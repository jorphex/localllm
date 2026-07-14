from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

import httpx

from pathlib import Path
from unittest.mock import patch

from benchmarks.barrage_v2 import SCHEMA_VERSION
from benchmarks.barrage_v2 import artifacts, openwendy_driver, production_driver, publish, runner
from benchmarks import generate_results_md
from benchmarks.barrage_v2.sandbox import TASKS, run_task, selected_tasks
from benchmarks.barrage_v2.workloads import TOOL_CONTRACTS, selected_items


class FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class FakeStream:
    def __init__(self, body: dict):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        yield 'data: {"choices":[{"delta":{"role":"assistant"}}]}'
        content = self.body.get("choices", [{}])[0].get("message", {}).get("content", "")
        yield f'data: {json.dumps({"choices": [{"delta": {"content": content}}]})}'
        yield f"data: {json.dumps(self.body)}"
        yield "data: [DONE]"


class FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _timed(self, content: str = "OK") -> dict:
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "timings": {"prompt_n": 100, "cache_n": 80, "predicted_n": 10, "prompt_per_second": 200.0, "predicted_per_second": 40.0},
        }

    def post(self, _url: str, *, json: dict, timeout: float):
        del timeout
        tools = json.get("tools", [])
        messages = json["messages"]
        if tools and tools[0]["function"]["name"] == "release_lookup":
            user = messages[0]["content"]
            if "Do not use a tool" in user:
                return FakeResponse(self._timed("hello"))
            tool_outputs = [message["content"] for message in messages if message.get("role") == "tool"]
            if "plugin_core" in user and tool_outputs:
                if any("supports" in output for output in tool_outputs):
                    return FakeResponse(self._timed("Version 2.4.1 is supported."))
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "compatibility",
                                            "function": {
                                                "name": "compatibility_lookup",
                                                "arguments": '{"component":"plugin_core","version":"2.4.1"}',
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            if "preview" in user and tool_outputs:
                if any("2.5.0-rc1" in output for output in tool_outputs):
                    return FakeResponse(self._timed("The preview release is 2.5.0-rc1."))
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "mirror",
                                            "function": {
                                                "name": "mirror_lookup",
                                                "arguments": '{"package":"barrage","channel":"preview"}',
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            if tool_outputs:
                versions = " ".join(tool_outputs)
                return FakeResponse(self._timed(versions))
            if "both independent" in user:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "release-barrage",
                                            "function": {
                                                "name": "release_lookup",
                                                "arguments": '{"package":"barrage","channel":"stable"}',
                                            },
                                        },
                                        {
                                            "id": "release-agentkit",
                                            "function": {
                                                "name": "release_lookup",
                                                "arguments": '{"package":"agentkit","channel":"stable"}',
                                            },
                                        },
                                    ]
                                }
                            }
                        ]
                    }
                )
            package = "agentkit" if "agentkit" in user else "barrage"
            channel = "preview" if "preview" in user else "stable"
            return FakeResponse(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "release",
                                        "function": {
                                            "name": "release_lookup",
                                            "arguments": json_module.dumps({"package": package, "channel": channel}),
                                        },
                                    }
                                ]
                            },
                        }
                    ],
                    "timings": {},
                }
            )
        if tools:
            if messages[-1]["role"] == "tool":
                output = messages[-1]["content"]
                if "TransientRunnerError" in output:
                    return FakeResponse({"choices": [{"message": {"tool_calls": [{"id": "retry-test", "function": {"name": "run_tests", "arguments": '{"command":"python3 tests.py"}'}}]}}]})
                if "wrote discounts.py" in output:
                    code = "from discounts import normalize_discount\n\ndef final_price(price, discount):\n    return round(price * (1 - normalize_discount(discount)), 2)\n"
                    return FakeResponse({"choices": [{"message": {"tool_calls": [{"id": "write-pricing", "function": {"name": "write_file", "arguments": json_module.dumps({"path": "pricing.py", "content": code})}}]}}]})
                if output.startswith("wrote "):
                    return FakeResponse({"choices": [{"message": {"tool_calls": [{"id": "test", "function": {"name": "run_tests", "arguments": '{"command":"python3 tests.py"}'}}]}}]})
                return FakeResponse(self._timed("done"))
            prompt = messages[1]["content"]
            path = "solution.py"
            if "normalize_tags" in prompt:
                code = "def normalize_tags(tags):\n    return [tag.strip().lower() for tag in tags if tag.strip()]\n"
            elif "merge_intervals" in prompt:
                code = "def merge_intervals(intervals):\n    result = []\n    for start, end in sorted(intervals):\n        if result and start <= result[-1][1]:\n            result[-1][1] = max(result[-1][1], end)\n        else:\n            result.append([start, end])\n    return result\n"
            elif "discount normalization" in prompt:
                code = "def normalize_discount(value):\n    return min(1, max(0, value))\n"
                path = "discounts.py"
            elif "boolean parser" in prompt:
                code = "def parse_bool(value):\n    if isinstance(value, str):\n        normalized = value.strip().lower()\n        if normalized in {'true', 'false'}:\n            return normalized == 'true'\n    if isinstance(value, bool):\n        return value\n    raise ValueError(f'invalid boolean: {value!r}')\n"
                path = "parser.py"
            else:
                code = "def call_with_retry(fn, retries=2):\n    for attempt in range(retries + 1):\n        try:\n            return fn()\n        except Exception:\n            if attempt == retries:\n                raise\n"
                path = "solution.py"
            return FakeResponse({"choices": [{"message": {"tool_calls": [{"id": "write", "function": {"name": "write_file", "arguments": json_module.dumps({"path": path, "content": code})}}]}}]})
        if "Final checkpoint code" in messages[-1]["content"]:
            return FakeResponse(self._timed("EMBER-417 HARBOR-263 LANTERN-905"))
        return FakeResponse(self._timed())

    def stream(self, _method: str, _url: str, *, json: dict, timeout: float):
        del timeout
        content = "EMBER-417 HARBOR-263 LANTERN-905" if "Final checkpoint code" in json["messages"][-1]["content"] else "OK"
        return FakeStream(self._timed(content))


class FailingClient(FakeClient):
    def post(self, _url: str, *, json: dict, timeout: float):
        del json, timeout
        raise httpx.ReadTimeout("simulated timeout")


class FailAfterPostsClient(FakeClient):
    def __init__(self, successful_posts: int):
        self.successful_posts = successful_posts
        self.post_count = 0

    def post(self, *args, **kwargs):
        self.post_count += 1
        if self.post_count > self.successful_posts:
            raise httpx.ReadTimeout("simulated timeout")
        return super().post(*args, **kwargs)


