from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
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


def _tool_event_matches(event: dict[str, Any], expected: dict[str, Any]) -> bool:
    expected_arguments = expected.get("arguments", {})
    if not isinstance(expected_arguments, dict):
        raise ValueError("task tool arguments expectation must be an object")
    expected_output = expected.get("output")
    expected_output_contains = expected.get("output_contains")
    return (
        event["tool_name"] == str(expected.get("name") or "").lower()
        and all(event["arguments"].get(key) == value for key, value in expected_arguments.items())
        and (expected_output is None or event["output"] == expected_output)
        and (expected_output_contains is None or str(expected_output_contains).lower() in event["output"].lower())
    )


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
    required_texts = expect.get("texts", [expect.get("text")] if expect.get("text") is not None else [])
    if not isinstance(required_texts, list):
        raise ValueError("task text expectation must be a string or list")
    required_texts = [str(value).lower() for value in required_texts]
    tool_expectations = expect.get("tools")
    if tool_expectations is None and "tool" in expect:
        tool_expect = expect["tool"]
        tool_expectations = [{"name": tool_expect}] if isinstance(tool_expect, str) else [tool_expect]
    if tool_expectations is not None and (
        not isinstance(tool_expectations, list) or not all(isinstance(item, dict) for item in tool_expectations)
    ):
        raise ValueError("task tools expectation must be a list of objects")
    tool_events = completed_tool_events(events)
    matching_events: list[dict[str, Any]] = []
    tools_ok = True
    if tool_expectations is not None:
        if str(expect.get("tool_order", "exact")) == "any":
            remaining = list(tool_events)
            for expected in tool_expectations:
                match = next((event for event in remaining if _tool_event_matches(event, expected)), None)
                if match is None:
                    tools_ok = False
                    break
                matching_events.append(match)
                remaining.remove(match)
            tools_ok = tools_ok and (bool(expect.get("allow_extra_tools")) or not remaining)
        else:
            tools_ok = len(tool_events) == len(tool_expectations)
            if tools_ok:
                matching_events = [
                    event
                    for event, expected in zip(tool_events, tool_expectations, strict=True)
                    if _tool_event_matches(event, expected)
                ]
                tools_ok = len(matching_events) == len(tool_expectations)
    if expect.get("no_tools"):
        tools_ok = not tool_events
    forbidden_tools = {str(name).lower() for name in expect.get("forbid_tools", [])}
    forbidden_tool_found = any(event["tool_name"] in forbidden_tools for event in tool_events)
    text_ok = all(value in answer_text for value in required_texts)
    nonempty_ok = not expect.get("nonempty_answer") or bool(answer_text.strip())
    return {
        "task_id": task["id"],
        "passed": terminal_type == "run_completed" and text_ok and nonempty_ok and tools_ok and not forbidden_tool_found,
        "terminal_type": terminal_type,
        "event_count": len(events),
        "answer_text": str(snapshot.get("answer_text") or ""),
        "required_text_found": text_ok,
        "required_tool_found": tools_ok,
        "forbidden_tool_found": forbidden_tool_found,
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


def run_concurrent_openwendy_task(
    client: httpx.Client,
    base_url: str,
    task: dict[str, Any],
    model_id: str,
    timeout: float,
) -> dict[str, Any]:
    cases = task.get("cases")
    if not isinstance(cases, list) or len(cases) < 2 or not all(isinstance(case, dict) for case in cases):
        raise ValueError("concurrent OpenWendy task requires at least two cases")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(cases)) as executor:
        results = list(
            executor.map(
                lambda case: run_openwendy_task(client, base_url, case, model_id, timeout),
                cases,
            )
        )
    return {
        "task_id": task["id"],
        "passed": all(result["passed"] for result in results),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "case_count": len(results),
        "cases": results,
    }


