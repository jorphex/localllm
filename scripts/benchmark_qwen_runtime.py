#!/usr/bin/env python3
"""Scratch benchmark runner for localllm Qwen server presets.

Runs one llama-server at a time, checks RAM/VRAM before and after launch, sends
small fixed /completion probes, writes JSONL results, and always stops the
scratch server before returning.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
PRESET_DIR = ROOT / "config" / "presets"
LOG_DIR = ROOT / "logs" / "bench"
RESULT_DIR = ROOT / "benchmarks" / "results"
HOST = "127.0.0.1"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def mem_available_mib() -> int:
    data: dict[str, int] = {}
    for raw in Path("/proc/meminfo").read_text().splitlines():
        key, value = raw.split(":", 1)
        data[key] = int(value.strip().split()[0]) // 1024
    return data.get("MemAvailable", 0)


def swap_free_mib() -> int:
    data: dict[str, int] = {}
    for raw in Path("/proc/meminfo").read_text().splitlines():
        key, value = raw.split(":", 1)
        data[key] = int(value.strip().split()[0]) // 1024
    return data.get("SwapFree", 0)


def vram_used_mib() -> int:
    proc = subprocess.run(
        ["rocm-smi", "--showmeminfo", "vram", "--json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(proc.stdout)
    card = next(iter(payload.values()))
    return int(card["VRAM Total Used Memory (B)"]) // (1024 * 1024)


def ensure_clean_start(args: argparse.Namespace) -> None:
    proc = subprocess.run(
        ["pgrep", "-a", "llama-server"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        raise RuntimeError(f"refusing to launch with existing llama-server:\n{proc.stdout}")
    ram = mem_available_mib()
    swap = swap_free_mib()
    vram = vram_used_mib()
    if ram < args.min_mem_available_mib:
        raise RuntimeError(f"low available RAM before launch: {ram} MiB")
    if swap < args.min_swap_free_mib:
        raise RuntimeError(f"low free swap before launch: {swap} MiB")
    if vram > args.max_baseline_vram_mib:
        raise RuntimeError(f"VRAM baseline too high before launch: {vram} MiB")


def append_cache_args(command: list[str], env: dict[str, str]) -> None:
    cache_prompt = env.get("MAIN_CACHE_PROMPT", "true").lower()
    command.append("--cache-prompt" if cache_prompt in {"1", "true", "yes", "on"} else "--no-cache-prompt")
    command.extend(["--cache-reuse", env.get("MAIN_CACHE_REUSE", "0")])
    command.extend(["--cache-ram", env.get("MAIN_CACHE_RAM", "0")])
    command.extend(["--slot-prompt-similarity", env.get("MAIN_SLOT_PROMPT_SIMILARITY", "0.10")])


def build_command(
    server_bin: Path,
    preset: dict[str, str],
    port: int,
    overrides: dict[str, str],
) -> list[str]:
    env = {**preset, **overrides}
    model = MODEL_DIR / env["MAIN_MODEL"]
    mmproj = MODEL_DIR / env["MAIN_MMPROJ"]
    if not model.is_file():
        raise FileNotFoundError(model)
    if not mmproj.is_file():
        raise FileNotFoundError(mmproj)

    command = [
        str(server_bin),
        "-m",
        str(model),
        "--host",
        HOST,
        "--port",
        str(port),
        "-t",
        env.get("MAIN_THREADS", "10"),
        "-c",
        env["MAIN_CONTEXT"],
        "-mm",
        str(mmproj),
        "--alias",
        env.get("MAIN_ALIAS", "bench"),
    ]

    device = env.get("MAIN_DEVICE") or "Vulkan0"
    if device:
        command.extend(["--device", device])
    gpu_layers = env.get("MAIN_GPU_LAYERS", "auto")
    if gpu_layers:
        command.extend(["--gpu-layers", gpu_layers])
    if env.get("MAIN_FIT", "true").lower() in {"1", "true", "yes", "on"}:
        command.extend(["--fit", "on"])

    append_cache_args(command, env)
    command.extend(shlex.split(env.get("MAIN_EXTRA_ARGS", "")))
    return command


def request_json(method: str, url: str, body: dict | None = None, timeout: int = 180) -> dict:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode())


def wait_for_health(port: int, proc: subprocess.Popen, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://{HOST}:{port}/health"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early with rc={proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
        except OSError:
            time.sleep(1)
    raise TimeoutError("server health timeout")


def prompt_text(kind: str) -> tuple[str, int]:
    if kind == "short":
        return "Reply with exactly: OK", 16
    if kind == "medium":
        line = (
            "Repository note: preserve multimodal support, q8 KV, GPU residency, "
            "and deterministic tool-calling behavior while evaluating speed. "
        )
        prompt = line * 280
        prompt += "\nSummarize the operational constraint in one concise sentence."
        return prompt, 96
    if kind == "long":
        line = (
            "Long context benchmark row: this local agent stack values prefix reuse, "
            "stable scratch servers, q8 KV, and avoiding CPU tensor spill. "
        )
        prompt = line * 1100
        prompt += "\nReturn a compact checklist of three constraints."
        return prompt, 96
    raise ValueError(kind)


def run_probe(port: int, kind: str, ignore_eos: bool) -> dict:
    prompt, n_predict = prompt_text(kind)
    body = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0,
        "cache_prompt": False,
        "ignore_eos": ignore_eos,
        "stream": False,
    }
    started = time.monotonic()
    payload = request_json("POST", f"http://{HOST}:{port}/completion", body, timeout=300)
    elapsed = time.monotonic() - started
    timings = payload.get("timings", {})
    prompt_n = timings.get("prompt_n") or payload.get("prompt_n")
    predicted_n = timings.get("predicted_n") or payload.get("tokens_predicted")
    prompt_ms = timings.get("prompt_ms")
    predicted_ms = timings.get("predicted_ms")
    return {
        "probe": kind,
        "elapsed_s": elapsed,
        "prompt_n": prompt_n,
        "predicted_n": predicted_n,
        "prompt_ms": prompt_ms,
        "predicted_ms": predicted_ms,
        "pp_tps": (prompt_n / (prompt_ms / 1000)) if prompt_n and prompt_ms else None,
        "tg_tps": (predicted_n / (predicted_ms / 1000)) if predicted_n and predicted_ms else None,
        "content_prefix": str(payload.get("content", ""))[:120],
    }


def stop_proc(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=20)


def parse_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"override must be KEY=VALUE: {item}")
        key, value = item.split("=", 1)
        overrides[key] = value
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-bin", type=Path, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--port", type=int, default=18091)
    parser.add_argument("--probe", action="append", default=None)
    parser.add_argument("--ignore-eos", action="store_true")
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--override", action="append", default=[])
    parser.add_argument("--startup-timeout", type=int, default=240)
    parser.add_argument("--max-baseline-vram-mib", type=int, default=1200)
    parser.add_argument("--min-free-vram-after-load-mib", type=int, default=160)
    parser.add_argument("--min-mem-available-mib", type=int, default=18000)
    parser.add_argument("--min-swap-free-mib", type=int, default=1800)
    args = parser.parse_args()
    if args.probe is None:
        args.probe = ["short", "medium", "long"]

    preset_path = PRESET_DIR / f"main-{args.preset}.env"
    if not preset_path.is_file():
        raise FileNotFoundError(preset_path)
    if not args.server_bin.is_file():
        raise FileNotFoundError(args.server_bin)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    overrides = parse_overrides(args.override)
    preset = read_env_file(preset_path)
    command = build_command(args.server_bin, preset, args.port, overrides)
    run_id = f"{int(time.time())}-{args.label}"
    log_path = LOG_DIR / f"{run_id}.log"
    result_path = RESULT_DIR / "qwen-runtime-ab.jsonl"

    ensure_clean_start(args)
    before = {
        "mem_available_mib": mem_available_mib(),
        "swap_free_mib": swap_free_mib(),
        "vram_used_mib": vram_used_mib(),
    }
    proc: subprocess.Popen | None = None
    try:
        with log_path.open("wb") as log:
            proc = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={
                    **os.environ,
                    "LD_LIBRARY_PATH": f"{args.server_bin.parent}:{os.environ.get('LD_LIBRARY_PATH', '')}",
                },
            )
        wait_for_health(args.port, proc, args.startup_timeout)
        after_load = {
            "mem_available_mib": mem_available_mib(),
            "swap_free_mib": swap_free_mib(),
            "vram_used_mib": vram_used_mib(),
        }
        total_vram_mib = 34208743424 // (1024 * 1024)
        free_vram_mib = total_vram_mib - after_load["vram_used_mib"]
        if after_load["mem_available_mib"] < args.min_mem_available_mib:
            raise RuntimeError(f"low available RAM after load: {after_load['mem_available_mib']} MiB")
        if after_load["swap_free_mib"] < args.min_swap_free_mib:
            raise RuntimeError(f"low free swap after load: {after_load['swap_free_mib']} MiB")
        if free_vram_mib < args.min_free_vram_after_load_mib:
            raise RuntimeError(f"low free VRAM after load: {free_vram_mib} MiB")

        probes = []
        if args.hold_seconds > 0:
            print(
                json.dumps(
                    {
                        "label": args.label,
                        "pid": proc.pid,
                        "port": args.port,
                        "after_load": after_load,
                        "log_path": str(log_path),
                        "hold_seconds": args.hold_seconds,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                flush=True,
            )
            time.sleep(args.hold_seconds)
        else:
            probes = [run_probe(args.port, kind, args.ignore_eos) for kind in args.probe]
        record = {
            "label": args.label,
            "preset": args.preset,
            "server_bin": str(args.server_bin),
            "server_version": subprocess.run(
                [str(args.server_bin), "--version"],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ).stdout.strip(),
            "overrides": overrides,
            "before": before,
            "after_load": after_load,
            "after_probes": {
                "mem_available_mib": mem_available_mib(),
                "swap_free_mib": swap_free_mib(),
                "vram_used_mib": vram_used_mib(),
            },
            "log_path": str(log_path),
            "command": command,
            "probes": probes,
        }
        with result_path.open("a") as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    finally:
        stop_proc(proc)
        time.sleep(2)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
