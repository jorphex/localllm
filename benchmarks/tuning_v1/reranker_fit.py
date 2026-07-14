from __future__ import annotations

import argparse
import json
import os
import re
import signal
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from benchmarks.barrage_v2.workloads import context_recall_prompt, repeated_prompt
from benchmarks.gpu_safety import GpuSafetyError, GpuSafetyGuard
from benchmarks.tuning_v1.runner import content_text, memory_state, request_json, response_metrics


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_ENV = ROOT / "config" / "localllm-main.env"
SERVER_BIN = Path.home() / ".local/src/llama.cpp/build-vulkan-r9700/bin/llama-server"
MAIN_PORT = 9731
RERANKER_URL = "http://127.0.0.1:8093"
LAYER_RE = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")

PROFILES: dict[str, dict[str, Any]] = {
    "qwen35-unsloth": {
        "model": "qwen-3.6/Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf",
        "mmproj": "qwen-3.6/Qwen3.6-35B-A3B-mmproj-F16-unsloth.gguf",
        "context": 163840,
        "batch": 4096,
        "ubatch": 2048,
        "threads": 10,
        "threads_batch": 8,
        "checkpoints": 8,
        "max_gpu_layers": 41,
        "min_gpu_layers": 28,
        "spec_args": [],
    },
    "qwen35-huihui": {
        "model": "qwen-3.6/Huihui-Qwen3.6-35B-A3B-abliterated-MTP-Q6_K.gguf",
        "mmproj": "qwen-3.6/Huihui-Qwen3.6-35B-A3B-abliterated-MTP-mmproj-f16.gguf",
        "context": 262144,
        "batch": 1024,
        "ubatch": 512,
        "threads": 10,
        "threads_batch": 8,
        "checkpoints": 8,
        "max_gpu_layers": 42,
        "min_gpu_layers": 28,
        "spec_args": ["--spec-type", "draft-mtp", "--spec-draft-n-max", "3"],
    },
}


def json_write(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def layer_candidates(profile: dict[str, Any]) -> list[int]:
    return list(range(int(profile["max_gpu_layers"]), int(profile["min_gpu_layers"]) - 1, -1))


def build_command(profile: dict[str, Any], gpu_layers: int, slot_dir: Path) -> list[str]:
    return [
        str(SERVER_BIN),
        "-m",
        str(ROOT / "models" / profile["model"]),
        "-mm",
        str(ROOT / "models" / profile["mmproj"]),
        "--host",
        "127.0.0.1",
        "--port",
        str(MAIN_PORT),
        "--alias",
        f"reranker-fit-{gpu_layers}",
        "--device",
        "Vulkan0",
        "--gpu-layers",
        str(gpu_layers),
        "--fit",
        "off",
        "-v",
        "-t",
        str(profile["threads"]),
        "-c",
        str(profile["context"]),
        "-np",
        "1",
        "-tb",
        str(profile["threads_batch"]),
        "-b",
        str(profile["batch"]),
        "-ub",
        str(profile["ubatch"]),
        "-fa",
        "on",
        "--threads-http",
        "4",
        "-ctk",
        "q8_0",
        "-ctv",
        "q8_0",
        "-rea",
        "on",
        "--metrics",
        "--no-warmup",
        "--image-max-tokens",
        "8192",
        "--temp",
        "0.6",
        "--top-k",
        "20",
        "--top-p",
        "0.95",
        "--min-p",
        "0.0",
        "--presence-penalty",
        "0.0",
        "--repeat-penalty",
        "1.0",
        "--cache-prompt",
        "--cache-reuse",
        "0",
        "--cache-ram",
        "2048",
        "--slot-prompt-similarity",
        "0.10",
        "--ctx-checkpoints",
        str(profile["checkpoints"]),
        "--slot-save-path",
        str(slot_dir),
        *profile["spec_args"],
    ]


def wait_health(url: str, process: subprocess.Popen[bytes] | None = None, timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    last_error = "health timeout"
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"server exited with status {process.returncode}")
        try:
            request_json(url, timeout=5)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(1)
    raise TimeoutError(last_error)


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=20)


def reranker_probe() -> dict[str, Any]:
    body = {
        "model": "qwen3-reranker-4b-q4",
        "query": "Which document discusses local language-model inference?",
        "documents": ["A vegetable soup recipe.", "Running a quantized language model on a local GPU."],
    }
    started = time.perf_counter()
    payload = request_json(f"{RERANKER_URL}/v1/rerank", body, timeout=60)
    elapsed = time.perf_counter() - started
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 2:
        raise RuntimeError("reranker returned an invalid response")
    return {"elapsed_seconds": round(elapsed, 6), "response": payload}


