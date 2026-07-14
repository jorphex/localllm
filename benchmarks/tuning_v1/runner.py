from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.barrage_v2.workloads import context_recall_prompt, release_tool, repeated_prompt
from benchmarks.gpu_safety import GpuSafetyError, GpuSafetyGuard
from benchmarks.tuning_v1 import SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
DEFAULT_RESULTS = ROOT / "benchmarks" / "tuning-v1-results"
ACTIVE_ENV = ROOT / "config" / "localllm-main.env"
ACCEPTANCE_RE = re.compile(
    r"draft acceptance =\s*([0-9.]+)\s*\(\s*(\d+) accepted /\s*(\d+) generated\),\s*"
    r"mean (?:acceptance length|len) =\s*([0-9.]+)(?:, acceptance rate per position = \(([^)]*)\))?"
)


def json_dump(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def memory_state() -> dict[str, Any]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) // 1024
    vram_used: int | None = None
    vram_total: int | None = None
    gpu: dict[str, Any] = {}
    try:
        proc = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        card = next(value for key, value in json.loads(proc.stdout).items() if key.startswith("card"))
        vram_used = int(card.get("VRAM Total Used Memory (B)", 0)) // 1048576
        vram_total = int(card.get("VRAM Total Memory (B)", 0)) // 1048576
    except (OSError, StopIteration, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        pass
    try:
        hardware = subprocess.run(
            ["rocm-smi", "--showtemp", "--showclocks", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        card = next(value for key, value in json.loads(hardware.stdout).items() if key.startswith("card"))
        gpu = {
            "edge_temp_c": card.get("Temperature (Sensor edge) (C)"),
            "junction_temp_c": card.get("Temperature (Sensor junction) (C)"),
            "memory_temp_c": card.get("Temperature (Sensor memory) (C)"),
            "sclk": card.get("sclk clock speed:"),
            "mclk": card.get("mclk clock speed:"),
        }
    except (OSError, StopIteration, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        pass
    return {
        "available_ram_mib": values.get("MemAvailable"),
        "free_swap_mib": values.get("SwapFree"),
        "vram_used_mib": vram_used,
        "vram_free_mib": None if vram_used is None or vram_total is None else vram_total - vram_used,
        "gpu": gpu,
    }


def request_json(url: str, body: dict[str, Any] | None = None, timeout: int = 900) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def parse_acceptance(text: str) -> dict[str, Any] | None:
    matches = list(ACCEPTANCE_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    positions = []
    if match.group(5):
        positions = [float(value.strip()) for value in match.group(5).split(",") if value.strip()]
    return {
        "acceptance": float(match.group(1)),
        "accepted": int(match.group(2)),
        "proposed": int(match.group(3)),
        "mean_acceptance_length": float(match.group(4)),
        "acceptance_per_position": positions,
    }


def response_metrics(payload: dict[str, Any], elapsed: float) -> dict[str, Any]:
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "elapsed_seconds": round(elapsed, 6),
        "prompt_n": timings.get("prompt_n") or usage.get("prompt_tokens"),
        "predicted_n": timings.get("predicted_n") or usage.get("completion_tokens"),
        "prompt_per_second": timings.get("prompt_per_second"),
        "predicted_per_second": timings.get("predicted_per_second"),
        "cache_n": timings.get("cache_n"),
    }


def content_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("content"), str):
        return payload["content"]
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            return str(message.get("content") or message.get("reasoning_content") or "")
    return ""


def structured_call_valid(payload: dict[str, Any]) -> bool:
    try:
        calls = payload["choices"][0]["message"]["tool_calls"]
        call = calls[0]["function"]
        arguments = call["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        return call["name"] == "release_lookup" and arguments == {"package": "barrage", "channel": "stable"}
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        return False


def candidate_id(candidate: dict[str, Any]) -> str:
    spec = candidate["spec_type"].replace(",", "+")
    return (
        f"{candidate['model_id']}-c{candidate['context']}-b{candidate['batch']}-u{candidate['ubatch']}"
        f"-t{candidate['threads']}-tb{candidate['threads_batch']}-cp{candidate['checkpoints']}-{spec}"
        f"-n{candidate.get('mtp_n', 0)}"
    )


def make_candidate(
    model_id: str,
    model: dict[str, Any],
    *,
    context: int,
    batch: int,
    ubatch: int,
    threads: int = 10,
    threads_batch: int = 8,
    checkpoints: int = 0,
    spec_type: str = "none",
    mtp_n: int = 0,
) -> dict[str, Any]:
    candidate = {
        "model_id": model_id,
        "model": model["model"],
        "mmproj": model["mmproj"],
        "context": context,
        "batch": batch,
        "ubatch": ubatch,
        "threads": threads,
        "threads_batch": threads_batch,
        "checkpoints": checkpoints,
        "spec_type": spec_type,
        "mtp_n": mtp_n,
    }
    candidate["id"] = candidate_id(candidate)
    return candidate


def phase_candidates(config: dict[str, Any], phase: str, prior_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    models = config["models"]
    main = models["qwen27-unsloth"]
    if phase == "main-shape":
        shapes = [
            (1024, 512, 10, 8),
            (2048, 512, 10, 8),
            (2048, 1024, 10, 8),
            (4096, 1024, 10, 8),
            (4096, 2048, 10, 8),
            (2048, 1024, 8, 8),
            (2048, 1024, 12, 12),
        ]
        return [
            make_candidate("qwen27-unsloth", main, context=32768, batch=b, ubatch=u, threads=t, threads_batch=tb)
            for b, u, t, tb in shapes
        ]
    if phase == "main-spec":
        shape = best_shape(prior_rows, "qwen27-unsloth") or main["production"]
        common = {
            "context": 32768,
            "batch": int(shape["batch"]),
            "ubatch": int(shape["ubatch"]),
            "threads": int(shape["threads"]),
            "threads_batch": int(shape["threads_batch"]),
        }
        candidates = [make_candidate("qwen27-unsloth", main, **common)]
        candidates.extend(
            make_candidate("qwen27-unsloth", main, **common, spec_type="draft-mtp", mtp_n=n) for n in (1, 2, 3, 4)
        )
        candidates.append(make_candidate("qwen27-unsloth", main, **common, spec_type="draft-mtp,ngram-cache", mtp_n=2))
        return candidates
    if phase == "main-context":
        spec = best_candidate(prior_rows, "qwen27-unsloth", phases={"main-spec"})
        production = main["production"]
        shape = spec or {
            "batch": production["batch"],
            "ubatch": production["ubatch"],
            "threads": production["threads"],
            "threads_batch": production["threads_batch"],
            "spec_type": "draft-mtp",
            "mtp_n": production["mtp_n"],
        }
        candidates = []
        for context in (32768, 131072):
            checkpoints = (0,) if context == 32768 else (0, 4)
            for checkpoint in checkpoints:
                for spec_type, mtp_n in (("none", 0), (shape["spec_type"], int(shape.get("mtp_n", 0)))):
                    candidates.append(
                        make_candidate(
                            "qwen27-unsloth",
                            main,
                            context=context,
                            batch=int(shape["batch"]),
                            ubatch=int(shape["ubatch"]),
                            threads=int(shape["threads"]),
                            threads_batch=int(shape["threads_batch"]),
                            checkpoints=checkpoint,
                            spec_type=spec_type,
                            mtp_n=mtp_n,
                        )
                    )
        return unique_candidates(candidates)
    if phase == "other-models":
        candidates = []
        for model_id in ("qwen27-huihui", "qwen35-unsloth", "qwen35-huihui"):
            model = models[model_id]
            production = model["production"]
            bases = [(1024, 512), (int(production["batch"]), int(production["ubatch"]))]
            for batch, ubatch in bases:
                candidates.append(make_candidate(model_id, model, context=32768, batch=batch, ubatch=ubatch))
            n_values = (2, 3, 4) if model_id == "qwen27-huihui" else (1, 2, 3)
            for n in n_values:
                candidates.append(
                    make_candidate(
                        model_id,
                        model,
                        context=32768,
                        batch=int(production["batch"]),
                        ubatch=int(production["ubatch"]),
                        threads=int(production["threads"]),
                        threads_batch=int(production["threads_batch"]),
                        spec_type="draft-mtp",
                        mtp_n=n,
                    )
                )
        return unique_candidates(candidates)
    if phase == "validation":
        candidates = []
        for model_id, model in models.items():
            winner = best_candidate(prior_rows, model_id)
            production = model["production"]
            source = winner or {
                **production,
                "spec_type": "draft-mtp",
                "mtp_n": production["mtp_n"],
            }
            candidates.append(
                make_candidate(
                    model_id,
                    model,
                    context=int(model["max_context"]),
                    batch=int(source["batch"]),
                    ubatch=int(source["ubatch"]),
                    threads=int(source["threads"]),
                    threads_batch=int(source["threads_batch"]),
                    checkpoints=int(production["checkpoints"]),
                    spec_type=str(source["spec_type"]),
                    mtp_n=int(source.get("mtp_n", 0)),
                )
            )
        return candidates
    if phase == "validation-controls":
        controls = []
        for model_id in ("qwen27-unsloth", "qwen27-huihui", "qwen35-huihui"):
            model = models[model_id]
            production = model["production"]
            threads = 12 if model_id == "qwen27-unsloth" else int(production["threads"])
            threads_batch = 12 if model_id == "qwen27-unsloth" else int(production["threads_batch"])
            controls.append(
                make_candidate(
                    model_id,
                    model,
                    context=int(model["max_context"]),
                    batch=int(production["batch"]),
                    ubatch=int(production["ubatch"]),
                    threads=threads,
                    threads_batch=threads_batch,
                    checkpoints=int(production["checkpoints"]),
                )
            )
        production = main["production"]
        controls.append(
            make_candidate(
                "qwen27-unsloth",
                main,
                context=int(main["max_context"]),
                batch=int(production["batch"]),
                ubatch=int(production["ubatch"]),
                threads=int(production["threads"]),
                threads_batch=int(production["threads_batch"]),
                checkpoints=int(production["checkpoints"]),
                spec_type="draft-mtp",
                mtp_n=int(production["mtp_n"]),
            )
        )
        return controls
    raise ValueError(f"unknown phase: {phase}")


def unique_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({candidate["id"]: candidate for candidate in candidates}.values())


def workload_names(phase: str) -> tuple[str, ...]:
    if phase == "main-context":
        return ("cold_pp_long", "context_recall", "warm_append")
    if phase in {"validation", "validation-controls"}:
        return (
            "cold_pp_short",
            "cold_pp_long",
            "deterministic_tg",
            "sampled_agent_tg",
            "structured_tool_tg",
            "context_recall",
            "warm_append",
        )
    return ("cold_pp_short", "cold_pp_long", "deterministic_tg", "sampled_agent_tg", "structured_tool_tg")


def build_command(config: dict[str, Any], candidate: dict[str, Any], log_path: Path) -> list[str]:
    runtime = config["runtime"]
    invariant = config["invariants"]
    model_path = ROOT / "models" / candidate["model"]
    mmproj_path = ROOT / "models" / candidate["mmproj"]
    command = [
        runtime["server_bin"],
        "-m",
        str(model_path),
        "-mm",
        str(mmproj_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(runtime["port"]),
        "--alias",
        candidate["id"],
        "--device",
        invariant["device"] if "device" in invariant else runtime["device"],
        "--gpu-layers",
        str(invariant["gpu_layers"]),
        "--fit",
        "on" if invariant["fit"] else "off",
        "-t",
        str(candidate["threads"]),
        "-tb",
        str(candidate["threads_batch"]),
        "-c",
        str(candidate["context"]),
        "-np",
        str(invariant["parallel"]),
        "-b",
        str(candidate["batch"]),
        "-ub",
        str(candidate["ubatch"]),
        "-fa",
        "on" if invariant["flash_attention"] else "off",
        "-ctk",
        invariant["cache_type_k"],
        "-ctv",
        invariant["cache_type_v"],
        "-rea",
        "on",
        "--threads-http",
        str(invariant["threads_http"]),
        "--metrics",
        "--no-warmup",
        "--image-max-tokens",
        str(invariant["image_max_tokens"]),
        "--cache-prompt",
        "--cache-ram",
        str(invariant["cache_ram_mib"]),
        "--cache-reuse",
        str(invariant["cache_reuse"]),
        "--slot-prompt-similarity",
        str(invariant["slot_prompt_similarity"]),
        "--ctx-checkpoints",
        str(candidate["checkpoints"]),
        "--spec-type",
        candidate["spec_type"],
        "--temp",
        "0.6",
        "--top-k",
        "20",
        "--top-p",
        "0.95",
        "--log-timestamps",
    ]
    if candidate["spec_type"] != "none":
        command.extend(["--spec-draft-n-max", str(candidate["mtp_n"])])
    command.extend(["--slot-save-path", str(log_path.parent.parent / "slots" / candidate["id"])])
    return command


def assert_invariants(command: list[str]) -> None:
    joined = " ".join(command)
    required = ("-ctk q8_0", "-ctv q8_0", "-fa on", "-np 1", "--gpu-layers auto")
    missing = [item for item in required if item not in joined]
    if missing:
        raise ValueError(f"candidate violates invariants: {missing}")
    if "q4_" in joined:
        raise ValueError("Q4 runtime cache is forbidden")


def best_shape(rows: list[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
    winner = best_candidate(rows, model_id, phases={"main-shape"})
    if not winner:
        return None
    return {key: winner[key] for key in ("batch", "ubatch", "threads", "threads_batch")}


def best_candidate(
    rows: list[dict[str, Any]], model_id: str, phases: set[str] | None = None
) -> dict[str, Any] | None:
    relevant = [
        row
        for row in rows
        if row.get("model_id") == model_id
        and (phases is None or row.get("phase") in phases)
        and row.get("workload") in {"cold_pp_long", "sampled_agent_tg", "structured_tool_tg"}
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in relevant:
        grouped.setdefault(str(row["candidate_id"]), []).append(row)
    scores: list[tuple[float, dict[str, Any]]] = []
    for candidate_rows in grouped.values():
        if any(row.get("status") != "ok" or row.get("passed") is not True for row in candidate_rows):
            continue
        by_workload = {
            name: [float(row["elapsed_seconds"]) for row in candidate_rows if row["workload"] == name]
            for name in ("cold_pp_long", "sampled_agent_tg", "structured_tool_tg")
        }
        if any(not values for values in by_workload.values()):
            continue
        score = (
            0.25 * statistics.median(by_workload["cold_pp_long"])
            + statistics.median(by_workload["sampled_agent_tg"])
            + statistics.median(by_workload["structured_tool_tg"])
        )
        scores.append((score, candidate_rows[0]["candidate"]))
    return min(scores, key=lambda item: item[0])[1] if scores else None


@dataclass
class Server:
    process: subprocess.Popen[bytes]
    log_path: Path
    log_handle: Any
    started_at: float

    def stop(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=20)
        self.log_handle.close()


class TuningRun:
    def __init__(self, config: dict[str, Any], out_dir: Path, *, resume: bool, retry_failed: bool) -> None:
        self.config = config
        self.out_dir = out_dir
        self.resume = resume
        self.retry_failed = retry_failed
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "logs").mkdir(exist_ok=True)
        self.trials_path = self.out_dir / "trials.jsonl"
        self.manifest_path = self.out_dir / "manifest.json"
        self.original_env = ACTIVE_ENV.read_bytes() if ACTIVE_ENV.exists() else None
        self.stack_stopped = False
        self.server: Server | None = None
        self.safety = GpuSafetyGuard(self.out_dir / "safety", stabilize_seconds=30)

    def rows(self) -> list[dict[str, Any]]:
        if not self.trials_path.exists():
            return []
        rows = []
        for line in self.trials_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def completed(self) -> set[str]:
        return {
            str(row["trial_id"])
            for row in self.rows()
            if not self.retry_failed or (row.get("status") == "ok" and row.get("passed") is True)
        }

    def append(self, row: dict[str, Any]) -> None:
        with self.trials_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def stop_stack(self) -> None:
        self.safety.start()
        self.stack_stopped = True
        subprocess.run([str(ROOT / "scripts" / "stop-stack.sh")], check=True, cwd=ROOT)
        self.safety.stabilize("post-stack-stop-kernel.log")

    def restore_stack(self) -> None:
        if self.original_env is None:
            ACTIVE_ENV.unlink(missing_ok=True)
        else:
            ACTIVE_ENV.write_bytes(self.original_env)
        if self.stack_stopped:
            self.safety.check("pre-stack-restore-kernel.log")
            subprocess.run([str(ROOT / "scripts" / "start-stack.sh")], check=True, cwd=ROOT)
            self.safety.stabilize("post-stack-restore-kernel.log")
            self.stack_stopped = False
        self.safety.close()

    def preflight(self) -> dict[str, Any]:
        state = memory_state()
        runtime = self.config["runtime"]
        if state["vram_used_mib"] is None or state["vram_used_mib"] > runtime["max_baseline_vram_mib"]:
            raise RuntimeError(f"VRAM baseline is not clean: {state}")
        if state["available_ram_mib"] is None or state["available_ram_mib"] < runtime["min_available_ram_mib"]:
            raise RuntimeError(f"available RAM is below gate: {state}")
        if state["free_swap_mib"] is None or state["free_swap_mib"] < runtime["min_free_swap_mib"]:
            raise RuntimeError(f"free swap is below gate: {state}")
        proc = subprocess.run(["pgrep", "-a", "llama-server"], capture_output=True, text=True, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            raise RuntimeError(f"unexpected llama-server process:\n{proc.stdout}")
        return state

    def start_candidate(self, candidate: dict[str, Any]) -> Server:
        attempts = len(list((self.out_dir / "logs").glob(f"{candidate['id']}-*.log"))) + 1
        log_path = self.out_dir / "logs" / f"{candidate['id']}-{attempts}.log"
        command = build_command(self.config, candidate, log_path)
        assert_invariants(command)
        slot_path = Path(command[command.index("--slot-save-path") + 1])
        slot_path.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("ab", buffering=0)
        env = {**os.environ, "LD_LIBRARY_PATH": f"{Path(command[0]).parent}:{os.environ.get('LD_LIBRARY_PATH', '')}"}
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        server = Server(process=process, log_path=log_path, log_handle=log_handle, started_at=time.monotonic())
        self.safety.start_monitor(process.pid, candidate["id"])
        deadline = time.monotonic() + self.config["runtime"]["startup_timeout_seconds"]
        url = f"http://127.0.0.1:{self.config['runtime']['port']}/health"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                server.stop()
                raise RuntimeError(f"server exited during startup; inspect {log_path}")
            try:
                request_json(url, timeout=5)
                self.safety.check(f"{candidate['id']}-post-load-kernel.log")
                self.server = server
                return server
            except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                time.sleep(1)
        server.stop()
        raise TimeoutError(f"server health timeout; inspect {log_path}")

    def run_request(self, candidate: dict[str, Any], workload: str, repeat: int, server: Server) -> dict[str, Any]:
        port = self.config["runtime"]["port"]
        timeout = self.config["runtime"]["request_timeout_seconds"]
        context = int(candidate["context"])
        long_repeat = 500 if context <= 32768 else min(6600, max(500, context // 19))
        log_offset = server.log_path.stat().st_size
        endpoint = "/completion"
        expected: tuple[str, ...] = ()
        if workload == "cold_pp_short":
            body = {"prompt": repeated_prompt(80), "n_predict": 1, "temperature": 0, "cache_prompt": False}
        elif workload == "cold_pp_long":
            body = {"prompt": repeated_prompt(long_repeat), "n_predict": 1, "temperature": 0, "cache_prompt": False}
        elif workload == "deterministic_tg":
            body = {
                "prompt": "Write a numbered deployment checklist with repetitive CHECK, VERIFY, and RECORD fields.",
                "n_predict": 128,
                "temperature": 0,
                "ignore_eos": True,
                "cache_prompt": False,
            }
        elif workload == "sampled_agent_tg":
            endpoint = "/v1/chat/completions"
            body = {
                "messages": [
                    {"role": "system", "content": "You are a coding agent. Reason from evidence and give concrete verification steps."},
                    {"role": "user", "content": repeated_prompt(32) + " Analyze a failing service and propose the next debugging actions."},
                ],
                "max_tokens": 128,
                "temperature": 0.6,
                "top_k": 20,
                "top_p": 0.95,
                "ignore_eos": True,
                "cache_prompt": False,
            }
        elif workload == "structured_tool_tg":
            endpoint = "/v1/chat/completions"
            body = {
                "messages": [{"role": "user", "content": "Use release_lookup to find the stable release of barrage."}],
                "tools": [release_tool()],
                "tool_choice": "required",
                "max_tokens": 96,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
                "cache_prompt": False,
            }
        elif workload == "context_recall":
            prompt, expected = context_recall_prompt(long_repeat)
            endpoint = "/v1/chat/completions"
            body = {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 32,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
                "cache_prompt": False,
            }
        elif workload == "warm_append":
            prefix = f"TUNING-{stable_hash([candidate['id'], repeat])[:16]} " + repeated_prompt(long_repeat)
            first_body = {"prompt": prefix + "\nState CHECK.", "n_predict": 1, "temperature": 0, "cache_prompt": True}
            started = time.perf_counter()
            first = request_json(f"http://127.0.0.1:{port}/completion", first_body, timeout=timeout)
            first_elapsed = time.perf_counter() - started
            body = {
                "prompt": prefix + "\nState CHECK.\nCHECK\nNow state VERIFY.",
                "n_predict": 1,
                "temperature": 0,
                "cache_prompt": True,
            }
        else:
            raise ValueError(workload)
        started = time.perf_counter()
        payload = request_json(f"http://127.0.0.1:{port}{endpoint}", body, timeout=timeout)
        elapsed = time.perf_counter() - started
        self.safety.check(f"{candidate['id']}-{workload}-{repeat}-kernel.log")
        time.sleep(0.1)
        with server.log_path.open("rb") as handle:
            handle.seek(log_offset)
            log_delta = handle.read().decode(errors="replace")
        metrics = response_metrics(payload, elapsed)
        text = content_text(payload)
        passed = True
        details: dict[str, Any] = {"content_prefix": text[:240]}
        if workload == "structured_tool_tg":
            passed = structured_call_valid(payload)
            details["structured_call_valid"] = passed
        elif workload == "context_recall":
            passed = all(marker in text for marker in expected)
            details["expected_markers"] = list(expected)
        elif workload == "warm_append":
            first_metrics = response_metrics(first, first_elapsed)
            details["first_request"] = first_metrics
            details["cache_ratio"] = (
                float(metrics["cache_n"]) / float(first_metrics["prompt_n"])
                if isinstance(metrics.get("cache_n"), (int, float))
                and isinstance(first_metrics.get("prompt_n"), (int, float))
                and first_metrics["prompt_n"]
                else None
            )
            passed = details["cache_ratio"] is not None and details["cache_ratio"] >= 0.8
        details["request"] = body
        details["response"] = payload
        return {
            **metrics,
            "passed": passed,
            "details": details,
            "speculation": parse_acceptance(log_delta),
            "resource_after": memory_state(),
        }

    def run_candidate(self, phase: str, candidate: dict[str, Any], repeats: int) -> None:
        completed = self.completed()
        workloads = workload_names(phase)
        pending = [
            (workload, repeat, f"{phase}:{candidate['id']}:{workload}:{repeat}")
            for repeat in range(1, repeats + 1)
            for workload in workloads
            if f"{phase}:{candidate['id']}:{workload}:{repeat}" not in completed
        ]
        if not pending:
            return
        baseline = self.preflight()
        server: Server | None = None
        try:
            server = self.start_candidate(candidate)
            props = request_json(f"http://127.0.0.1:{self.config['runtime']['port']}/props")
            postload = memory_state()
            model_size_mib = (ROOT / "models" / candidate["model"]).stat().st_size / 1048576
            residency_ratio = (
                (float(postload["vram_used_mib"]) - float(baseline["vram_used_mib"])) / model_size_mib
                if postload["vram_used_mib"] is not None and baseline["vram_used_mib"] is not None
                else None
            )
            if residency_ratio is None or residency_ratio < 0.9:
                raise RuntimeError(f"model GPU residency gate failed: ratio={residency_ratio}")
            launch = {
                "argv": build_command(self.config, candidate, server.log_path),
                "props": props,
                "startup_seconds": round(time.monotonic() - server.started_at, 4),
                "resource_baseline": baseline,
                "resource_postload": postload,
                "model_vram_residency_ratio": round(residency_ratio, 4),
                "server_log": str(server.log_path),
            }
            for workload, repeat, trial_id in pending:
                base = {
                    "schema_version": SCHEMA_VERSION,
                    "trial_id": trial_id,
                    "phase": phase,
                    "candidate_id": candidate["id"],
                    "model_id": candidate["model_id"],
                    "candidate": candidate,
                    "workload": workload,
                    "repeat": repeat,
                    "launch": launch,
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
                try:
                    result = self.run_request(candidate, workload, repeat, server)
                    self.append({**base, "status": "ok", **result})
                except GpuSafetyError:
                    raise
                except Exception as exc:  # evidence must survive individual request failures
                    self.append({**base, "status": "error", "passed": False, "error": str(exc)})
                    if server.process.poll() is not None:
                        break
        except GpuSafetyError as exc:
            self.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "trial_id": f"{phase}:{candidate['id']}:safety:{int(time.time())}",
                    "phase": phase,
                    "candidate_id": candidate["id"],
                    "model_id": candidate["model_id"],
                    "candidate": candidate,
                    "workload": "safety",
                    "repeat": 0,
                    "status": "error",
                    "passed": False,
                    "error": str(exc),
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            )
            raise
        except Exception as exc:
            self.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "trial_id": f"{phase}:{candidate['id']}:startup:{int(time.time())}",
                    "phase": phase,
                    "candidate_id": candidate["id"],
                    "model_id": candidate["model_id"],
                    "candidate": candidate,
                    "workload": "startup",
                    "repeat": 0,
                    "status": "error",
                    "passed": False,
                    "error": str(exc),
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            )
        finally:
            if server is not None:
                server.stop()
            self.server = None
            try:
                self.safety.stabilize(f"{candidate['id']}-post-unload-kernel.log")
            finally:
                self.safety.stop_monitor()


def aggregate(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("workload") == "startup":
            continue
        key = f"{row['phase']}:{row['candidate_id']}"
        entry = grouped.setdefault(
            key,
            {"candidate": row["candidate"], "phase": row["phase"], "workloads": {}, "failures": 0},
        )
        if row.get("status") != "ok" or row.get("passed") is not True:
            entry["failures"] += 1
        values = entry["workloads"].setdefault(row["workload"], [])
        values.append(row)
    summaries = []
    for candidate_id_value, entry in grouped.items():
        workload_summary = {}
        for workload, workload_rows in entry["workloads"].items():
            metric_summary = {}
            for metric in ("elapsed_seconds", "prompt_per_second", "predicted_per_second", "cache_n"):
                values = [float(row[metric]) for row in workload_rows if isinstance(row.get(metric), (int, float))]
                metric_summary[metric] = None if not values else round(statistics.median(values), 4)
            specs = [row["speculation"] for row in workload_rows if isinstance(row.get("speculation"), dict)]
            accepted = sum(int(item["accepted"]) for item in specs)
            proposed = sum(int(item["proposed"]) for item in specs)
            workload_summary[workload] = {
                "trials": len(workload_rows),
                "passed": sum(row.get("passed") is True and row.get("status") == "ok" for row in workload_rows),
                **metric_summary,
                "speculation": {
                    "accepted": accepted,
                    "proposed": proposed,
                    "acceptance": None if not proposed else round(accepted / proposed, 4),
                },
            }
        summaries.append(
            {
                "candidate_id": candidate_id_value,
                "candidate": entry["candidate"],
                "phase": entry["phase"],
                "failures": entry["failures"],
                "workloads": workload_summary,
            }
        )
    winners = {}
    for model_id in manifest["models"]:
        winner = best_candidate(rows, model_id)
        winners[model_id] = winner
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "trial_count": len(rows),
        "candidate_summaries": sorted(summaries, key=lambda item: item["candidate_id"]),
        "winners": winners,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = ["# Runtime Tuning V1", "", f"Trials recorded: {summary['trial_count']}", "", "## Selected Candidates", ""]
    for model_id, winner in summary["winners"].items():
        if winner is None:
            lines.append(f"- `{model_id}`: no candidate cleared the selection gate")
        else:
            lines.append(
                f"- `{model_id}`: `{winner['id']}` (`b{winner['batch']}/ub{winner['ubatch']}`, "
                f"`{winner['spec_type']}`, draft `{winner.get('mtp_n', 0)}`)"
            )
    lines.extend(["", "## Candidate Results", ""])
    for item in summary["candidate_summaries"]:
        lines.append(f"### {item['candidate_id']}")
        lines.append(f"Failures: {item['failures']}")
        for workload, values in sorted(item["workloads"].items()):
            lines.append(
                f"- `{workload}`: {values['passed']}/{values['trials']} passed, "
                f"elapsed `{values['elapsed_seconds']}`, PP `{values['prompt_per_second']}`, "
                f"TG `{values['predicted_per_second']}`, acceptance `{values['speculation']['acceptance']}`"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_manifest(
    config: dict[str, Any], selected_phases: list[str], selected_models: list[str] | None = None
) -> dict[str, Any]:
    server_bin = Path(config["runtime"]["server_bin"])
    version_result = subprocess.run([str(server_bin), "--version"], capture_output=True, text=True, check=False)
    version = "\n".join(value for value in (version_result.stdout.strip(), version_result.stderr.strip()) if value)
    models = {}
    for model_id, model in config["models"].items():
        if selected_models and model_id not in selected_models:
            continue
        path = ROOT / "models" / model["model"]
        models[model_id] = {
            **model,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": file_hash(path),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "config": config,
        "config_digest": stable_hash(config),
        "selected_phases": selected_phases,
        "runtime": {"path": str(server_bin), "sha256": file_hash(server_bin), "version": version.strip()},
        "models": models,
        "phase_candidates": {},
        "active_env_sha256": hashlib.sha256(ACTIVE_ENV.read_bytes()).hexdigest() if ACTIVE_ENV.exists() else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sequential, resumable llama.cpp runtime tuning.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument(
        "--phase",
        action="append",
        choices=(
            "main-shape",
            "main-spec",
            "main-context",
            "other-models",
            "validation",
            "validation-controls",
            "all",
        ),
    )
    parser.add_argument("--model", action="append", choices=("qwen27-unsloth", "qwen27-huihui", "qwen35-unsloth", "qwen35-huihui"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidate-limit", type=int)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--seed", type=int, default=73627)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("incompatible tuning config")
    phases = args.phase or ["all"]
    if "all" in phases:
        phases = ["main-shape", "main-spec", "main-context", "other-models", "validation"]
    if args.dry_run:
        rows: list[dict[str, Any]] = []
        for phase in phases:
            candidates = phase_candidates(config, phase, rows)
            if args.model:
                candidates = [candidate for candidate in candidates if candidate["model_id"] in args.model]
            print(
                json.dumps(
                    {"phase": phase, "repeats": config["phases"][phase]["repeats"], "candidates": candidates},
                    indent=2,
                )
            )
        return 0
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (DEFAULT_RESULTS / f"qwen36-tuning-{timestamp}")
    if args.resume and not out_dir.exists():
        raise FileNotFoundError(f"resume directory does not exist: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    if args.resume and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["config_digest"] != stable_hash(config):
            raise ValueError("resume config differs from manifest")
    else:
        manifest = build_manifest(config, phases, args.model)
        json_dump(manifest_path, manifest)
    run = TuningRun(config, out_dir, resume=args.resume, retry_failed=args.retry_failed)
    try:
        run.stop_stack()
        for phase_index, phase in enumerate(phases):
            candidates = phase_candidates(config, phase, run.rows())
            if args.model:
                candidates = [candidate for candidate in candidates if candidate["model_id"] in args.model]
            if args.candidate_limit is not None:
                candidates = candidates[: args.candidate_limit]
            random.Random(args.seed + phase_index).shuffle(candidates)
            manifest["phase_candidates"][phase] = candidates
            json_dump(manifest_path, manifest)
            repeats = args.repeats if args.repeats is not None else int(config["phases"][phase]["repeats"])
            for candidate in candidates:
                run.run_candidate(phase, candidate, repeats)
            summary = aggregate(run.rows(), manifest)
            json_dump(out_dir / "summary.json", summary)
            write_report(out_dir / "REPORT.md", summary)
    finally:
        if run.server is not None:
            run.server.stop()
        try:
            run.restore_stack()
        finally:
            run.safety.close()
    summary = aggregate(run.rows(), manifest)
    json_dump(out_dir / "summary.json", summary)
    write_report(out_dir / "REPORT.md", summary)
    print(out_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"runtime tuning failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
