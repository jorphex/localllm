from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from benchmarks.barrage_v2 import SCHEMA_VERSION
from benchmarks.barrage_v2.openwendy_driver import harness_metadata, live_service_identity, run_request
from benchmarks.gpu_safety import GpuSafetyError, GpuSafetyGuard


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_ENV = ROOT / "config" / "localllm-main.env"
TASKS_PATH = ROOT / "benchmarks" / "barrage_v2" / "openwendy_tasks.json"
OPENWENDY_ROOT = Path("/home/j/projects/openwendy")
MAIN_BASE_URL = "http://127.0.0.1:8091"
OPENWENDY_BASE_URL = "http://127.0.0.1:7347"
MODEL_ID = "local"


@dataclass(frozen=True)
class Arm:
    name: str
    threads: int
    threads_batch: int
    mtp_n: int


ARMS = {
    "current": Arm("current", threads=10, threads_batch=8, mtp_n=2),
    "finalist": Arm("finalist", threads=12, threads_batch=12, mtp_n=4),
}
RUN_ORDER = (("current", 1), ("finalist", 1), ("finalist", 2), ("current", 2), ("current", 3), ("finalist", 3))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def env_values(payload: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in payload.decode("utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def arm_env(original: bytes, arm: Arm) -> bytes:
    text = original.decode("utf-8")
    text, thread_count = re.subn(r"(?m)^MAIN_THREADS=\d+$", f"MAIN_THREADS={arm.threads}", text)
    if thread_count != 1:
        raise ValueError("active env must contain exactly one MAIN_THREADS setting")
    lines = text.splitlines(keepends=True)
    extra_indexes = [index for index, line in enumerate(lines) if line.startswith("MAIN_EXTRA_ARGS=")]
    if len(extra_indexes) != 1:
        raise ValueError("active env must contain exactly one MAIN_EXTRA_ARGS setting")
    index = extra_indexes[0]
    ending = "\n" if lines[index].endswith("\n") else ""
    value = lines[index].removeprefix("MAIN_EXTRA_ARGS=").rstrip("\n")
    value, tb_count = re.subn(r"(?<!\S)-tb\s+\d+(?!\S)", f"-tb {arm.threads_batch}", value)
    value, mtp_count = re.subn(
        r"(?<!\S)--spec-draft-n-max\s+\d+(?!\S)",
        f"--spec-draft-n-max {arm.mtp_n}",
        value,
    )
    if tb_count != 1 or mtp_count != 1:
        raise ValueError("active env must contain one batch-thread and one MTP draft setting")
    lines[index] = f"MAIN_EXTRA_ARGS={value}{ending}"
    result = "".join(lines).encode("utf-8")
    before = env_values(original)
    after = env_values(result)
    changed = {key for key in before | after if before.get(key) != after.get(key)}
    if not changed <= {"MAIN_THREADS", "MAIN_EXTRA_ARGS"}:
        raise ValueError(f"arm mutation changed unexpected env keys: {sorted(changed)}")
    return result


def atomic_write(path: Path, payload: bytes) -> None:
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def command(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def service_pid() -> int:
    value = command(["systemctl", "--user", "show", "-p", "MainPID", "--value", "localllm-main.service"]).stdout.strip()
    pid = int(value)
    if pid <= 0:
        raise RuntimeError("localllm-main has no live MainPID")
    return pid


def process_argv(pid: int) -> list[str]:
    return [part.decode() for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]


def argument_value(argv: list[str], flag: str) -> str:
    matches = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == flag]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {flag} argument")
    return matches[0]


def assert_arm_argv(argv: list[str], arm: Arm) -> None:
    expected = {"-t": arm.threads, "-tb": arm.threads_batch, "--spec-draft-n-max": arm.mtp_n}
    for flag, value in expected.items():
        if int(argument_value(argv, flag)) != value:
            raise ValueError(f"live {flag} does not match {arm.name} arm")
    if argument_value(argv, "-ctk") != "q8_0" or argument_value(argv, "-ctv") != "q8_0":
        raise ValueError("live main service is not using Q8 K/V")
    if argument_value(argv, "--spec-type") != "draft-mtp":
        raise ValueError("live main service is not using draft-mtp")


def wait_service(active: bool, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "localllm-main.service"],
            check=False,
        ).returncode == 0
        if state == active:
            return
        time.sleep(1)
    raise TimeoutError(f"localllm-main did not become {'active' if active else 'inactive'}")


def wait_health(timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{MAIN_BASE_URL}/health", timeout=3) as response:  # noqa: S310
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise TimeoutError("localllm-main health endpoint did not become ready")


def transition(guard: GpuSafetyGuard, env_payload: bytes, arm: Arm, transition_index: int) -> list[str]:
    guard.check(f"transition-{transition_index}-pre-stop.log")
    command(["systemctl", "--user", "stop", "localllm-main.service"], timeout=90)
    wait_service(False)
    guard.stabilize(f"transition-{transition_index}-post-stop.log")
    atomic_write(ACTIVE_ENV, env_payload)
    command(["systemctl", "--user", "daemon-reload"])
    command(["systemctl", "--user", "start", "localllm-main.service"], timeout=90)
    wait_health()
    guard.stabilize(f"transition-{transition_index}-post-load.log")
    argv = process_argv(service_pid())
    assert_arm_argv(argv, arm)
    return argv


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(output_dir: Path, *, stabilize_seconds: int = 30) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    original = ACTIVE_ENV.read_bytes()
    original_hash = sha256_bytes(original)
    arm_payloads = {name: arm_env(original, arm) for name, arm in ARMS.items()}
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    harness = harness_metadata(OPENWENDY_ROOT)
    service_identity = live_service_identity(OPENWENDY_BASE_URL, OPENWENDY_ROOT)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "original_env_sha256": original_hash,
        "tasks_sha256": sha256_file(TASKS_PATH),
        "openwendy_config_sha256": sha256_file(OPENWENDY_ROOT / "config.toml"),
        "harness": harness,
        "openwendy_service_identity": service_identity,
        "run_order": [{"arm": arm, "repeat": repeat} for arm, repeat in RUN_ORDER],
        "arms": {name: vars(arm) for name, arm in ARMS.items()},
    }
    write_json(output_dir / "manifest.json", manifest)
    guard = GpuSafetyGuard(output_dir / "safety", stabilize_seconds=stabilize_seconds)
    results: list[dict[str, Any]] = []
    current_arm = "current"
    transition_index = 0
    safety_fault = False
    restored = False

    def emergency_stop() -> None:
        subprocess.run(["systemctl", "--user", "stop", "localllm-main.service"], check=False, timeout=60)

    try:
        guard.start()
        guard.start_monitor(None, "openwendy-ab", fault_callback=emergency_stop)
        initial_argv = process_argv(service_pid())
        assert_arm_argv(initial_argv, ARMS["current"])
        for order_index, (arm_name, repeat) in enumerate(RUN_ORDER, start=1):
            guard.check(f"run-{order_index}-preflight.log")
            if arm_name != current_arm:
                transition_index += 1
                launch_argv = transition(guard, arm_payloads[arm_name], ARMS[arm_name], transition_index)
                current_arm = arm_name
            else:
                launch_argv = process_argv(service_pid())
                assert_arm_argv(launch_argv, ARMS[arm_name])
            request = {
                "schema_version": SCHEMA_VERSION,
                "profile": {"class": "production", "id": f"openwendy-ab-{arm_name}"},
                "harness": harness,
                "candidate": {"model": MODEL_ID, "model_path": None},
                "tasks": tasks,
                "launch": {"argv": launch_argv},
            }
            started = time.perf_counter()
            payload = run_request(
                request,
                base_url=OPENWENDY_BASE_URL,
                model_id=MODEL_ID,
                timeout=900,
                root=OPENWENDY_ROOT,
            )
            row = {
                "order_index": order_index,
                "arm": arm_name,
                "repeat": repeat,
                "elapsed_seconds": round(time.perf_counter() - started, 4),
                "launch_argv": launch_argv,
                "passed": all(bool(result["passed"]) for result in payload["results"]),
                "results": payload["results"],
                "driver_metadata": payload["driver_metadata"],
            }
            results.append(row)
            write_json(output_dir / "runs" / f"{order_index:02d}-{arm_name}-{repeat}.json", row)
            guard.check(f"run-{order_index}-post.log")
    except GpuSafetyError:
        safety_fault = True
        raise
    finally:
        try:
            guard.stop_monitor()
            safety_fault = safety_fault or bool(guard.fault_lines)
            if not safety_fault:
                try:
                    guard.check("pre-restore.log")
                except GpuSafetyError:
                    safety_fault = True
                    raise
                if ACTIVE_ENV.read_bytes() != original or current_arm != "current":
                    transition_index += 1
                    transition(guard, original, ARMS["current"], transition_index)
                if ACTIVE_ENV.read_bytes() != original or sha256_file(ACTIVE_ENV) != original_hash:
                    raise RuntimeError("active main env was not restored byte-for-byte")
                guard.check("post-restore.log")
                restored = True
        finally:
            write_json(
                output_dir / "safety" / "completion.json",
                {
                    "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "safety_fault": safety_fault,
                    "restored": restored,
                    "completed_runs": len(results),
                },
            )
            guard.close()
    if safety_fault:
        raise GpuSafetyError("OpenWendy A/B stopped after a kernel safety fault; production was not reloaded")
    summary = {
        "status": "completed" if len(results) == len(RUN_ORDER) else "incomplete",
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "original_env_sha256": original_hash,
        "restored_env_sha256": sha256_file(ACTIVE_ENV),
        "runs": results,
    }
    write_json(output_dir / "run.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded OpenWendy current/finalist attribution run")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--stabilize-seconds", type=int, default=30)
    args = parser.parse_args()
    result = run(args.output_dir, stabilize_seconds=args.stabilize_seconds)
    return 0 if result["status"] == "completed" and all(row["passed"] for row in result["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
