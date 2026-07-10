from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    return hashlib.sha256(
        json.dumps(
            {
                "commit": commit,
                "config": config_digest,
                "driver": driver_digest,
                "working_tree": working_tree_digest(root),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def harness_metadata(root: Path) -> dict[str, str]:
    return {"id": "openwendy-core-api", "digest": source_digest(root)}


def working_tree_digest(root: Path) -> str:
    try:
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--binary", "HEAD"],
            check=True,
            capture_output=True,
        ).stdout
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    digest = hashlib.sha256(diff)
    for raw_path in sorted(path for path in untracked.split(b"\0") if path):
        path = root / os.fsdecode(raw_path)
        if not path.is_file():
            continue
        digest.update(raw_path)
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def completed_tool_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tool_name": str(event.get("tool_name") or "").lower(),
            "arguments": dict(event.get("arguments") or {}) if isinstance(event.get("arguments"), dict) else {},
            "output": str(event.get("output") or ""),
        }
        for event in events
        if str(event.get("type") or "").lower() == "tool_end"
        and str(event.get("state") or "").lower() == "completed"
    ]


def listener_pid(base_url: str) -> int:
    port = urlparse(base_url).port
    if port is None:
        raise ValueError("OpenWendy base URL must include an explicit port")
    try:
        output = subprocess.run(["ss", "-ltnp", f"sport = :{port}"], check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("could not inspect the OpenWendy listener process") from exc
    matches = {int(value) for value in re.findall(r"pid=(\d+)", output)}
    if len(matches) != 1:
        raise ValueError(f"could not identify one OpenWendy listener on port {port}")
    return matches.pop()


def active_source_mtime(root: Path) -> float:
    try:
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("could not inspect the OpenWendy source tree") from exc
    mtimes = [
        path.stat().st_mtime
        for raw_path in [*tracked.split(b"\0"), *untracked.split(b"\0")]
        if raw_path
        for path in [root / os.fsdecode(raw_path)]
        if path.is_file()
    ]
    if not mtimes:
        raise ValueError("could not find OpenWendy source files")
    return max(mtimes)


def process_cwd(pid: int) -> Path:
    return Path(f"/proc/{pid}/cwd").resolve()


def process_started_at(pid: int) -> float:
    try:
        stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(") ", maxsplit=1)[1].split()
        start_ticks = int(stat_fields[19])
        boot_time = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
            if line.startswith("btime ")
        )
        return boot_time + start_ticks / os.sysconf("SC_CLK_TCK")
    except (IndexError, OSError, StopIteration, ValueError) as exc:
        raise ValueError(f"could not determine OpenWendy listener start time for PID {pid}") from exc


def live_service_identity(base_url: str, root: Path) -> dict[str, Any]:
    pid = listener_pid(base_url)
    process_root = process_cwd(pid)
    if process_root != root.resolve():
        raise ValueError(f"OpenWendy listener cwd mismatch: expected {root}, got {process_root}")
    started_at = process_started_at(pid)
    source_mtime = active_source_mtime(root)
    if source_mtime > started_at:
        raise ValueError("OpenWendy listener predates the active source tree; restart it before benchmarking")
    return {
        "pid": pid,
        "process_started_at": round(started_at, 3),
        "source_mtime": round(source_mtime, 3),
    }


def evaluate_task(task: dict[str, Any], snapshot: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    expect = task.get("expect", {})
    terminal_type = snapshot.get("terminal_type")
    answer_text = str(snapshot.get("answer_text") or "").lower()
    required_text = str(expect.get("text", "")).lower()
    tool_expect = expect.get("tool", {})
    tool_expect = {"name": tool_expect} if isinstance(tool_expect, str) else tool_expect
    if not isinstance(tool_expect, dict):
        raise ValueError("task tool expectation must be a string or object")
    required_tool = str(tool_expect.get("name") or "").lower()
    expected_arguments = tool_expect.get("arguments", {})
    if not isinstance(expected_arguments, dict):
        raise ValueError("task tool arguments expectation must be an object")
    expected_output = tool_expect.get("output")
    tool_events = completed_tool_events(events)
    matching_events = [
        event
        for event in tool_events
        if event["tool_name"] == required_tool
        and all(event["arguments"].get(key) == value for key, value in expected_arguments.items())
        and (expected_output is None or event["output"] == expected_output)
    ]
    return {
        "task_id": task["id"],
        "passed": terminal_type == "run_completed" and (not required_text or required_text in answer_text) and (not required_tool or bool(matching_events)),
        "terminal_type": terminal_type,
        "event_count": len(events),
        "answer_text": str(snapshot.get("answer_text") or ""),
        "required_text_found": not required_text or required_text in answer_text,
        "required_tool_found": not required_tool or bool(matching_events),
        "completed_tool_events": tool_events,
        "matching_tool_events": matching_events,
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
        replay = events_response.json()
        final_snapshot = replay.get("snapshot") if isinstance(replay.get("snapshot"), dict) else snapshot
        result = evaluate_task(task, final_snapshot, replay.get("events", []))
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
    candidate = request.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("model") != model_id:
        raise ValueError("OpenWendy candidate alias must match the selected model profile")
    service_identity = live_service_identity(base_url, root)
    with httpx.Client(timeout=timeout) as client:
        client.get(f"{base_url}/api/health/details").raise_for_status()
        results = [run_openwendy_task(client, base_url, task, model_id, timeout) for task in request["tasks"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": request["profile"],
        "harness": request["harness"],
        "driver_metadata": {"adapter": "openwendy-core-api", "model_id": model_id, "service_identity": service_identity},
        "results": results,
    }


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