def run_cancel_openwendy_task(
    client: httpx.Client,
    base_url: str,
    task: dict[str, Any],
    model_id: str,
    timeout: float,
) -> dict[str, Any]:
    conversation_id: str | None = None
    run_id: str | None = None
    try:
        created = client.post(
            f"{base_url}/api/conversations",
            json={"title": f"barrage-v2-{task['id']}", "source": "benchmark"},
        )
        created.raise_for_status()
        conversation_id = str(created.json()["conversation"]["conversation_id"])
        client.patch(f"{base_url}/api/conversations/{conversation_id}/model", json={"model_id": model_id}).raise_for_status()
        started = client.post(
            f"{base_url}/api/conversations/{conversation_id}/messages",
            json={"text": task["text"], "client_message_id": f"barrage-v2-{task['id']}"},
        )
        started.raise_for_status()
        run_id = str(started.json()["run_id"])
        cancel = client.post(f"{base_url}/api/conversations/{conversation_id}/run/cancel")
        cancel.raise_for_status()
        deadline = time.monotonic() + timeout
        snapshot: dict[str, Any] = {}
        while time.monotonic() < deadline:
            response = client.get(f"{base_url}/api/runs/{run_id}/snapshot")
            response.raise_for_status()
            snapshot = response.json()["snapshot"]
            if snapshot.get("terminal"):
                break
            time.sleep(0.2)
        return {
            "task_id": task["id"],
            "passed": snapshot.get("terminal_type") == "run_cancelled" and snapshot.get("status") == "cancelled",
            "run_id": run_id,
            "cancel_status": cancel.json().get("status"),
            "terminal_type": snapshot.get("terminal_type"),
            "status": snapshot.get("status"),
        }
    finally:
        if conversation_id:
            try:
                client.delete(f"{base_url}/api/conversations/{conversation_id}").raise_for_status()
            except httpx.HTTPError:
                pass


def run_workspace_roundtrip_task(
    client: httpx.Client,
    base_url: str,
    task: dict[str, Any],
    model_id: str,
    timeout: float,
) -> dict[str, Any]:
    benchmark_root = Path.home() / ".openwendy" / "benchmark-workspaces"
    benchmark_root.mkdir(parents=True, exist_ok=True)
    content = "barrage-v2 workspace roundtrip"
    with tempfile.TemporaryDirectory(prefix="roundtrip-", dir=benchmark_root) as tempdir:
        workspace = Path(tempdir)
        probe = workspace / "probe.txt"
        conversation_task = {
            "id": task["id"],
            "text": (
                f"Use workspace_session to bind this conversation to {workspace}. Then use write to create probe.txt "
                f"with exact content '{content}', use read to verify it, and answer exactly WORKSPACE_ROUNDTRIP_OK."
            ),
            "expect": {
                "text": "WORKSPACE_ROUNDTRIP_OK",
                "tools": [
                    {"name": "workspace_session", "arguments": {"operation": "bind_project", "path": str(workspace)}},
                    {"name": "write", "arguments": {"path": "probe.txt", "content": content}},
                    {"name": "read", "arguments": {"path": "probe.txt"}, "output_contains": content},
                ],
            },
        }
        result = run_openwendy_task(client, base_url, conversation_task, model_id, timeout)
        filesystem_ok = probe.is_file() and probe.read_text(encoding="utf-8") == content
        result["workspace_filesystem_ok"] = filesystem_ok
        result["passed"] = result["passed"] and filesystem_ok
        return result


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
        results = []
        for task in request["tasks"]:
            task_started = time.perf_counter()
            kind = str(task.get("kind", "conversation"))
            if kind == "conversation":
                result = run_openwendy_task(client, base_url, task, model_id, timeout)
            elif kind == "concurrent_conversations":
                result = run_concurrent_openwendy_task(client, base_url, task, model_id, timeout)
            elif kind == "cancel_run":
                result = run_cancel_openwendy_task(client, base_url, task, model_id, timeout)
            elif kind == "workspace_roundtrip":
                result = run_workspace_roundtrip_task(client, base_url, task, model_id, timeout)
            else:
                raise ValueError(f"unknown OpenWendy task kind: {kind}")
            result["elapsed_seconds"] = round(time.perf_counter() - task_started, 4)
            results.append(result)
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
