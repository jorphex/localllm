from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from benchmarks.barrage_v2 import SCHEMA_VERSION


DEFAULT_BASE_URL = "http://127.0.0.1:7347"
DEFAULT_OPENWENDY_ROOT = Path("/home/j/projects/openwendy")


def source_digest(root: Path) -> str:
    try:
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unavailable"
    config = root / "config.toml"
    config_digest = hashlib.sha256(config.read_bytes()).hexdigest() if config.exists() else "absent"
    driver_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps({"commit": commit, "config": config_digest, "driver": driver_digest}, sort_keys=True).encode()).hexdigest()


def harness_metadata(root: Path) -> dict[str, str]:
    return {"id": "openwendy-core-api", "digest": source_digest(root)}


def _event_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_event_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_event_text(item) for item in value)
    return ""


def evaluate_task(task: dict[str, Any], snapshot: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    expect = task.get("expect", {})
    terminal_type = snapshot.get("terminal_type")
    text = _event_text(events).lower()
    required_text = str(expect.get("text", "")).lower()
    required_tool = str(expect.get("tool", "")).lower()
    return {
        "task_id": task["id"],
        "passed": terminal_type == "run_completed" and (not required_text or required_text in text) and (not required_tool or required_tool in text),
        "terminal_type": terminal_type,
        "event_count": len(events),
        "required_text_found": not required_text or required_text in text,
        "required_tool_found": not required_tool or required_tool in text,
    }


def run_openwendy_task(client: httpx.Client, base_url: str, task: dict[str, Any], model_id: str, timeout: float) -> dict[str, Any]:
    conversation_id: str | None = None
    run_id: str | None = None
    try:
        created_response = client.post(f"{base_url}/api/conversations", json={"title": f"barrage-v2-{task['id']}", "source": "benchmark"})
        created_response.raise_for_status()
        created = created_response.json()
        conversation_id = str(created["conversation"]["conversation_id"])
        client.patch(f"{base_url}/api/conversations/{conversation_id}/model", json={"model_id": model_id}).raise_for_status()
        started = client.post(
            f"{base_url}/api/conversations/{conversation_id}/messages",
            json={"text": task["text"], "client_message_id": f"barrage-v2-{task['id']}"},
        )
        started.raise_for_status()
        run_id = started.json()["run_id"]
        deadline = time.monotonic() + timeout
        snapshot: dict[str, Any] = {}
        while time.monotonic() < deadline:
            snapshot_response = client.get(f"{base_url}/api/runs/{run_id}/snapshot")
            snapshot_response.raise_for_status()
            snapshot = snapshot_response.json()["snapshot"]
            if snapshot.get("terminal"):
                break
            time.sleep(0.5)
        if not snapshot.get("terminal"):
            raise TimeoutError(f"OpenWendy run did not finish within {timeout} seconds")
        events_response = client.get(f"{base_url}/api/runs/{run_id}/events")
        events_response.raise_for_status()
        result = evaluate_task(task, snapshot, events_response.json().get("events", []))
        result["run_id"] = run_id
        return result
    finally:
        if conversation_id:
            if run_id:
                client.post(f"{base_url}/api/conversations/{conversation_id}/run/cancel")
            try:
                client.delete(f"{base_url}/api/conversations/{conversation_id}").raise_for_status()
            except httpx.HTTPError:
                pass


def run_request(request: dict[str, Any], *, base_url: str, model_id: str, timeout: float, root: Path) -> dict[str, Any]:
    if request.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("incompatible barrage schema")
    if request.get("harness") != harness_metadata(root):
        raise ValueError("OpenWendy harness digest does not match the active source/configuration")
    with httpx.Client(timeout=timeout) as client:
        client.get(f"{base_url}/api/health/details").raise_for_status()
        results = [run_openwendy_task(client, base_url, task, model_id, timeout) for task in request["tasks"]]
    return {"schema_version": SCHEMA_VERSION, "profile": request["profile"], "harness": request["harness"], "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark an explicitly selected OpenWendy core-API model profile.")
    parser.add_argument("--metadata", action="store_true")
    parser.add_argument("--openwendy-root", type=Path, default=Path(os.environ.get("OPENWENDY_ROOT", DEFAULT_OPENWENDY_ROOT)))
    parser.add_argument("--base-url", default=os.environ.get("OPENWENDY_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model-id", default=os.environ.get("OPENWENDY_BARRAGE_MODEL_ID"))
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if args.metadata:
        print(json.dumps(harness_metadata(args.openwendy_root), sort_keys=True))
        return
    if not args.model_id:
        raise SystemExit("Set --model-id or OPENWENDY_BARRAGE_MODEL_ID.")
    request = json.load(__import__("sys").stdin)
    print(json.dumps(run_request(request, base_url=args.base_url.rstrip("/"), model_id=args.model_id, timeout=args.timeout, root=args.openwendy_root), sort_keys=True))


if __name__ == "__main__":
    main()
