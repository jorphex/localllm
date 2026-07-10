from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path
from statistics import median
from typing import Any


def stable_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_output(command: list[str], *, include_stderr: bool = False) -> str | None:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or (result.stderr.strip() if include_stderr else None)


def server_version(server_bin: Path) -> str | None:
    output = command_output([str(server_bin), "--version"], include_stderr=True)
    if not output:
        return None
    version_lines = [line for line in output.splitlines() if line.startswith(("version:", "built with"))]
    return "\n".join(version_lines) or output


def gpu_metadata() -> dict[str, str]:
    nvidia = command_output(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    if nvidia:
        name, _, driver = nvidia.partition(",")
        return {"backend": "nvidia", "name": name.strip(), "driver": driver.strip()}
    rocm = command_output(["rocm-smi", "--showdriverversion"])
    if rocm:
        return {"backend": "rocm", "driver": rocm}
    return {"backend": "unknown"}


def environment_metadata(server_bin: Path | None, model_path: Path | None) -> dict[str, Any]:
    model: dict[str, Any] | None = None
    if model_path is not None:
        stat = model_path.stat()
        model = {"path": str(model_path), "size_bytes": stat.st_size, "sha256": file_sha256(model_path)}
    return {
        "platform": platform.platform(),
        "runtime_backend": os.environ.get("LOCALLLM_RUNTIME_BACKEND", "unknown"),
        "gpu": gpu_metadata(),
        "server_version": server_version(server_bin) if server_bin else None,
        "model": model,
    }


def distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(values),
        "median": round(float(median(values)), 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
    }


def aggregate_trials(records: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    metric_names = (
        "prompt_per_second",
        "predicted_per_second",
        "elapsed_seconds",
        "ttft_seconds",
        "cache_n",
        "agent_predicted_per_second",
        "agent_prompt_n",
        "agent_predicted_n",
        "agent_request_count",
    )
    workloads = sorted({str(row["workload"]) for row in records})
    return {
        workload: {
            metric: distribution(
                [float(row[metric]) for row in records if row["workload"] == workload and isinstance(row.get(metric), (int, float))]
            )
            for metric in metric_names
        }
        for workload in workloads
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
