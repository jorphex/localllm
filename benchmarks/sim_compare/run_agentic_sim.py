from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from benchmarks.result_summaries import SCHEMA_VERSION, stable_digest

try:
    from .scenarios import SCENARIOS
except ImportError:  # pragma: no cover - script entrypoint fallback
    from scenarios import SCENARIOS


MAX_TURNS = 12
SYSTEM_PROMPT = (
    "You are Codex, a coding agent operating in a disposable benchmark repo. "
    "Workflow: inspect -> patch -> verify -> stop. Prefer the next real action "
    "over narration. Use only the provided tools. Keep scope narrow."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--fixture-root", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def scenario_max_turns(scenario: dict) -> int:
    return int(scenario.get("max_turns", MAX_TURNS))


def scenario_family(scenario_name: str) -> str:
    if scenario_name in {"retry_bugfix", "queue_bugfix", "tool_error_recovery", "command_denial_recovery"}:
        return "coding_core"
    if scenario_name in {"retry_review_feedback", "batch_tail_recovery"}:
        return "coding_recovery"
    if scenario_name in {"flush_report_two_file_fix", "session_store_exploration"}:
        return "coding_scope"
    return "coding_misc"


def ensure_within_workspace(workspace: Path, raw_path: str) -> Path:
    candidate = (workspace / raw_path).resolve()
    workspace_resolved = workspace.resolve()
    if workspace_resolved not in (candidate, *candidate.parents):
        raise ValueError(f"path escapes workspace: {raw_path}")
    if not candidate.exists():
        raise FileNotFoundError(raw_path)
    return candidate


def resolve_write_path(workspace: Path, raw_path: str) -> Path:
    candidate = (workspace / raw_path).resolve()
    workspace_resolved = workspace.resolve()
    if workspace_resolved not in (candidate, *candidate.parents):
        raise ValueError(f"path escapes workspace: {raw_path}")
    return candidate


def list_files(workspace: Path, relative: str = ".") -> str:
    root = ensure_within_workspace(workspace, relative)
    if not root.is_dir():
        raise NotADirectoryError(relative)
    paths = [
        str(path.relative_to(workspace))
        for path in sorted(root.rglob("*"))
        if "__pycache__" not in path.parts
    ]
    return "\n".join(paths[:200])


def search_files(workspace: Path, pattern: str) -> str:
    result = subprocess.run(
        ["rg", "-n", pattern, str(workspace)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "search failed")
    return result.stdout.strip()


def read_file(workspace: Path, relative: str) -> str:
    path = ensure_within_workspace(workspace, relative)
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path.read_text(encoding="utf-8")


def write_file(workspace: Path, relative: str, content: str) -> str:
    path = resolve_write_path(workspace, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.relative_to(workspace)} ({len(content)} bytes)"


def normalize_test_command(command: str) -> list[str]:
    argv = shlex.split(command)
    if not argv:
        raise ValueError("empty test command")

    if argv[0] == "python":
        argv[0] = "python3"

    if argv[:3] in (["python3", "-m", "unittest"], ["python3", "-m", "pytest"]):
        runner = argv[:3]
        test_args = argv[3:]
    elif argv[0] == "pytest":
        runner = ["pytest"]
        test_args = argv[1:]
    else:
        raise ValueError(f"command not allowed: {command}")

    allowed_flags = {"-q", "-v"}
    for arg in test_args:
        if arg in allowed_flags:
            continue
        if arg.startswith("tests.") or arg.startswith("tests/"):
            continue
        raise ValueError(f"test argument not allowed: {arg}")

    return runner + test_args


def run_tests(workspace: Path, command: str) -> str:
    argv = normalize_test_command(command)
    result = subprocess.run(
        argv,
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    return json.dumps(payload)


def test_targets(argv: list[str]) -> list[str]:
    return sorted(arg for arg in argv if not arg.startswith("-"))


def current_changed_files(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = []
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            path = line[3:]
            if "__pycache__" in path:
                continue
            changed.append(path)
    return changed


def build_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files under a workspace path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "Search file contents with ripgrep.",
                "parameters": {
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Replace a workspace file with full content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": "Run one of the allowed test commands for this scenario.",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        },
    ]


def execute_tool(
    workspace: Path,
    scenario: dict,
    tool_name: str,
    arguments: dict,
) -> str:
    try:
        if tool_name == "list_files":
            return list_files(workspace, arguments.get("path", "."))
        if tool_name == "search_files":
            return search_files(workspace, arguments["pattern"])
        if tool_name == "read_file":
            return read_file(workspace, arguments["path"])
        if tool_name == "write_file":
            return write_file(workspace, arguments["path"], arguments["content"])
        if tool_name == "run_tests":
            return run_tests(workspace, arguments["command"])
        raise ValueError(f"unknown tool: {tool_name}")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc.__class__.__name__}: {exc}"


def should_fire_follow_up(
    follow_up: dict,
    event_counts: dict[str, int],
    tool_name: str,
    tool_result: dict | None = None,
) -> bool:
    trigger = follow_up["trigger"]
    if trigger.get("tool_name") != tool_name:
        return False
    if event_counts.get(tool_name, 0) < trigger.get("count", 1):
        return False
    if trigger.get("returncode_nonzero"):
        return bool(tool_result and tool_result.get("returncode", 0) != 0)
    if "returncode" in trigger:
        return bool(tool_result) and tool_result.get("returncode") == trigger["returncode"]
    return True


def chat_once(client: httpx.Client, base_url: str, payload: dict) -> tuple[dict, float]:
    started = time.perf_counter()
    response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=300.0)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


def verify_scenario(workspace: Path, scenario: dict) -> dict:
    normalized_verify = normalize_test_command(scenario["verify_command"])
    result = subprocess.run(
        normalized_verify,
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    changed_files = current_changed_files(workspace)
    return {
        "verify_command": scenario["verify_command"],
        "normalized_verify_command": normalized_verify,
        "verify_returncode": result.returncode,
        "verify_stdout": result.stdout,
        "verify_stderr": result.stderr,
        "changed_files": changed_files,
        "expected_modified_files": scenario["expected_modified_files"],
        "expected_files_only": sorted(changed_files) == sorted(scenario["expected_modified_files"]),
    }


def summarize_result(
    scenario_name: str,
    scenario: dict,
    transcript: list[dict],
    verification: dict,
    total_elapsed: float,
    tool_error_count: int,
) -> dict:
    solved = verification["verify_returncode"] == 0
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario": scenario_name,
        "scenario_family": scenario_family(scenario_name),
        "scenario_digest": stable_digest(
            {
                "title": scenario["title"],
                "prompt": scenario["prompt"],
                "verify_command": scenario["verify_command"],
                "expected_modified_files": scenario["expected_modified_files"],
                "follow_ups": scenario.get("follow_ups", []),
                "max_turns": scenario.get("max_turns"),
            }
        ),
        "title": scenario["title"],
        "model": None,
        "total_elapsed_seconds": total_elapsed,
        "turns": len(transcript),
        "verify_returncode": verification["verify_returncode"],
        "normalized_verify_command": verification["normalized_verify_command"],
        "changed_files": verification["changed_files"],
        "expected_files_only": verification["expected_files_only"],
        "tool_error_count": tool_error_count,
        "solved": solved,
        "tool_counts": tool_counts(transcript),
        "scorecard": {
            "pass": solved,
            "scope_clean": verification["expected_files_only"],
            "tool_error_free": tool_error_count == 0,
        },
    }


def init_workspace(fixture_root: Path) -> Path:
    tempdir = Path(tempfile.mkdtemp(prefix="localllm-sim-"))
    workspace = tempdir / "repo"
    shutil.copytree(fixture_root, workspace)
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Sim", "-c", "user.email=sim@example.com", "commit", "-m", "fixture"],
        cwd=workspace,
        check=True,
        capture_output=True,
    )
    return workspace


def tool_counts(transcript: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for turn in transcript:
        message = turn.get("response", {}).get("choices", [{}])[0].get("message", {})
        for tool_call in message.get("tool_calls") or []:
            tool_name = tool_call["function"]["name"]
            counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts


def main() -> None:
    args = parse_args()
    scenario = SCENARIOS[args.scenario]
    fixture_root = Path(args.fixture_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    workspace = init_workspace(fixture_root)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{scenario['prompt']}\n"
                "The workspace is disposable and starts with failing tests. "
                "Use tools to inspect, patch, and verify. Stop once the targeted "
                "tests pass or you are blocked."
            ),
        },
    ]
    tools = build_tools()
    transcript = []
    total_elapsed = 0.0
    solved = False
    event_counts: dict[str, int] = {}
    fired_follow_ups: set[int] = set()
    tool_error_count = 0

    client = httpx.Client()
    try:
        for turn in range(1, scenario_max_turns(scenario) + 1):
            payload = {
                "model": args.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "stream": False,
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 20,
                "repeat_penalty": 1.05,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            response_json, elapsed = chat_once(client, args.base_url, payload)
            total_elapsed += elapsed
            assistant_message = response_json["choices"][0]["message"]
            transcript.append(
                {
                    "turn": turn,
                    "request": payload,
                    "response": response_json,
                    "elapsed_seconds": elapsed,
                }
            )
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                break

            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                event_counts[tool_name] = event_counts.get(tool_name, 0) + 1
                arguments = json.loads(tool_call["function"]["arguments"])
                tool_output = execute_tool(
                    workspace,
                    scenario,
                    tool_name,
                    arguments,
                )
                if tool_output.startswith("ERROR: "):
                    tool_error_count += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": tool_output,
                    }
                )
                tool_result: dict | None = None
                if tool_name == "run_tests":
                    try:
                        tool_result = json.loads(tool_output)
                    except json.JSONDecodeError:
                        tool_result = None
                    if tool_result is not None:
                        normalized_verify = normalize_test_command(scenario["verify_command"])
                        normalized_seen = normalize_test_command(tool_result["command"])
                        if (
                            tool_result["returncode"] == 0
                            and test_targets(normalized_seen) == test_targets(normalized_verify)
                        ):
                            solved = True
                for index, follow_up in enumerate(scenario.get("follow_ups", [])):
                    if index in fired_follow_ups:
                        continue
                    if should_fire_follow_up(follow_up, event_counts, tool_name, tool_result):
                        messages.append({"role": "user", "content": follow_up["message"]})
                        fired_follow_ups.add(index)
            if solved:
                break
    finally:
        client.close()

    verification = verify_scenario(workspace, scenario)
    result = {
        "schema_version": SCHEMA_VERSION,
        "scenario": args.scenario,
        "scenario_family": scenario_family(args.scenario),
        "title": scenario["title"],
        "model": args.model,
        "scenario_digest": stable_digest(
            {
                "title": scenario["title"],
                "prompt": scenario["prompt"],
                "verify_command": scenario["verify_command"],
                "expected_modified_files": scenario["expected_modified_files"],
                "follow_ups": scenario.get("follow_ups", []),
                "max_turns": scenario.get("max_turns"),
            }
        ),
        "workspace": str(workspace),
        "total_elapsed_seconds": total_elapsed,
        "turns": len(transcript),
        "tool_error_count": tool_error_count,
        "tool_counts": tool_counts(transcript),
        "solved_during_run": solved,
        "transcript": transcript,
        "verification": verification,
    }
    summary = summarize_result(args.scenario, scenario, transcript, verification, total_elapsed, tool_error_count)
    summary["model"] = args.model
    (out_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
