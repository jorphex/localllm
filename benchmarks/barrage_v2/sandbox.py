from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx


TASKS = (
    {
        "id": "normalize_tags",
        "split": "core",
        "prompt": "Fix solution.py so normalize_tags strips whitespace, removes blank values, lowercases tags, and preserves order.",
        "source": "def normalize_tags(tags):\n    return [tag.lower() for tag in tags]\n",
        "public_test": "from solution import normalize_tags\nassert normalize_tags([' A ', '', 'B']) == ['a', 'b']\nprint('OK')\n",
        "acceptance": "from solution import normalize_tags\nassert normalize_tags([]) == []\nassert normalize_tags(['  ', 'X', ' x ']) == ['x', 'x']\nprint('OK')\n",
    },
    {
        "id": "merge_intervals",
        "split": "core",
        "prompt": "Fix solution.py so merge_intervals sorts ranges and merges overlapping or touching integer intervals.",
        "source": "def merge_intervals(intervals):\n    return intervals\n",
        "public_test": "from solution import merge_intervals\nassert merge_intervals([[1, 3], [2, 6]]) == [[1, 6]]\nprint('OK')\n",
        "acceptance": "from solution import merge_intervals\nassert merge_intervals([]) == []\nassert merge_intervals([[8, 10], [1, 4], [4, 5]]) == [[1, 5], [8, 10]]\nprint('OK')\n",
    },
    {
        "id": "retry_limit",
        "split": "core",
        "prompt": "Fix solution.py so call_with_retry retries a failing zero-argument function exactly retries times after the initial call, then raises the final exception.",
        "source": "def call_with_retry(fn, retries=2):\n    for _ in range(retries):\n        try:\n            return fn()\n        except Exception:\n            pass\n",
        "public_test": "from solution import call_with_retry\nassert call_with_retry(lambda: 7) == 7\nprint('OK')\n",
        "acceptance": "from solution import call_with_retry\ncount = {'value': 0}\ndef flaky():\n    count['value'] += 1\n    if count['value'] < 3:\n        raise ValueError('no')\n    return 9\nassert call_with_retry(flaky, retries=2) == 9\nassert count['value'] == 3\ntry:\n    call_with_retry(lambda: (_ for _ in ()).throw(RuntimeError('x')), retries=1)\nexcept RuntimeError:\n    pass\nelse:\n    raise AssertionError('missing final exception')\nprint('OK')\n",
    },
    {
        "id": "pricing_repository",
        "split": "core",
        "prompt": "Inspect the repository and fix its discount normalization and final-price calculation. Do not change tests.py.",
        "files": {
            "discounts.py": "def normalize_discount(value):\n    return value\n",
            "pricing.py": "from discounts import normalize_discount\n\ndef final_price(price, discount):\n    return price - normalize_discount(discount)\n",
        },
        "public_test": "from pricing import final_price\nassert final_price(100, 0.2) == 80.0\nprint('OK')\n",
        "acceptance": "from discounts import normalize_discount\nfrom pricing import final_price\nassert normalize_discount(-1) == 0\nassert normalize_discount(2) == 1\nassert final_price(19.99, 0) == 19.99\nassert final_price(19.99, 1) == 0.0\nassert final_price(25, 0.15) == 21.25\nprint('OK')\n",
        "expected_changed_files": ["discounts.py", "pricing.py"],
    },
    {
        "id": "transient_test_recovery",
        "split": "core",
        "prompt": "Find and fix the boolean parser. The test runner may fail transiently once; recover and rerun it before stopping.",
        "files": {
            "parser.py": "def parse_bool(value):\n    return bool(value)\n",
            "README.txt": "parse_bool accepts booleans and case-insensitive true/false strings. Invalid values raise ValueError.\n",
        },
        "public_test": "from parser import parse_bool\nassert parse_bool(True) is True\nassert parse_bool('false') is False\nprint('OK')\n",
        "acceptance": "from parser import parse_bool\nassert parse_bool(' TRUE ') is True\nassert parse_bool('False') is False\nfor value in ('yes', 1, None):\n    try:\n        parse_bool(value)\n    except ValueError:\n        pass\n    else:\n        raise AssertionError(f'accepted {value!r}')\nprint('OK')\n",
        "expected_changed_files": ["parser.py"],
        "inject_first_test_failure": True,
        "required_test_attempts": 2,
    },
    {
        "id": "duration_format",
        "split": "holdout",
        "prompt": "Fix solution.py so format_duration renders non-negative seconds as compact h/m/s text without zero-valued leading units.",
        "source": "def format_duration(seconds):\n    return str(seconds)\n",
        "public_test": "from solution import format_duration\nassert format_duration(65) == '1m 5s'\nassert format_duration(3600) == '1h 0m 0s'\nprint('OK')\n",
        "acceptance": "from solution import format_duration\nassert format_duration(0) == '0s'\nassert format_duration(59) == '59s'\nassert format_duration(3661) == '1h 1m 1s'\nprint('OK')\n",
    },
    {
        "id": "config_overlay",
        "split": "holdout",
        "prompt": "Fix solution.py so resolve_timeout returns a positive explicit timeout when present, otherwise the DEFAULT_TIMEOUT from defaults.py.",
        "files": {
            "solution.py": "from defaults import DEFAULT_TIMEOUT\n\ndef resolve_timeout(config):\n    return config.get('timeout', 0)\n",
            "defaults.py": "DEFAULT_TIMEOUT = 30\n",
        },
        "public_test": "from solution import resolve_timeout\nassert resolve_timeout({'timeout': 15}) == 15\nassert resolve_timeout({}) == 30\nprint('OK')\n",
        "acceptance": "from solution import resolve_timeout\nassert resolve_timeout({'timeout': 0}) == 30\nassert resolve_timeout({'timeout': -1}) == 30\nassert resolve_timeout({'timeout': 90}) == 90\nprint('OK')\n",
    },
    {
        "id": "package_summary",
        "split": "holdout",
        "prompt": "Inspect the package and fix summarize_user without changing its public API or unrelated files.",
        "files": {
            "account/__init__.py": "from .summary import summarize_user\n",
            "account/formatting.py": "def display_name(name):\n    return name.strip().title()\n",
            "account/summary.py": "from .formatting import display_name\n\ndef summarize_user(record):\n    return record['name']\n",
        },
        "public_test": "from account import summarize_user\nassert summarize_user({'name': ' ada ', 'active': True}) == 'Ada (active)'\nprint('OK')\n",
        "acceptance": "from account import summarize_user\nassert summarize_user({'name': 'grace hopper', 'active': False}) == 'Grace Hopper (inactive)'\nassert summarize_user({'name': ' LINUS ', 'active': True}) == 'Linus (active)'\nprint('OK')\n",
        "expected_changed_files": ["account/summary.py"],
    },
)