class EmptyRestraintClient(FakeClient):
    def post(self, _url: str, *, json: dict, timeout: float):
        del timeout
        messages = json["messages"]
        if json.get("tools") and messages[-1]["role"] == "user" and "Do not use a tool" in messages[-1]["content"]:
            return FakeResponse(self._timed(""))
        return super().post(_url, json=json, timeout=1)


class VisionFakeClient(FakeClient):
    def post(self, _url: str, *, json: dict, timeout: float):
        if isinstance(json["messages"][-1]["content"], list):
            return FakeResponse(self._timed("TOP_LEFT=red BOTTOM_RIGHT=yellow"))
        return super().post(_url, json=json, timeout=timeout)


class CancelFakeClient:
    def post(self, url: str, *, json: dict | None = None):
        del json
        if url.endswith("/api/conversations"):
            return FakeResponse({"conversation": {"conversation_id": "conversation"}})
        if url.endswith("/messages"):
            return FakeResponse({"run_id": "run"})
        if url.endswith("/run/cancel"):
            return FakeResponse({"status": "cancel_requested"})
        raise AssertionError(url)

    def patch(self, _url: str, *, json: dict):
        del json
        return FakeResponse({})

    def get(self, url: str):
        if url.endswith("/snapshot"):
            return FakeResponse(
                {
                    "snapshot": {
                        "terminal": True,
                        "terminal_type": "run_cancelled",
                        "status": "cancelled",
                    }
                }
            )
        raise AssertionError(url)

    def delete(self, _url: str):
        return FakeResponse({})


json_module = json


