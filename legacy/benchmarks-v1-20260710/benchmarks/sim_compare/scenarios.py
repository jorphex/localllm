from __future__ import annotations

SCENARIOS = {
    "retry_bugfix": {
        "title": "Retry helper bugfix",
        "prompt": (
            "You are fixing a regression in a small Python repo inside a disposable "
            "benchmark workspace. Use the available tools instead of narrating long "
            "plans. Goal: make the retry helper behave correctly without broad "
            "refactoring. Keep the patch minimal, prefer editing only "
            "`worker/retry.py`, and verify with the targeted tests before you stop. "
            "When you run tests, prefer `python3 -m unittest ...`."
        ),
        "verify_command": "python3 -m unittest tests.test_retry",
        "expected_modified_files": ["worker/retry.py"],
    },
    "retry_review_feedback": {
        "title": "Retry helper revise after review feedback",
        "prompt": (
            "You are fixing a regression in a small Python repo inside a disposable "
            "benchmark workspace. Use tools to inspect, patch, and verify. The main "
            "goal is still the retry helper bug, but you may receive follow-up review "
            "feedback after your first patch. Do not restart from scratch when that "
            "happens."
        ),
        "verify_command": "python3 -m unittest tests.test_retry",
        "expected_modified_files": ["worker/retry.py"],
        "follow_ups": [
            {
                "trigger": {"tool_name": "write_file", "count": 1},
                "message": (
                    "Review feedback: keep the patch scoped to `worker/retry.py` "
                    "only, do not edit tests, and rerun the smallest targeted retry "
                    "test command before stopping. Revise from the current patch "
                    "state instead of starting over."
                ),
            }
        ],
    },
    "queue_bugfix": {
        "title": "Queue order bugfix",
        "prompt": (
            "You are fixing a queue-order regression in a small Python repo inside a "
            "disposable benchmark workspace. Use tools to inspect the repo, keep the "
            "change tightly scoped, and verify the fix with the smallest useful test "
            "command before stopping. Prefer editing only `worker/queue.py`. When "
            "you run tests, prefer `python3 -m unittest ...`."
        ),
        "verify_command": "python3 -m unittest tests.test_queue",
        "expected_modified_files": ["worker/queue.py"],
    },
    "tool_error_recovery": {
        "title": "Recover after a stale file-path hint",
        "prompt": (
            "You are fixing a retry-helper regression in a small Python repo inside a "
            "disposable benchmark workspace. A stale note from the previous run "
            "claims the helper lives at `worker/retry_helpers.py`, but that hint may "
            "be wrong. Use tools to inspect, recover from bad assumptions quickly, "
            "keep the patch minimal, and verify with the smallest targeted test "
            "command before stopping."
        ),
        "verify_command": "python3 -m unittest tests.test_retry",
        "expected_modified_files": ["worker/retry.py"],
    },
    "command_denial_recovery": {
        "title": "Recover after a denied test command",
        "prompt": (
            "You are fixing a retry-helper regression in a small Python repo inside a "
            "disposable benchmark workspace. A stale runbook suggests trying "
            "`pytest tests/test_retry.py::FetchWithRetryTests::test_raises_last_error_after_final_attempt -q` "
            "first, but the harness may reject unsupported test-command shapes. "
            "Recover cleanly if that happens, keep the patch minimal, and verify with "
            "the smallest allowed targeted test command before stopping."
        ),
        "verify_command": "python3 -m unittest tests.test_retry",
        "expected_modified_files": ["worker/retry.py"],
    },
    "batch_tail_recovery": {
        "title": "Batch helper recovery after a bad first patch",
        "prompt": (
            "You are fixing a batching helper regression in a small Python repo "
            "inside a disposable benchmark workspace. Use tools to inspect, patch, "
            "and verify. Keep the patch tightly scoped to `worker/batches.py`, and "
            "prefer the smallest targeted test command that proves the fix before "
            "you stop."
        ),
        "verify_command": "python3 -m unittest tests.test_batches",
        "expected_modified_files": ["worker/batches.py"],
        "follow_ups": [
            {
                "trigger": {
                    "tool_name": "run_tests",
                    "count": 1,
                    "returncode_nonzero": True,
                },
                "message": (
                    "Review feedback: your first patch still loses the trailing "
                    "partial batch. Revise from the current patch state, keep the "
                    "change in `worker/batches.py` only, and rerun the smallest "
                    "targeted batch test before stopping."
                ),
            }
        ],
    },
    "flush_report_two_file_fix": {
        "title": "Legitimate two-file flush report fix",
        "prompt": (
            "You are fixing a flush-report regression in a small Python repo inside a "
            "disposable benchmark workspace. Both the grouped IDs and the reported "
            "ready/pending counts are wrong. Keep the patch implementation-only, "
            "verify with the smallest useful test command, and stop once the flush "
            "report behavior is correct. The fix is expected to be narrow, but it may "
            "require touching more than one implementation file."
        ),
        "verify_command": "python3 -m unittest tests.test_flush_report",
        "expected_modified_files": ["worker/flush_report.py", "worker/reporting.py"],
        "max_turns": 14,
    },
    "session_store_exploration": {
        "title": "Repo exploration flush bugfix",
        "prompt": (
            "You are triaging a small Python repo inside a disposable benchmark "
            "workspace. A flush-related regression is hiding ready records in the "
            "wrong result bucket. The failing test is somewhere under `tests/`, but "
            "the buggy implementation file is not named in this prompt. Use tools to "
            "locate the relevant code, keep the patch minimal, and verify with the "
            "smallest useful test command before stopping. Do not change "
            "`worker/reporting.py` unless the evidence clearly requires it."
        ),
        "verify_command": "python3 -m unittest tests.test_session_store",
        "expected_modified_files": ["worker/session_store.py"],
    },
}