SYSTEM_PROMPT = "You are a coding agent. Use tools to inspect, edit, and verify. Keep the change narrow."


def tools() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": "list_files", "parameters": {"type": "object"}}},
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_tests",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
            },
        },
    ]


def _path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    if root.resolve() not in (candidate, *candidate.parents):
        raise ValueError("path escapes workspace")
    return candidate


def execute_tool(root: Path, name: str, arguments: dict[str, Any]) -> str:
    try:
        if name == "list_files":
            return "\n".join(str(path.relative_to(root)) for path in sorted(root.rglob("*")) if path.is_file())
        if name == "read_file":
            return _path(root, arguments["path"]).read_text(encoding="utf-8")
        if name == "write_file":
            path = _path(root, arguments["path"])
            path.write_text(arguments["content"], encoding="utf-8")
            return f"wrote {path.relative_to(root)}"
        if name == "run_tests":
            if arguments.get("command") != "python3 tests.py":
                raise ValueError("only 'python3 tests.py' is allowed")
            result = subprocess.run(["python3", "tests.py"], cwd=root, capture_output=True, text=True, timeout=30)
            return json.dumps({"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        raise ValueError("unknown tool")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc.__class__.__name__}: {exc}"


def selected_tasks(include_holdout: bool) -> tuple[dict[str, Any], ...]:
    return tuple(task for task in TASKS if include_holdout or task.get("split", "core") == "core")


def run_task(
    client: httpx.Client,
    base_url: str,
    model: str,
    task: dict[str, Any],
    max_turns: int,
    timeout: float,
    *,
    trial: int = 1,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="localllm-barrage-") as tempdir:
        root = Path(tempdir)
        files = task.get("files") or {"solution.py": task["source"]}
        for relative_path, content in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (root / "tests.py").write_text(task["public_test"], encoding="utf-8")
        initial_files = {
            str(path.relative_to(root)): path.read_text(encoding="utf-8")
            for path in root.rglob("*")
            if path.is_file()
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task["prompt"] + " Run python3 tests.py before stopping."},
        ]
        transcript: list[dict[str, Any]] = []
        tool_errors = 0
        test_attempts = 0
        verification_attempted = False
        verification_passed = False
        started = time.perf_counter()
        failure: dict[str, Any] | None = None
        for turn in range(1, max_turns + 1):
            payload = {
                "model": model,
                "messages": messages,
                "tools": tools(),
                "tool_choice": "auto",
                "temperature": 0.2,
                "seed": 42 + trial,
                "top_p": 0.95,
                "top_k": 20,
                "repeat_penalty": 1.05,
                "max_tokens": max_tokens,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            try:
                response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                response.raise_for_status()
                body = response.json()
                message = body["choices"][0]["message"]
            except Exception as exc:  # noqa: BLE001
                failure = {
                    "status": "error",
                    "phase": "model_request",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "request": payload,
                }
                break
            transcript.append({"turn": turn, "request": payload, "response": body})
            messages.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                break
            for call in calls:
                try:
                    arguments = json.loads(call["function"]["arguments"])
                    tool_name = call["function"]["name"]
                    if tool_name == "run_tests":
                        test_attempts += 1
                    if tool_name == "run_tests" and task.get("inject_first_test_failure") and test_attempts == 1:
                        output = "ERROR: TransientRunnerError: test worker unavailable; retry the exact command"
                    else:
                        output = execute_tool(root, tool_name, arguments)
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    output = f"ERROR: {exc.__class__.__name__}: {exc}"
                if output.startswith("ERROR:"):
                    tool_errors += 1
                if call["function"]["name"] == "run_tests":
                    verification_attempted = True
                    try:
                        verification_passed = json.loads(output).get("returncode") == 0
                    except json.JSONDecodeError:
                        verification_passed = False
                messages.append({"role": "tool", "tool_call_id": call.get("id", "call"), "content": output})
        acceptance = root / "acceptance.py"
        acceptance_stdout = ""
        acceptance_stderr = ""
        acceptance_passed = False
        try:
            acceptance.write_text(task["acceptance"], encoding="utf-8")
            verified = subprocess.run(["python3", "acceptance.py"], cwd=root, capture_output=True, text=True, timeout=30)
            acceptance_stdout = verified.stdout
            acceptance_stderr = verified.stderr
            acceptance_passed = verified.returncode == 0
        except Exception as exc:  # noqa: BLE001
            if failure is None:
                failure = {
                    "status": "error",
                    "phase": "acceptance",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
        changed_files = sorted(
            relative
            for path in root.rglob("*")
            if path.is_file()
            if (relative := str(path.relative_to(root))) != "acceptance.py"
            and "__pycache__" not in path.parts
            and (relative not in initial_files or path.read_text(encoding="utf-8") != initial_files[relative])
        )
        expected_changed_files = sorted(task.get("expected_changed_files", ["solution.py"]))
        scope_clean = changed_files == expected_changed_files
        required_test_attempts = int(task.get("required_test_attempts", 1))
        recovery_completed = test_attempts >= required_test_attempts
        timing_rows = [entry["response"].get("timings", {}) for entry in transcript]
        result = {
            "task": task["id"],
            "split": task.get("split", "core"),
            "trial": trial,
            "passed": acceptance_passed and scope_clean and verification_passed and recovery_completed,
            "turns": len(transcript),
            "tool_error_count": tool_errors,
            "verification_attempted": verification_attempted,
            "verification_passed": verification_passed,
            "test_attempts": test_attempts,
            "required_test_attempts": required_test_attempts,
            "recovery_completed": recovery_completed,
            "changed_files": changed_files,
            "expected_changed_files": expected_changed_files,
            "scope_clean": scope_clean,
            "turn_budget_fraction": round(len(transcript) / max_turns, 4),
            "elapsed_seconds": round(time.perf_counter() - started, 4),
            "acceptance_stdout": acceptance_stdout,
            "acceptance_stderr": acceptance_stderr,
            "transcript": transcript,
            "agent_metrics": {
                "request_count": len(transcript),
                "prompt_n": sum(int(timing.get("prompt_n") or 0) for timing in timing_rows),
                "predicted_n": sum(int(timing.get("predicted_n") or 0) for timing in timing_rows),
            },
        }
        if failure is not None:
            result.update(failure)
        return result