class BarrageV2Tests(unittest.TestCase):
    def test_config_schema_matches_runner_schema(self):
        config_path = Path(__file__).parents[1] / "benchmarks" / "barrage_v2" / "config.json"
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["schema_version"], SCHEMA_VERSION)

    def test_aggregate_trials_reports_distribution(self):
        summary = artifacts.aggregate_trials(
            [
                {"workload": "pp", "prompt_per_second": 2},
                {"workload": "pp", "prompt_per_second": 4},
                {"workload": "tg", "predicted_per_second": 9},
            ]
        )
        self.assertEqual(summary["pp"]["prompt_per_second"]["median"], 3.0)
        self.assertEqual(summary["pp"]["prompt_per_second"]["mean"], 3.0)
        self.assertEqual(summary["pp"]["prompt_per_second"]["p95"], 4.0)
        self.assertEqual(summary["pp"]["reliability"]["pass_rate"], 0.0)
        self.assertEqual(summary["tg"]["prompt_per_second"]["count"], 0)

    def test_binary_summary_reports_wilson_interval_and_errors(self):
        summary = artifacts.binary_summary(
            [
                {"passed": True},
                {"passed": False},
                {"passed": False, "status": "error"},
            ]
        )
        self.assertEqual(summary["pass_rate"], 0.3333)
        self.assertEqual(summary["error_rate"], 0.3333)
        self.assertLess(summary["wilson_low"], summary["pass_rate"])
        self.assertGreater(summary["wilson_high"], summary["pass_rate"])

    def test_gpu_metadata_falls_back_when_nvidia_command_fails(self):
        with patch("benchmarks.barrage_v2.artifacts.command_output", side_effect=[None, "Driver version: 6.16"]):
            self.assertEqual(artifacts.gpu_metadata()["backend"], "rocm")

    def test_server_version_accepts_llama_cpp_stderr_and_excludes_startup_noise(self):
        result = subprocess.CompletedProcess(
            ["llama-server", "--version"],
            0,
            stdout="",
            stderr="WARNING: graphics driver\nversion: 1306 (db52540f7)\nbuilt with GNU 14\n",
        )
        with patch("benchmarks.barrage_v2.artifacts.subprocess.run", return_value=result):
            self.assertEqual(
                artifacts.server_version(Path("/usr/bin/llama-server")),
                "version: 1306 (db52540f7)\nbuilt with GNU 14",
            )

    def test_performance_and_tool_contracts_emit_expected_records(self):
        client = FakeClient()
        performance = runner.run_performance(client, "http://fake", "fake", 1, 1, 7)
        tools = runner.run_tool_contracts(client, "http://fake", "fake", 1)
        self.assertEqual({row["workload"] for row in performance}, {workload["id"] for workload in runner.PERFORMANCE_WORKLOADS})
        self.assertTrue(all(row["passed"] for row in performance))
        self.assertTrue(all(row["passed"] for row in tools))
        self.assertTrue(all(("request" in row and "response" in row) or "initial_request" in row for row in performance))
        self.assertTrue(
            all(
                row["predicted_per_second"] is None
                for row in performance
                if row["workload"].startswith(("cold_pp_", "context_recall_", "warm_append_"))
            )
        )
        reference_loop = next(row for row in performance if row["workload"] == "reference_agent_loop")
        self.assertEqual(reference_loop["initial_request"]["tool_choice"], "required")
        self.assertEqual(reference_loop["followup_request"]["tool_choice"], "none")
        self.assertEqual(reference_loop["agent_request_count"], 2)
        warm_append = next(row for row in performance if row["workload"] == "warm_append_8k")
        self.assertIn("prime_request", warm_append)
        self.assertIn("prime_response", warm_append)
        self.assertGreaterEqual(warm_append["cache_ratio"], 0.8)
        context = next(row for row in performance if row["workload"] == "context_recall_120k")
        self.assertIsNotNone(context["ttft_seconds"])
        self.assertIn("EMBER-417", context["answer_text"])

    def test_warm_append_requires_a_reported_cache_hit(self):
        class NoCacheClient(FakeClient):
            def _timed(self, content: str = "OK") -> dict:
                body = super()._timed(content)
                body["timings"]["cache_n"] = 0
                return body

        workload = ({"id": "warm_append_test", "kind": "warm", "repeat": 1, "max_tokens": 1},)
        with patch.object(runner, "PERFORMANCE_WORKLOADS", workload):
            result = runner.run_performance(NoCacheClient(), "http://fake", "fake", 1, 1, 7)[0]
        self.assertFalse(result["cache_hit"])
        self.assertFalse(result["passed"])

    def test_warm_cache_gate_allows_one_ubatch_of_reprocessing(self):
        self.assertEqual(runner.warm_cache_required_n(8030, 2048), 5974)
        self.assertGreaterEqual(5978, runner.warm_cache_required_n(8030, 2048))
        self.assertLess(5978, runner.warm_cache_required_n(8030, 0))

    def test_launch_argument_int_reads_ubatch_and_rejects_bad_values(self):
        self.assertEqual(runner.launch_argument_int(["llama-server", "-ub", "2048"], "-ub", "--ubatch"), 2048)
        self.assertEqual(runner.launch_argument_int(["llama-server"], "-ub", "--ubatch"), 0)
        with self.assertRaises(ValueError):
            runner.launch_argument_int(["llama-server", "-ub", "bad"], "-ub", "--ubatch")

    def test_tool_restraint_requires_a_nonempty_answer(self):
        result = runner.run_tool_contracts(EmptyRestraintClient(), "http://fake", "fake", 1, [TOOL_CONTRACTS[0]])[0]
        self.assertTrue(result["tool_ok"])
        self.assertFalse(result["content_present"])
        self.assertFalse(result["passed"])

    def test_tool_contracts_cover_parallel_dependent_and_error_recovery(self):
        selected = [
            contract
            for contract in TOOL_CONTRACTS
            if contract["id"] in {"dependent_tool_sequence", "parallel_tool_calls", "tool_error_recovery"}
        ]
        results = runner.run_tool_contracts(FakeClient(), "http://fake", "fake", 1, selected)
        self.assertTrue(all(result["passed"] for result in results), results)
        self.assertEqual([len(result["step_results"]) for result in results], [2, 1, 2])
        parallel = next(result for result in results if result["contract"] == "parallel_tool_calls")
        self.assertEqual(len(parallel["step_results"][0]["actual"]), 2)

    def test_sandbox_task_executes_tools_and_acceptance(self):
        result = run_task(FakeClient(), "http://fake", "fake", TASKS[0], 6, 1, trial=2)
        self.assertTrue(result["passed"])
        self.assertEqual(result["trial"], 2)
        self.assertEqual(result["tool_error_count"], 0)
        self.assertTrue(result["scope_clean"])
        self.assertEqual(result["changed_files"], ["solution.py"])
        self.assertGreater(result["agent_metrics"]["request_count"], 0)
        self.assertEqual(result["transcript"][0]["request"]["max_tokens"], 2048)

    def test_sandbox_requires_scope_verification_and_transient_failure_recovery(self):
        task = next(task for task in TASKS if task["id"] == "transient_test_recovery")
        result = run_task(FakeClient(), "http://fake", "fake", task, 8, 1)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["test_attempts"], 2)
        self.assertEqual(result["tool_error_count"], 1)
        self.assertTrue(result["verification_passed"])
        self.assertTrue(result["recovery_completed"])

    def test_concurrency_and_vision_suites_grade_independently(self):
        concurrency = runner.run_concurrency(FakeClient(), "http://fake", "fake", 1, 1)
        self.assertEqual({row["workload"] for row in concurrency}, {"dual_generation", "mixed_prefill_generation"})
        self.assertTrue(all(row["passed"] and row["successful_requests"] == 2 for row in concurrency))
        unsupported = runner.run_vision(FakeClient(), "http://fake", "fake", 1, 1, {"modalities": {"vision": False}})
        self.assertFalse(unsupported["applicable"])
        supported = runner.run_vision(VisionFakeClient(), "http://fake", "fake", 1, 1, {"modalities": {"vision": True}})
        self.assertTrue(supported["applicable"])
        self.assertEqual(supported["passed"], 1)
        self.assertIn("request", supported["trials"][0])
        self.assertIn("digest", supported["trials"][0]["image"])
        self.assertTrue(runner.quadrant_image_data_url(8).startswith("data:image/png;base64,"))

    def test_core_and_holdout_splits_are_explicit(self):
        self.assertTrue(all(task["split"] == "core" for task in selected_tasks(False)))
        self.assertTrue(any(task["split"] == "holdout" for task in selected_tasks(True)))
        self.assertTrue(all(contract["split"] == "core" for contract in selected_items(TOOL_CONTRACTS, False)))
        self.assertTrue(any(contract["split"] == "holdout" for contract in selected_items(TOOL_CONTRACTS, True)))

    def test_production_task_selection_honors_the_holdout_switch(self):
        tasks = [{"id": "core"}, {"id": "holdout", "split": "holdout"}]
        self.assertEqual([task["id"] for task in runner.selected_production_tasks(tasks, False)], ["core"])
        self.assertEqual([task["id"] for task in runner.selected_production_tasks(tasks, True)], ["core", "holdout"])

    def test_openwendy_event_evaluation_requires_terminal_text_and_tool(self):
        result = openwendy_driver.evaluate_task(
            {
                "id": "calculate",
                "expect": {
                    "text": "323",
                    "tool": {
                        "name": "calculate",
                        "arguments": {"operation": "evaluate_expression"},
                        "output": "Exact result: 323",
                    },
                },
            },
            {"terminal_type": "run_completed", "answer_text": "The result is 323."},
            [
                {"type": "user_message", "text": "Use calculate"},
                {
                    "type": "tool_end",
                    "tool_name": "calculate",
                    "state": "completed",
                    "arguments": {"operation": "evaluate_expression", "expression": "17 * 19"},
                    "output": "Exact result: 323",
                },
            ],
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["matching_tool_events"][0]["output"], "Exact result: 323")
        self.assertEqual(result["answer_text"], "The result is 323.")

    def test_openwendy_event_evaluation_rejects_wrong_tool_arguments_or_output(self):
        task = {
            "id": "calculate",
            "expect": {
                "text": "323",
                "tool": {
                    "name": "calculate",
                    "arguments": {"operation": "evaluate_expression"},
                    "output": "Exact result: 323",
                },
            },
        }
        snapshot = {"terminal_type": "run_completed", "answer_text": "The result is 323."}
        for event in (
            {"arguments": {"operation": "round"}, "output": "Exact result: 323"},
            {"arguments": {"operation": "evaluate_expression"}, "output": "323"},
        ):
            result = openwendy_driver.evaluate_task(
                task,
                snapshot,
                [{"type": "tool_end", "tool_name": "calculate", "state": "completed", **event}],
            )
            self.assertFalse(result["passed"])
            self.assertFalse(result["required_tool_found"])

    def test_openwendy_event_evaluation_rejects_prompt_and_tool_output_false_positives(self):
        result = openwendy_driver.evaluate_task(
            {"id": "calculate", "expect": {"text": "323", "tool": "calculate"}},
            {"terminal_type": "run_completed", "answer_text": ""},
            [
                {"type": "user_message", "text": "Use the calculate tool to compute 17 * 19."},
                {"type": "tool_end", "tool_name": "calculate", "state": "completed", "output": "323"},
            ],
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["required_text_found"])

    def test_openwendy_event_evaluation_grades_sequences_restraint_and_extra_tools(self):
        events = [
            {
                "type": "tool_end",
                "tool_name": "workspace_session",
                "state": "completed",
                "arguments": {"operation": "status"},
                "output": "Workspace session status: ready",
            }
        ]
        task = {
            "id": "workspace",
            "expect": {
                "text": "WORKSPACE_STATUS_OK",
                "tools": [
                    {
                        "name": "workspace_session",
                        "arguments": {"operation": "status"},
                        "output_contains": "session status",
                    }
                ],
            },
        }
        result = openwendy_driver.evaluate_task(
            task,
            {"terminal_type": "run_completed", "answer_text": "WORKSPACE_STATUS_OK"},
            events,
        )
        self.assertTrue(result["passed"])
        extra = openwendy_driver.evaluate_task(
            task,
            {"terminal_type": "run_completed", "answer_text": "WORKSPACE_STATUS_OK"},
            [*events, {**events[0], "tool_name": "terminal"}],
        )
        self.assertFalse(extra["passed"])
        restraint = openwendy_driver.evaluate_task(
            {"id": "restraint", "expect": {"text": "OK", "no_tools": True}},
            {"terminal_type": "run_completed", "answer_text": "OK"},
            [],
        )
        self.assertTrue(restraint["passed"])

    def test_openwendy_concurrent_cancel_and_workspace_task_types(self):
        task = {
            "id": "concurrent",
            "cases": [{"id": "one"}, {"id": "two"}],
        }
        with patch(
            "benchmarks.barrage_v2.openwendy_driver.run_openwendy_task",
            side_effect=lambda _client, _url, case, _model, _timeout: {"task_id": case["id"], "passed": True},
        ):
            result = openwendy_driver.run_concurrent_openwendy_task(object(), "http://fake", task, "local", 1)
        self.assertTrue(result["passed"])
        self.assertEqual(result["case_count"], 2)
        cancelled = openwendy_driver.run_cancel_openwendy_task(
            CancelFakeClient(),
            "http://fake",
            {"id": "cancel", "text": "wait"},
            "local",
            1,
        )
        self.assertTrue(cancelled["passed"])
        with tempfile.TemporaryDirectory() as tempdir:
            def fake_workspace_run(_client, _url, generated_task, _model, _timeout):
                tools = generated_task["expect"]["tools"]
                workspace = Path(tools[0]["arguments"]["path"])
                (workspace / "probe.txt").write_text(tools[1]["arguments"]["content"], encoding="utf-8")
                return {"task_id": generated_task["id"], "passed": True}

            with patch("benchmarks.barrage_v2.openwendy_driver.Path.home", return_value=Path(tempdir)), patch(
                "benchmarks.barrage_v2.openwendy_driver.run_openwendy_task",
                side_effect=fake_workspace_run,
            ):
                workspace = openwendy_driver.run_workspace_roundtrip_task(
                    object(), "http://fake", {"id": "workspace"}, "local", 1
                )
        self.assertTrue(workspace["passed"])

    def test_openwendy_source_digest_changes_for_dirty_and_untracked_source(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "module.py"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=Tests", "-c", "user.email=tests@example.com", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
            clean = openwendy_driver.source_digest(root)
            (root / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
            dirty = openwendy_driver.source_digest(root)
            (root / "new_module.py").write_text("VALUE = 3\n", encoding="utf-8")
            untracked = openwendy_driver.source_digest(root)
        self.assertNotEqual(clean, dirty)
        self.assertNotEqual(dirty, untracked)

    def test_openwendy_live_service_identity_rejects_a_stale_or_wrong_process(self):
        root = Path("/expected")
        with patch("benchmarks.barrage_v2.openwendy_driver.listener_pid", return_value=42), patch(
            "benchmarks.barrage_v2.openwendy_driver.process_cwd", return_value=root
        ), patch("benchmarks.barrage_v2.openwendy_driver.process_started_at", return_value=100.0), patch(
            "benchmarks.barrage_v2.openwendy_driver.active_source_mtime", return_value=101.0
        ):
            with self.assertRaisesRegex(ValueError, "predates"):
                openwendy_driver.live_service_identity("http://127.0.0.1:7347", root)
        with patch("benchmarks.barrage_v2.openwendy_driver.listener_pid", return_value=42), patch(
            "benchmarks.barrage_v2.openwendy_driver.process_cwd", return_value=Path("/other")
        ):
            with self.assertRaisesRegex(ValueError, "cwd mismatch"):
                openwendy_driver.live_service_identity("http://127.0.0.1:7347", root)
        with patch("benchmarks.barrage_v2.openwendy_driver.listener_pid", return_value=42), patch(
            "benchmarks.barrage_v2.openwendy_driver.process_cwd", return_value=root
        ), patch("benchmarks.barrage_v2.openwendy_driver.process_started_at", return_value=101.0), patch(
            "benchmarks.barrage_v2.openwendy_driver.active_source_mtime", return_value=100.0
        ):
            self.assertEqual(
                openwendy_driver.live_service_identity("http://127.0.0.1:7347", root),
                {"pid": 42, "process_started_at": 101.0, "source_mtime": 100.0},
            )

    def test_openwendy_rejects_a_candidate_profile_mismatch_before_network_use(self):
        request = {
            "schema_version": SCHEMA_VERSION,
            "profile": {"class": "production", "id": "openwendy"},
            "harness": {"id": "openwendy-core-api", "digest": "digest"},
            "candidate": {"model": "other"},
            "tasks": [{"id": "task"}],
        }
        with patch("benchmarks.barrage_v2.openwendy_driver.harness_metadata", return_value=request["harness"]):
            with self.assertRaises(ValueError):
                openwendy_driver.run_request(request, base_url="http://fake", model_id="local", timeout=1, root=Path("/tmp"))

    def test_publish_creates_compact_summary_without_raw_trials(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            candidate_dir = root / "raw" / "candidate"
            candidate_dir.mkdir(parents=True)
            run = {
                "schema_version": SCHEMA_VERSION,
                "status": "completed",
                "manifest": {
                    "model": "candidate",
                    "generated_at": "2026-07-12T12:00:00+00:00",
                    "profile": {"class": "fair"},
                    "evaluation": {"quality_repeats": 3},
                },
                "suites": {
                    "tool_contract": {
                        "status": "ok",
                        "passed": 6,
                        "total": 6,
                        "splits": {"core": {"passed": 6, "total": 6}},
                        "contracts": [{"raw": "secret"}],
                    },
                    "concurrency": {"status": "ok", "passed": 2, "total": 2, "trials": [{"raw": "secret"}]},
                    "vision": {"status": "ok", "applicable": False, "reason": "vision=false", "trials": []},
                },
                "release_gate": {"requested": False, "passed": False},
                "failures": [],
            }
            (candidate_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
            published = publish.publish(root / "raw", "smoke", root / "summaries")
            summary = json.loads((root / "summaries" / "smoke" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(published["summary"]["candidate_count"], 1)
        self.assertEqual(summary["candidates"][0]["tool_contract"]["passed"], 6)
        self.assertEqual(summary["candidates"][0]["concurrency"]["passed"], 2)
        self.assertEqual(summary["candidates"][0]["generated_at"], "2026-07-12T12:00:00+00:00")
        self.assertFalse(summary["candidates"][0]["vision"]["applicable"])
        self.assertFalse(summary["candidates"][0]["release_gate"]["requested"])
        self.assertNotIn("trials", summary["candidates"][0])
        self.assertNotIn("contracts", summary["candidates"][0]["tool_contract"])

    def test_publish_retains_production_pass_fail_counts(self):
        summary = publish.candidate_summary(
            {
                "manifest": {"model": "candidate"},
                "suites": {
                    "production": {
                        "status": "ok",
                        "harness": {"id": "harness"},
                        "results": [{"task_id": "one", "passed": False}],
                        "passed": 0,
                        "total": 1,
                        "splits": {"core": {"passed": 0, "total": 1, "errors": 0}},
                    }
                },
            }
        )
        self.assertEqual(summary["production"]["passed"], 0)
        self.assertEqual(summary["production"]["total"], 1)

    def test_production_summary_uses_harness_result_columns(self):
        rendered = generate_results_md.render_barrage_v2(
            {
                "candidates": [
                    {
                        "model": "local",
                        "status": "completed",
                        "profile": {"class": "production"},
                        "production": {"harness": {"id": "openwendy-core-api"}, "passed": 1, "total": 2},
                    }
                ]
            }
        )
        self.assertIn("| Candidate | Status | Release | Harness | Core | Holdout |", rendered)
        self.assertIn("| local | completed | smoke/standard | openwendy-core-api | - | - |", rendered)

    def test_partial_tool_and_sandbox_failures_retain_prior_evidence(self):
        tool = runner.run_tool_contracts(FailAfterPostsClient(1), "http://fake", "fake", 1, [TOOL_CONTRACTS[1]])[0]
        self.assertEqual(tool["status"], "error")
        self.assertIn("initial_request", tool)
        self.assertIn("initial_response", tool)
        self.assertIn("followup_request", tool)

        sandbox = run_task(FailAfterPostsClient(1), "http://fake", "fake", TASKS[0], 6, 1)
        self.assertEqual(sandbox["status"], "error")
        self.assertEqual(sandbox["phase"], "model_request")
        self.assertEqual(len(sandbox["transcript"]), 1)
        self.assertIn("request", sandbox)
        self.assertEqual(sandbox["changed_files"], ["solution.py"])

    def test_validate_run_requires_requested_suites(self):
        with self.assertRaises(ValueError):
            runner.validate_run({"schema_version": SCHEMA_VERSION, "suites": {}}, {"sandbox"})

    def test_release_gate_requires_full_repeats_holdouts_and_all_suite_passes(self):
        cfg = {
            "release": {
                "minimum_performance_repeats": 5,
                "minimum_quality_repeats": 3,
                "require_holdout": True,
                "fair_required_suites": ["performance", "tool_contract", "sandbox", "concurrency"],
                "production_required_suites": ["production"],
            }
        }
        manifest = {
            "profile": {"class": "fair"},
            "evaluation": {
                "performance_repeats": 5,
                "quality_repeats": 3,
                "include_holdout": True,
            },
        }
        split = {
            "core": {"passed": 1, "total": 1},
            "holdout": {"passed": 1, "total": 1},
        }
        run = {
            "suites": {
                "performance": {
                    "status": "ok",
                    "summary": {"direct": {"reliability": {"passed": 5, "total": 5, "errors": 0}}},
                },
                "tool_contract": {"status": "ok", "passed": 2, "total": 2, "splits": split},
                "sandbox": {"status": "ok", "passed": 2, "total": 2, "splits": split},
                "concurrency": {"status": "ok", "passed": 2, "total": 2},
                "vision": {"status": "ok", "applicable": False},
            }
        }
        gate = runner.build_release_gate(run, manifest, cfg, True)
        self.assertTrue(gate["passed"], gate)
        manifest["evaluation"]["quality_repeats"] = 1
        failed = runner.build_release_gate(run, manifest, cfg, True)
        self.assertFalse(failed["passed"])
        smoke = runner.build_release_gate(run, manifest, cfg, False)
        self.assertIsNone(smoke["passed"])
        self.assertFalse(smoke["eligible"])

        production_manifest = {
            "profile": {"class": "production"},
            "evaluation": {"performance_repeats": 1, "quality_repeats": 3, "include_holdout": True},
        }
        production_run = {
            "suites": {
                "production": {"status": "ok", "passed": 2, "total": 2, "splits": split},
            }
        }
        production_gate = runner.build_release_gate(production_run, production_manifest, cfg, True)
        self.assertTrue(production_gate["passed"], production_gate)
        self.assertNotIn("performance_repeats", {check["check"] for check in production_gate["checks"]})

    def test_runner_writes_complete_normalized_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            out_dir = Path(tempdir) / "run"
            model_path = Path(tempdir) / "model.gguf"
            model_path.write_bytes(b"x" * 1024)
            server_log = Path(tempdir) / "server.log"
            server_log.write_text("load_tensors: layer   0 assigned to device Vulkan0, is_swa = 0\n", encoding="utf-8")
            argv = [
                "runner.py",
                "--base-url",
                "http://fake",
                "--model",
                "fake",
                "--model-path",
                str(model_path),
                "--out-dir",
                str(out_dir),
                "--profile-class",
                "fair",
                "--profile-id",
                "fair-v1-128k-q8",
                "--repeats",
                "1",
                "--order-seed",
                "7",
                "--candidate-order-index",
                "0",
                "--candidate-count",
                "1",
                "--candidate-order",
                '["fake"]',
                "--launch-argv",
                '["llama-server","-v","--gpu-layers","auto","--cache-prompt"]',
                "--launch-cache-prompt",
                "true",
                "--launch-cache-ram",
                "2048",
                "--launch-cache-reuse",
                "0",
                "--launch-slot-similarity",
                "0.1",
                "--server-props",
                '{"default_generation_settings":{"n_ctx":131072}}',
                "--server-slots",
                '[{"id":0,"n_ctx":131072}]',
                "--schedule",
                "sequential-shuffled-cooldown",
                "--cooldown-seconds",
                "30",
                "--server-log-path",
                str(server_log),
                "--stabilization",
                '{"gpu_mem":{"used_mib":0},"postload_gpu":{"used_mib":500}}',
            ]
            with patch.object(sys, "argv", argv), patch("benchmarks.barrage_v2.runner.httpx.Client", return_value=FakeClient()):
                runner.main()
            run = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["schema_version"], SCHEMA_VERSION)
            self.assertRegex(run["manifest"]["generated_at"], r"^\d{4}-\d{2}-\d{2}T")
            expected_sandbox_trials = len(selected_tasks(False)) * 3
            self.assertEqual(run["suites"]["sandbox"]["passed"], expected_sandbox_trials)
            self.assertTrue(list((out_dir / "trials").glob("performance-*.json")))
            self.assertTrue(run["manifest"]["launch"]["cache_prompt"])
            self.assertEqual(run["manifest"]["execution_order"]["candidate_order"], ["fake"])
            self.assertEqual(run["manifest"]["server_runtime"]["slots"][0]["n_ctx"], 131072)
            self.assertEqual(run["manifest"]["server_runtime"]["offload"]["evidence"], "verbose_layer_assignment")
            self.assertEqual(
                run["manifest"]["evaluation"],
                {
                    "performance_repeats": 1,
                    "quality_repeats": 3,
                    "include_holdout": False,
                    "release_run": False,
                },
            )
            self.assertEqual(run["suites"]["sandbox"]["splits"]["core"]["total"], expected_sandbox_trials)
            self.assertEqual(
                run["manifest"]["workload_digest"],
                artifacts.stable_digest(
                    {
                        "performance": runner.PERFORMANCE_WORKLOADS,
                        "concurrency": runner.CONCURRENCY_WORKLOADS,
                        "vision": runner.VISION_WORKLOAD,
                        "tools": TOOL_CONTRACTS,
                        "tasks": TASKS,
                    }
                ),
            )

    def test_launcher_dry_run_locks_fair_cache_profile(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["bash", "benchmarks/run_barrage_v2.sh"],
            cwd=root,
            env={**os.environ, "BARRAGE_V2_DRY_RUN": "true", "BARRAGE_V2_ORDER_SEED": "7", "BARRAGE_V2_CANDIDATES": "alpha|alpha.gguf;beta|beta.gguf"},
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertIn("-v", payload["extra_args"].split())
        self.assertTrue(payload["cache"]["prompt"])
        self.assertEqual(payload["cache"]["ram_mib"], 2048)
        self.assertEqual(payload["order_seed"], 7)
        self.assertEqual(payload["cooldown_seconds"], 30)
        self.assertEqual(payload["max_baseline_vram_mib"], 1024)
        self.assertFalse(payload["include_holdout"])
        self.assertFalse(payload["release_run"])

    def test_launcher_release_mode_forces_holdouts(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["bash", "benchmarks/run_barrage_v2.sh"],
            cwd=root,
            env={
                **os.environ,
                "BARRAGE_V2_DRY_RUN": "true",
                "BARRAGE_V2_RELEASE_RUN": "true",
                "BARRAGE_V2_ORDER_SEED": "7",
                "BARRAGE_V2_CANDIDATES": "alpha|alpha.gguf",
            },
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["release_run"])
        self.assertTrue(payload["include_holdout"])

    def test_launcher_runs_production_through_external_driver_only(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            (temp_path / "candidate.gguf").write_bytes(b"model")
            driver = temp_path / "driver.py"
            driver.write_text(
                "import json, sys\nrequest=json.load(sys.stdin)\nprint(json.dumps({'schema_version':request['schema_version'],'profile':request['profile'],'harness':request['harness'],'results':[{'task_id':task['id'],'passed':True} for task in request['tasks']]}))\n",
                encoding="utf-8",
            )
            results_dir = temp_path / "results"
            result = subprocess.run(
                ["bash", "benchmarks/run_barrage_v2.sh"],
                cwd=root,
                env={
                    **os.environ,
                    "LLAMA_CPP_MODEL_DIR": tempdir,
                    "BARRAGE_V2_RESULTS_DIR": str(results_dir),
                    "BARRAGE_V2_PROFILE_CLASS": "production",
                    "BARRAGE_V2_PROFILE_ID": "external-test",
                    "BARRAGE_V2_CONTEXT": "131072",
                    "BARRAGE_V2_EXTRA_ARGS": "--external-driver",
                    "BARRAGE_V2_CACHE_PROMPT": "true",
                    "BARRAGE_V2_CACHE_RAM": "0",
                    "BARRAGE_V2_CACHE_REUSE": "0",
                    "BARRAGE_V2_SLOT_PROMPT_SIMILARITY": "0.1",
                    "BARRAGE_V2_COOLDOWN_SECONDS": "30",
                    "BARRAGE_V2_MAX_BASELINE_VRAM_MIB": "1024",
                    "BARRAGE_V2_SUITES": "production",
                    "BARRAGE_V2_CANDIDATES": "external|candidate.gguf",
                    "BARRAGE_V2_PRODUCTION_DRIVER": f"{sys.executable} {driver}",
                    "BARRAGE_V2_PRODUCTION_HARNESS": '{"id":"test-driver","digest":"test-digest"}',
                    "BARRAGE_V2_PRODUCTION_TASKS": '[{"id":"task-1"}]',
                },
                capture_output=True,
                text=True,
                check=False,
            )
            run = json.loads((results_dir / "external" / "run.json").read_text(encoding="utf-8"))
        self.assertIn("BARRAGE_V2_RESULTS_DIR", result.stdout)
        self.assertEqual(result.returncode, 0, run)
        self.assertEqual(run["manifest"]["schedule"]["kind"], "external-driver")
        self.assertTrue(run["manifest"]["schedule"]["stabilization"]["managed_stack_untouched"])
        self.assertEqual(run["manifest"]["production_contract"]["task_ids"], ["task-1"])
        self.assertTrue(run["manifest"]["production_contract"]["tasks_digest"])

    def test_launcher_records_preflight_failure_continues_and_returns_nonzero(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tempdir:
            temp_path = Path(tempdir)
            (temp_path / "good.gguf").write_bytes(b"good")
            driver = temp_path / "driver.py"
            driver.write_text(
                "import json, sys\nrequest=json.load(sys.stdin)\nresults=[{'task_id':task['id'],'passed':True} for task in request['tasks']]\nprint(json.dumps({'schema_version':request['schema_version'],'profile':request['profile'],'harness':request['harness'],'results':results}))\n",
                encoding="utf-8",
            )
            results_dir = temp_path / "results"
            result = subprocess.run(
                ["bash", "benchmarks/run_barrage_v2.sh"],
                cwd=root,
                env={
                    **os.environ,
                    "LLAMA_CPP_MODEL_DIR": tempdir,
                    "BARRAGE_V2_RESULTS_DIR": str(results_dir),
                    "BARRAGE_V2_PROFILE_CLASS": "production",
                    "BARRAGE_V2_PROFILE_ID": "external-test",
                    "BARRAGE_V2_CONTEXT": "131072",
                    "BARRAGE_V2_EXTRA_ARGS": "--external-driver",
                    "BARRAGE_V2_CACHE_PROMPT": "true",
                    "BARRAGE_V2_CACHE_RAM": "0",
                    "BARRAGE_V2_CACHE_REUSE": "0",
                    "BARRAGE_V2_SLOT_PROMPT_SIMILARITY": "0.1",
                    "BARRAGE_V2_COOLDOWN_SECONDS": "30",
                    "BARRAGE_V2_MAX_BASELINE_VRAM_MIB": "1024",
                    "BARRAGE_V2_SUITES": "production",
                    "BARRAGE_V2_ORDER_SEED": "7",
                    "BARRAGE_V2_CANDIDATES": "missing|missing.gguf;good|good.gguf",
                    "BARRAGE_V2_PRODUCTION_DRIVER": f"{sys.executable} {driver}",
                    "BARRAGE_V2_PRODUCTION_HARNESS": '{"id":"test-driver","digest":"test-digest"}',
                    "BARRAGE_V2_PRODUCTION_TASKS": '[{"id":"task-1"}]',
                },
                capture_output=True,
                text=True,
                check=False,
            )
            missing_run = json.loads((results_dir / "missing" / "run.json").read_text(encoding="utf-8"))
            good_run = json.loads((results_dir / "good" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(missing_run["status"], "invalid")
        self.assertIn("candidate model is missing", missing_run["failures"][0]["error_message"])
        self.assertEqual(good_run["status"], "completed")

    def test_runner_rejects_empty_suites_and_fair_context_mismatch(self):
        with self.assertRaises(ValueError):
            runner.parse_suites("")
        with self.assertRaises(ValueError):
            runner.parse_suites("performance,production")
        with self.assertRaises(ValueError):
            runner.validate_fair_runtime(
                {"fair_profile": {"context": 131072}},
                {"default_generation_settings": {"n_ctx": 65536}},
                [{"n_ctx": 65536}],
                "",
            )
        with self.assertRaises(ValueError):
            runner.validate_fair_runtime(
                {"fair_profile": {"context": 131072}},
                {"default_generation_settings": {"n_ctx": 131072}},
                [{"n_ctx": 131072}],
                "offloaded 42/43 layers to GPU\n",
            )

    def test_fair_runtime_accepts_verbose_gpu_layers_with_postload_vram_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            model_path = Path(tempdir) / "model.gguf"
            model_path.write_bytes(b"x" * 1024)
            evidence = runner.validate_fair_runtime(
                {"fair_profile": {"context": 131072}, "execution": {"min_model_vram_residency_ratio": 1.0}},
                {"default_generation_settings": {"n_ctx": 131072}},
                [{"n_ctx": 131072}],
                "load_tensors: layer   0 assigned to device Vulkan0, is_swa = 0\n",
                stabilization={"gpu_mem": {"used_mib": 100}, "postload_gpu": {"used_mib": 500}},
                launch_argv=["llama-server", "-v", "--gpu-layers", "auto"],
                model_path=model_path,
            )
        self.assertEqual(evidence["evidence"], "verbose_layer_assignment")
        self.assertEqual(evidence["delta_mib"], 400)
        self.assertTrue(evidence["model_residency_supporting_evidence"])

    def test_fair_runtime_rejects_missing_or_cpu_verbose_layer_assignments(self):
        with tempfile.TemporaryDirectory() as tempdir:
            model_path = Path(tempdir) / "model.gguf"
            model_path.write_bytes(b"x" * 1024)
            args = {
                "cfg": {"fair_profile": {"context": 131072}, "execution": {"min_model_vram_residency_ratio": 1.0}},
                "props": {"default_generation_settings": {"n_ctx": 131072}},
                "slots": [{"n_ctx": 131072}],
                "stabilization": {"gpu_mem": {"used_mib": 100}, "postload_gpu": {"used_mib": 500}},
                "launch_argv": ["llama-server", "-v", "--gpu-layers", "auto"],
                "model_path": model_path,
            }
            with self.assertRaisesRegex(ValueError, "verbose tensor-layer"):
                runner.validate_fair_runtime(**args, startup_log="offloaded 99/99 layers to GPU\n")
            with self.assertRaisesRegex(ValueError, "assigned model layers to CPU"):
                runner.validate_fair_runtime(
                    **args,
                    startup_log="load_tensors: layer   0 assigned to device CPU, is_swa = 0\n",
                )

    def test_fair_runtime_records_a_sub_model_size_vram_delta_as_supporting_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            model_path = Path(tempdir) / "model.gguf"
            with model_path.open("wb") as model_file:
                model_file.truncate(512 * 1024 * 1024)
            args = {
                "cfg": {"fair_profile": {"context": 131072}, "execution": {"min_model_vram_residency_ratio": 1.0}},
                "props": {"default_generation_settings": {"n_ctx": 131072}},
                "slots": [{"n_ctx": 131072}],
                "startup_log": "load_tensors: layer   0 assigned to device Vulkan0, is_swa = 0\n",
                "launch_argv": ["llama-server", "-v", "--gpu-layers", "auto"],
                "model_path": model_path,
            }
            insufficient = runner.validate_fair_runtime(
                **args,
                stabilization={"gpu_mem": {"used_mib": 100}, "postload_gpu": {"used_mib": 600}},
            )
            sufficient = runner.validate_fair_runtime(
                **args,
                stabilization={"gpu_mem": {"used_mib": 100}, "postload_gpu": {"used_mib": 700}},
            )
        self.assertFalse(insufficient["model_residency_supporting_evidence"])
        self.assertTrue(sufficient["model_residency_supporting_evidence"])

    def test_runner_writes_preflight_failure_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            out_dir = Path(tempdir) / "run"
            server_log = Path(tempdir) / "server.log"
            server_log.write_text("offloaded 99/99 layers to GPU\n", encoding="utf-8")
            argv = [
                "runner.py", "--base-url", "http://fake", "--model", "fake", "--out-dir", str(out_dir), "--profile-class", "fair", "--profile-id", "fair-v1-128k-q8",
                "--order-seed", "7", "--candidate-order-index", "0", "--candidate-count", "1", "--candidate-order", '["fake"]', "--launch-argv", '["llama-server"]',
                "--launch-cache-prompt", "true", "--launch-cache-ram", "2048", "--launch-cache-reuse", "0", "--launch-slot-similarity", "0.1", "--server-props", '{"default_generation_settings":{"n_ctx":65536}}',
                "--server-slots", '[{"n_ctx":65536}]', "--server-log-path", str(server_log), "--stabilization", '{"gpu_mem":{"used_mib":0}}', "--schedule", "test", "--cooldown-seconds", "0",
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(runner.main(), 2)
            run = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
            failure = json.loads((out_dir / "trials" / "preflight-failure.json").read_text(encoding="utf-8"))
            self.assertEqual(run["status"], "invalid")
            self.assertEqual(failure["phase"], "preflight")
            self.assertEqual(failure["evidence"]["server_props"]["default_generation_settings"]["n_ctx"], 65536)
            self.assertIn("offloaded 99/99", failure["evidence"]["startup_log"])

    def test_production_suite_is_written_to_run(self):
        with tempfile.TemporaryDirectory() as tempdir:
            out_dir = Path(tempdir) / "run"
            argv = [
                "runner.py", "--base-url", "http://fake", "--model", "fake", "--out-dir", str(out_dir),
                "--profile-class", "production", "--profile-id", "openwendy-r1", "--suites", "production",
                "--order-seed", "7", "--candidate-order-index", "0", "--candidate-count", "1", "--candidate-order", '["fake"]',
                "--launch-argv", '["llama-server"]', "--launch-cache-prompt", "true", "--launch-cache-ram", "2048",
                "--launch-cache-reuse", "0", "--launch-slot-similarity", "0.1", "--server-props", '{}', "--server-slots", '[]', "--server-log-path", "/dev/null", "--stabilization", '{"mode":"external-driver"}',
                "--schedule", "sequential-shuffled-cooldown", "--cooldown-seconds", "30", "--quality-repeats", "2", "--production-driver", "driver",
                "--production-harness", '{"id":"openwendy","digest":"abc"}', "--production-tasks", '[{"id":"task-1"},{"id":"holdout","split":"holdout"}]',
            ]
            payload = {"schema_version": SCHEMA_VERSION, "profile": {"class": "production", "id": "openwendy-r1"}, "harness": {"id": "openwendy", "digest": "abc"}, "results": [{"task_id": "task-1", "passed": True}]}
            with patch.object(sys, "argv", argv), patch("benchmarks.barrage_v2.runner.httpx.Client", return_value=FakeClient()), patch("benchmarks.barrage_v2.runner.run_driver", return_value=payload):
                runner.main()
            run = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["suites"]["production"]["harness"]["id"], "openwendy")
            self.assertTrue((out_dir / "trials" / "production-task-1-1.json").exists())
            self.assertTrue((out_dir / "trials" / "production-task-1-2.json").exists())
            self.assertEqual(run["manifest"]["production_contract"]["task_ids"], ["task-1"])
            self.assertEqual(run["suites"]["production"]["passed"], 2)
            self.assertEqual(run["suites"]["production"]["splits"]["core"]["total"], 2)

    def test_runner_retains_suite_failures(self):
        with tempfile.TemporaryDirectory() as tempdir:
            out_dir = Path(tempdir) / "run"
            model_path = Path(tempdir) / "model.gguf"
            model_path.write_bytes(b"x" * 1024)
            server_log = Path(tempdir) / "server.log"
            server_log.write_text("load_tensors: layer   0 assigned to device Vulkan0, is_swa = 0\n", encoding="utf-8")
            argv = [
                "runner.py", "--base-url", "http://fake", "--model", "fake", "--model-path", str(model_path), "--out-dir", str(out_dir), "--profile-class", "fair", "--profile-id", "fair-v1-128k-q8", "--suites", "performance,tool_contract,sandbox",
                "--order-seed", "7", "--candidate-order-index", "0", "--candidate-count", "1", "--candidate-order", '["fake"]', "--launch-argv", '["llama-server","-v","--gpu-layers","auto"]',
                "--launch-cache-prompt", "true", "--launch-cache-ram", "2048", "--launch-cache-reuse", "0", "--launch-slot-similarity", "0.1", "--server-props", '{"default_generation_settings":{"n_ctx":131072}}',
                "--server-slots", '[{"n_ctx":131072}]', "--server-log-path", str(server_log), "--stabilization", '{"gpu_mem":{"used_mib":0},"postload_gpu":{"used_mib":500}}', "--schedule", "test", "--cooldown-seconds", "0",
            ]
            with patch.object(sys, "argv", argv), patch("benchmarks.barrage_v2.runner.httpx.Client", return_value=FailingClient()):
                self.assertEqual(runner.main(), 1)
            run = json.loads((out_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["status"], "completed_with_errors")
            self.assertEqual(run["suites"]["performance"]["status"], "completed_with_errors")
            failed = json.loads((out_dir / "trials" / "performance-cold_pp_short-1.json").read_text(encoding="utf-8"))
            self.assertEqual(failed["error_type"], "ReadTimeout")
            self.assertTrue((out_dir / "trials" / "tool-tool_restraint-1.json").exists())
            self.assertTrue((out_dir / "trials" / f"sandbox-{TASKS[0]['id']}-1.json").exists())

    def test_production_driver_rejects_profile_mixing(self):
        with self.assertRaises(ValueError):
            production_driver.run_driver("echo '{}'", {"profile": {"class": "fair"}}, 1)

    def test_production_driver_rejects_incomplete_task_results(self):
        with self.assertRaises(ValueError):
            production_driver.run_driver(
                "printf '%s' '{\"schema_version\":\"barrage-v2.0\",\"profile\":{\"class\":\"production\",\"id\":\"p\"},\"harness\":{\"id\":\"h\",\"digest\":\"d\"},\"results\":[]}'",
                {"profile": {"class": "production", "id": "p"}, "harness": {"id": "h", "digest": "d"}, "tasks": [{"id": "task-1"}]},
                5,
            )

    def test_production_driver_rejects_empty_task_id(self):
        output = json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "profile": {"class": "production", "id": "p"},
                "harness": {"id": "h", "digest": "d"},
                "results": [{"task_id": ""}, {"task_id": "task-1"}],
            }
        )
        with self.assertRaises(ValueError):
            production_driver.run_driver(
                f"printf '%s' '{output}'",
                {"profile": {"class": "production", "id": "p"}, "harness": {"id": "h", "digest": "d"}, "tasks": [{"id": ""}, {"id": "task-1"}]},
                5,
            )

    def test_production_driver_rejects_results_without_a_boolean_passed_field(self):
        output = json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "profile": {"class": "production", "id": "p"},
                "harness": {"id": "h", "digest": "d"},
                "results": [{"task_id": "task-1"}],
            }
        )
        with self.assertRaises(ValueError):
            production_driver.run_driver(
                f"printf '%s' '{output}'",
                {"profile": {"class": "production", "id": "p"}, "harness": {"id": "h", "digest": "d"}, "tasks": [{"id": "task-1"}]},
                5,
            )

    def test_production_driver_accepts_matching_output(self):
        with tempfile.TemporaryDirectory() as tempdir:
            script = Path(tempdir) / "driver.py"
            script.write_text(
                f"import json, sys\nrequest=json.load(sys.stdin)\nprint(json.dumps({{'schema_version':'{SCHEMA_VERSION}','profile':request['profile'],'harness':request['harness'],'results':[{{'task_id':'task-1','passed':True}}]}}))\n",
                encoding="utf-8",
            )
            result = production_driver.run_driver(
                f"python3 {script}",
                {"profile": {"class": "production", "id": "openwendy-r1"}, "harness": {"id": "openwendy", "digest": "abc"}, "tasks": [{"id": "task-1"}]},
                5,
            )
        self.assertEqual(result["profile"]["id"], "openwendy-r1")
