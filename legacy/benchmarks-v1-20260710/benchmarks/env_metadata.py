#!/usr/bin/env python3
"""Capture environment and artifact metadata for benchmark manifests."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from benchmarks.config import load_config
from benchmarks.result_summaries import stable_digest


def llama_server_version(bin_path: Path | str) -> str:
    try:
        result = subprocess.run(
            [str(bin_path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip().splitlines()[0] if result.stdout else "unknown"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def _find_git_root(start: Path) -> Path | None:
    path = start.resolve()
    for _ in range(5):
        if (path / ".git").is_dir():
            return path
        parent = path.parent
        if parent == path:
            break
        path = parent
    return None


def llama_cpp_commit(src_dir: Path | str | None = None, bin_path: Path | str | None = None) -> str:
    if src_dir:
        src = Path(src_dir)
    elif bin_path:
        root = _find_git_root(Path(bin_path).parent)
        src = root if root else Path.home() / ".local" / "src" / "llama.cpp"
    else:
        src = Path.home() / ".local" / "src" / "llama.cpp"
    try:
        result = subprocess.run(
            ["git", "-C", str(src), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def gpu_info() -> dict:
    if subprocess.run(["which", "nvidia-smi"], check=False, capture_output=True).returncode == 0:
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {"backend": "nvidia", "driver": parts[0] if parts else "unknown", "name": parts[1] if len(parts) > 1 else "unknown"}
        except Exception as exc:  # noqa: BLE001
            return {"backend": "nvidia", "driver": f"error: {exc}"}

    if subprocess.run(["which", "rocm-smi"], check=False, capture_output=True).returncode == 0:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showdriverversion"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            line = next((line for line in result.stdout.splitlines() if "Driver version" in line), "")
            driver = line.split(":")[-1].strip() if ":" in line else "unknown"
            return {"backend": "rocm", "driver": driver}
        except Exception as exc:  # noqa: BLE001
            return {"backend": "rocm", "driver": f"error: {exc}"}

    return {"backend": "unknown", "driver": "unknown"}


def model_artifact_info(model_path: Path | str) -> dict:
    path = Path(model_path)
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
        }
    except Exception as exc:  # noqa: BLE001
        return {"path": str(path), "error": str(exc)}


def config_digest() -> str:
    return stable_digest(load_config())


def collect_metadata(llama_server_bin: Path | str, model_path: Path | str | None = None) -> dict:
    return {
        "llama_server_version": llama_server_version(llama_server_bin),
        "llama_cpp_commit": llama_cpp_commit(bin_path=llama_server_bin),
        "gpu": gpu_info(),
        "model": model_artifact_info(model_path) if model_path else None,
        "config_digest": config_digest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llama-server-bin", default=os.environ.get("LLAMA_SERVER_BIN", ""))
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    metadata = collect_metadata(args.llama_server_bin, args.model)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()