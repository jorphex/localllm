from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import math
from pathlib import Path
from statistics import fmean, median, pstdev
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
        return {"count": 0, "median": None, "mean": None, "min": None, "max": None, "p95": None, "stdev": None}
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "count": len(values),
        "median": round(float(median(values)), 4),
        "mean": round(float(fmean(values)), 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
        "p95": round(ordered[p95_index], 4),
        "stdev": round(float(pstdev(values)), 4),
    }


def binary_summary(rows: list[dict[str, Any]], *, field: str = "passed") -> dict[str, float | int]:
    total = len(rows)
    passed = sum(value is True for value in (row.get(field) for row in rows))
    errors = sum(row.get("status") == "error" for row in rows)
    if total == 0:
        return {
            "passed": 0,
            "total": 0,
            "errors": 0,
            "pass_rate": 0.0,
            "error_rate": 0.0,
            "wilson_low": 0.0,
            "wilson_high": 0.0,
        }
    rate = passed / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return {
        "passed": passed,
        "total": total,
        "errors": errors,
        "pass_rate": round(rate, 4),
        "error_rate": round(errors / total, 4),
        "wilson_low": round(max(0.0, center - margin), 4),
        "wilson_high": round(min(1.0, center + margin), 4),
    }


def grouped_binary_summary(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, float | int]]:
    return {
        value: binary_summary([row for row in rows if str(row.get(key)) == value])
        for value in sorted({str(row.get(key)) for row in rows})
    }


def aggregate_trials(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
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
        | {"reliability": binary_summary([row for row in records if row["workload"] == workload])}
        for workload in workloads
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