def workloads(profile: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any], tuple[str, ...]]]:
    long_repeat = min(6600, max(500, int(profile["context"]) // 19))
    recall_prompt, expected = context_recall_prompt(long_repeat)
    return {
        "short_pp": (
            "/completion",
            {"prompt": repeated_prompt(80), "n_predict": 1, "temperature": 0, "cache_prompt": False},
            (),
        ),
        "long_pp": (
            "/completion",
            {"prompt": repeated_prompt(long_repeat), "n_predict": 1, "temperature": 0, "cache_prompt": False},
            (),
        ),
        "short_tg": (
            "/completion",
            {
                "prompt": "Write a numbered deployment checklist with repetitive CHECK, VERIFY, and RECORD fields.",
                "n_predict": 128,
                "temperature": 0,
                "ignore_eos": True,
                "cache_prompt": False,
            },
            (),
        ),
        "long_context_tg": (
            "/v1/chat/completions",
            {
                "messages": [{"role": "user", "content": recall_prompt}],
                "max_tokens": 32,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
                "cache_prompt": False,
            },
            expected,
        ),
    }


def placement_from_log(log_path: Path) -> dict[str, int] | None:
    matches = LAYER_RE.findall(log_path.read_text(encoding="utf-8", errors="replace"))
    if not matches:
        return None
    loaded, total = matches[-1]
    return {"gpu_layers": int(loaded), "total_layers": int(total), "cpu_layers": int(total) - int(loaded)}


def effective_placement(log_path: Path, requested: int, total: int) -> dict[str, Any]:
    placement = placement_from_log(log_path)
    if placement is not None:
        return {**placement, "evidence": "server_log"}
    return {
        "gpu_layers": requested,
        "total_layers": total,
        "cpu_layers": total - requested,
        "evidence": "fixed_gpu_layers_with_fit_disabled",
    }


class Study:
    def __init__(self, output_dir: Path, repeats: int) -> None:
        self.output_dir = output_dir
        self.repeats = repeats
        self.output_dir.mkdir(parents=True, exist_ok=False)
        (self.output_dir / "logs").mkdir()
        (self.output_dir / "slots").mkdir()
        self.safety = GpuSafetyGuard(output_dir / "safety", stabilize_seconds=30)
        self.trials_path = output_dir / "trials.jsonl"
        self.run_path = output_dir / "run.json"
        self.current_process: subprocess.Popen[bytes] | None = None
        self.current_log_handle: Any = None
        self.stack_stopped = False
        self.safety_fault = False
        self.original_hash = ""
        self.run: dict[str, Any] = {
            "schema_version": "reranker-fit-v1.0",
            "started_at": datetime.now(UTC).isoformat(),
            "repeats": repeats,
            "profiles": PROFILES,
            "fit_attempts": [],
            "finalists": [],
        }

    def persist(self) -> None:
        json_write(self.run_path, self.run)

    def stop_gpu_services(self) -> None:
        stop_process(self.current_process)
        subprocess.run(
            ["systemctl", "--user", "stop", "localllm-main.service", "localllm-reranker.service"],
            check=False,
        )

    def monitored_transition(self, name: str, action: Callable[[], None]) -> None:
        self.safety.start_monitor(None, name, fault_callback=self.stop_gpu_services)
        try:
            action()
        finally:
            try:
                self.safety.stabilize(f"{name}-stabilized.log")
            finally:
                self.safety.stop_monitor()

    def prepare(self) -> None:
        self.safety.start()
        self.original_hash = subprocess.check_output(["sha256sum", str(ACTIVE_ENV)], text=True).split()[0]
        self.stack_stopped = True
        self.monitored_transition(
            "stack-stop",
            lambda: subprocess.run([str(ROOT / "scripts" / "stop-stack.sh")], cwd=ROOT, check=True),
        )
        baseline = memory_state()
        if baseline["vram_used_mib"] is None or baseline["vram_used_mib"] > 1024:
            raise RuntimeError(f"VRAM baseline is not clean: {baseline}")
        if baseline["available_ram_mib"] is None or baseline["available_ram_mib"] < 12000:
            raise RuntimeError(f"available RAM is below safety gate: {baseline}")
        if baseline["free_swap_mib"] is None or baseline["free_swap_mib"] < 1200:
            raise RuntimeError(f"free swap is below safety gate: {baseline}")
        self.run["unloaded_baseline"] = baseline

        def start_reranker() -> None:
            subprocess.run(["systemctl", "--user", "start", "localllm-reranker.service"], check=True)
            wait_health(f"{RERANKER_URL}/health", timeout=240)

        self.monitored_transition("reranker-load", start_reranker)
        self.run["reranker_only"] = {
            "pid": self.reranker_pid(),
            "resource": memory_state(),
            "probe": reranker_probe(),
        }
        self.persist()

    @staticmethod
    def reranker_pid() -> int:
        value = subprocess.check_output(
            ["systemctl", "--user", "show", "-p", "MainPID", "--value", "localllm-reranker.service"],
            text=True,
        ).strip()
        pid = int(value)
        if pid <= 0:
            raise RuntimeError("reranker has no live MainPID")
        return pid

    def start_main(self, model_id: str, profile: dict[str, Any], gpu_layers: int) -> tuple[subprocess.Popen[bytes], Path]:
        log_path = self.output_dir / "logs" / f"{model_id}-gpu{gpu_layers}.log"
        command = build_command(profile, gpu_layers, self.output_dir / "slots" / f"{model_id}-gpu{gpu_layers}")
        Path(command[command.index("--slot-save-path") + 1]).mkdir(parents=True, exist_ok=True)
        self.current_log_handle = log_path.open("ab", buffering=0)
        env = {**os.environ, "LD_LIBRARY_PATH": f"{SERVER_BIN.parent}:{os.environ.get('LD_LIBRARY_PATH', '')}"}
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=self.current_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        self.current_process = process
        self.safety.start_monitor(process.pid, f"{model_id}-gpu{gpu_layers}", fault_callback=self.stop_gpu_services)
        return process, log_path

    def stop_main(self, label: str) -> None:
        stop_process(self.current_process)
        self.current_process = None
        if self.current_log_handle is not None:
            self.current_log_handle.close()
            self.current_log_handle = None
        try:
            self.safety.stabilize(f"{label}-post-unload.log")
        finally:
            self.safety.stop_monitor()

    def find_fit(self, model_id: str, profile: dict[str, Any]) -> tuple[int, subprocess.Popen[bytes], Path]:
        original_reranker_pid = self.reranker_pid()
        for gpu_layers in layer_candidates(profile):
            resource_before = memory_state()
            if resource_before["available_ram_mib"] is None or resource_before["available_ram_mib"] < 12000:
                raise RuntimeError(f"available RAM is below safety gate: {resource_before}")
            if resource_before["free_swap_mib"] is None or resource_before["free_swap_mib"] < 1200:
                raise RuntimeError(f"free swap is below safety gate: {resource_before}")
            process, log_path = self.start_main(model_id, profile, gpu_layers)
            attempt: dict[str, Any] = {
                "model_id": model_id,
                "requested_gpu_layers": gpu_layers,
                "argv": build_command(profile, gpu_layers, self.output_dir / "slots" / f"{model_id}-gpu{gpu_layers}"),
                "resource_before": resource_before,
                "log": str(log_path),
            }
            try:
                wait_health(f"http://127.0.0.1:{MAIN_PORT}/health", process, timeout=300)
                self.safety.stabilize(f"{model_id}-gpu{gpu_layers}-post-load.log")
                if self.reranker_pid() != original_reranker_pid:
                    raise RuntimeError("reranker process restarted during main-model load")
                wait_health(f"{RERANKER_URL}/health", timeout=30)
                attempt.update(
                    {
                        "status": "fit",
                        "placement": effective_placement(log_path, gpu_layers, int(profile["max_gpu_layers"])),
                        "resource_after": memory_state(),
                        "reranker_probe": reranker_probe(),
                    }
                )
                self.run["fit_attempts"].append(attempt)
                self.persist()
                return gpu_layers, process, log_path
            except GpuSafetyError:
                self.safety_fault = True
                attempt["status"] = "safety_fault"
                self.run["fit_attempts"].append(attempt)
                self.persist()
                raise
            except Exception as exc:  # a clean startup/OOM rejection is fit evidence
                attempt.update({"status": "rejected", "error": str(exc), "resource_after": memory_state()})
                self.run["fit_attempts"].append(attempt)
                self.persist()
                self.stop_main(f"{model_id}-gpu{gpu_layers}-rejected")
                if self.reranker_pid() != original_reranker_pid:
                    raise RuntimeError("reranker process restarted during a rejected fit attempt") from exc
        raise RuntimeError(f"no co-resident placement found for {model_id}")

    def benchmark(self, model_id: str, profile: dict[str, Any], gpu_layers: int, log_path: Path) -> None:
        finalist = {
            "model_id": model_id,
            "gpu_layers": gpu_layers,
            "placement": effective_placement(log_path, gpu_layers, int(profile["max_gpu_layers"])),
            "resource_start": memory_state(),
            "reranker_pid": self.reranker_pid(),
            "reranker_probe_before": reranker_probe(),
        }
        for workload, (endpoint, body, expected) in workloads(profile).items():
            for repeat in range(1, self.repeats + 1):
                started = time.perf_counter()
                payload = request_json(f"http://127.0.0.1:{MAIN_PORT}{endpoint}", body, timeout=900)
                elapsed = time.perf_counter() - started
                self.safety.check(f"{model_id}-{workload}-{repeat}.log")
                text = content_text(payload)
                passed = not expected or all(marker in text for marker in expected)
                row = {
                    "model_id": model_id,
                    "gpu_layers": gpu_layers,
                    "workload": workload,
                    "repeat": repeat,
                    "passed": passed,
                    **response_metrics(payload, elapsed),
                    "resource_after": memory_state(),
                }
                append_jsonl(self.trials_path, row)
        finalist["resource_end"] = memory_state()
        finalist["reranker_probe_after"] = reranker_probe()
        self.run["finalists"].append(finalist)
        self.persist()

    def restore(self) -> None:
        if self.current_process is not None:
            self.stop_main("cleanup-main")
        self.safety.stop_monitor()
        if not self.stack_stopped:
            return
        if self.safety_fault:
            self.stop_gpu_services()
            return

        def stop_reranker() -> None:
            subprocess.run(["systemctl", "--user", "stop", "localllm-reranker.service"], check=True)

        self.monitored_transition("reranker-unload", stop_reranker)
        self.safety.check("pre-stack-restore.log")

        def start_stack() -> None:
            subprocess.run([str(ROOT / "scripts" / "start-stack.sh")], cwd=ROOT, check=True)

        self.monitored_transition("stack-restore", start_stack)
        restored_hash = subprocess.check_output(["sha256sum", str(ACTIVE_ENV)], text=True).split()[0]
        if restored_hash != self.original_hash:
            raise RuntimeError("active main configuration changed during fit study")
        self.stack_stopped = False

    def finish(self) -> None:
        rows = [json.loads(line) for line in self.trials_path.read_text(encoding="utf-8").splitlines() if line]
        medians: dict[str, dict[str, float | None]] = {}
        for model_id in PROFILES:
            medians[model_id] = {}
            for workload in workloads(PROFILES[model_id]):
                matches = [row for row in rows if row["model_id"] == model_id and row["workload"] == workload]
                metric = "predicted_per_second" if "tg" in workload else "prompt_per_second"
                values = [float(row[metric]) for row in matches if row.get(metric) is not None]
                medians[model_id][workload] = round(statistics.median(values), 4) if values else None
        self.run.update(
            {
                "completed_at": datetime.now(UTC).isoformat(),
                "status": "passed",
                "medians": medians,
            }
        )
        self.persist()

    def execute(self) -> None:
        try:
            self.prepare()
            for model_id, profile in PROFILES.items():
                gpu_layers, _, log_path = self.find_fit(model_id, profile)
                self.benchmark(model_id, profile, gpu_layers, log_path)
                self.stop_main(f"{model_id}-complete")
            self.restore()
            self.finish()
        except GpuSafetyError:
            self.safety_fault = True
            self.run["status"] = "safety_fault"
            self.persist()
            raise
        except Exception as exc:
            self.run.update({"status": "error", "error": str(exc)})
            self.persist()
            raise
        finally:
            try:
                self.restore()
            finally:
                self.safety.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find 35B placements that coexist with the GPU reranker")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "benchmarks" / "tuning-v1-results" / f"35b-reranker-fit-{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
    )
    parser.add_argument("--repeats", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats < 1:
        raise ValueError("repeats must be positive")
    study = Study(args.output, args.repeats)
    study.execute()
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
