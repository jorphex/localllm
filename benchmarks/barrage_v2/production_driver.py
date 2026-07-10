from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from benchmarks.barrage_v2 import SCHEMA_VERSION
from benchmarks.barrage_v2.artifacts import write_json


def run_driver(command: str, request: dict[str, Any], timeout: int) -> dict[str, Any]:
    if request.get("profile", {}).get("class") != "production":
        raise ValueError("production driver requires a production profile")
    harness = request.get("harness")
    if not isinstance(harness, dict) or not harness.get("id") or not harness.get("digest"):
        raise ValueError("production driver requires a versioned harness id and digest")
    result = subprocess.run(
        shlex.split(command),
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"driver exited {result.returncode}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("driver output must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("driver returned an incompatible schema version")
    if payload.get("profile") != request["profile"]:
        raise ValueError("driver returned a different production profile")
    if payload.get("harness") != harness:
        raise ValueError("driver returned a different harness identity")
    requested_tasks = request.get("tasks", [])
    if not isinstance(requested_tasks, list):
        raise ValueError("production request tasks must be a list")
    requested_ids = [task.get("id") for task in requested_tasks if isinstance(task, dict)]
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise ValueError("driver results must be a list")
    result_ids = [result.get("task_id") for result in results if isinstance(result, dict)]
    if (
        not requested_ids
        or len(requested_ids) != len(requested_tasks)
        or any(not isinstance(task_id, str) or not task_id for task_id in requested_ids)
        or len(set(requested_ids)) != len(requested_ids)
    ):
        raise ValueError("production request must contain identified tasks")
    if len(result_ids) != len(results) or sorted(result_ids) != sorted(requested_ids):
        raise ValueError("driver results must cover every requested task exactly once")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    write_json(args.out, run_driver(args.driver, request, args.timeout))


if __name__ == "__main__":
    main()
