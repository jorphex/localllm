import json
import tempfile
import unittest

from pathlib import Path

from benchmarks import config
from benchmarks import harness_catalog
from benchmarks import model_eval
from benchmarks import result_summaries
from benchmarks.sim_compare import run_agentic_sim
from benchmarks.transcript_replay import run_replay


class GitFixtureMixin:
    def _git_init(self, workspace: Path) -> None:
        import subprocess

        subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=workspace, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Tests", "-c", "user.email=tests@example.com", "commit", "-m", "fixture"],
            cwd=workspace,
            check=True,
            capture_output=True,
        )


class HarnessCatalogTests(unittest.TestCase):
    def test_primary_suites_split_general_and_coding_agentic(self):
        general = [suite.name for suite in harness_catalog.primary_suites("general_agentic")]
        coding = [suite.name for suite in harness_catalog.primary_suites("coding_agentic")]

        self.assertEqual(general, ["transcript_replay"])
        self.assertEqual(coding, ["sim_compare"])

    def test_external_cli_policy_prefers_local_harnesses(self):
        policy = harness_catalog.external_cli_policy()
        self.assertIn("local harnesses", policy)
        self.assertIn("OpenCode or PI CLI", policy)


class ReplayHarnessTests(unittest.TestCase):
    def test_turn_matches_expectations_requires_both_finish_reason_and_tool_names(self):
        self.assertTrue(
            run_replay.turn_matches_expectations(
                {"matches_finish_reason": True, "matches_tool_names": True}
            )
        )
        self.assertFalse(
            run_replay.turn_matches_expectations(
                {"matches_finish_reason": True, "matches_tool_names": False}
            )
        )

    def test_summary_for_turn_tracks_expected_tool_names(self):
        turn = {"name": "turn1", "expect": {"finish_reason": "tool_calls", "tool_names": ["read"]}}
        payload = {"messages": [{"role": "user", "content": "hi"}]}
        response = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [{"function": {"name": "read"}}],
                        "content": "",
                        "reasoning_content": "inspect",
                    },
                }
            ],
            "timings": {"predicted_per_second": 12.5, "prompt_per_second": 98.0},
        }

        summary = run_replay.summary_for_turn(turn, payload, response, 1.2)

        self.assertTrue(summary["matches_finish_reason"])
        self.assertTrue(summary["matches_tool_names"])
        self.assertTrue(summary["matches_expectations"])
        self.assertEqual(summary["tool_names"], ["read"])
        self.assertTrue(summary["request_digest"])
        self.assertTrue(summary["response_digest"])
        self.assertEqual(summary["partial_score"], 1.0)

    def test_partial_credit_is_neutral_when_no_tools_expected(self):
        turn = {"name": "turn1", "expect": {"finish_reason": "stop"}}
        payload = {"messages": [{"role": "user", "content": "hi"}]}
        response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "ok", "tool_calls": []},
                }
            ],
            "timings": {},
        }
        summary = run_replay.summary_for_turn(turn, payload, response, 1.0)
        self.assertEqual(summary["partial_score"], 1.0)

    def test_partial_credit_rewards_set_overlap_not_order(self):
        turn = {"name": "turn1", "expect": {"finish_reason": "tool_calls", "tool_names": ["read", "write"]}}
        payload = {"messages": [{"role": "user", "content": "hi"}]}
        response = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "write"}},
                            {"function": {"name": "read"}},
                        ],
                        "content": "",
                    },
                }
            ],
            "timings": {},
        }

        summary = run_replay.summary_for_turn(turn, payload, response, 1.0)

        self.assertFalse(summary["matches_tool_names"])
        self.assertFalse(summary["matches_expectations"])
        self.assertEqual(summary["tool_set_jaccard"], 1.0)
        self.assertGreater(summary["partial_score"], 0.6)

    def test_replay_fixture_metadata_counts_turn_types(self):
        fixture = {
            "name": "sample",
            "turns": [
                {"name": "turn1", "expect": {"finish_reason": "tool_calls"}},
                {"name": "turn2", "expect": {"finish_reason": "stop"}},
            ],
        }

        metadata = result_summaries.replay_fixture_metadata(fixture)

        self.assertEqual(metadata["turn_count"], 2)
        self.assertEqual(metadata["expected_tool_call_turns"], 1)
        self.assertEqual(metadata["expected_stop_turns"], 1)
        self.assertTrue(metadata["fixture_digest"])


class SimHarnessTests(GitFixtureMixin, unittest.TestCase):
    def test_normalize_test_command_rejects_non_test_commands(self):
        with self.assertRaises(ValueError):
            run_agentic_sim.normalize_test_command("bash scripts/run.sh")

    def test_should_fire_follow_up_respects_returncode_filter(self):
        follow_up = {
            "trigger": {
                "tool_name": "run_tests",
                "count": 1,
                "returncode_nonzero": True,
            }
        }

        self.assertFalse(
            run_agentic_sim.should_fire_follow_up(
                follow_up,
                {"run_tests": 1},
                "run_tests",
                {"returncode": 0},
            )
        )
        self.assertTrue(
            run_agentic_sim.should_fire_follow_up(
                follow_up,
                {"run_tests": 1},
                "run_tests",
                {"returncode": 1},
            )
        )

    def test_verify_scenario_normalizes_verify_command_without_shell(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            (workspace / "worker").mkdir()
            (workspace / "worker" / "retry.py").write_text("print('ok')\n", encoding="utf-8")
            (workspace / "tests").mkdir()
            (workspace / "tests" / "test_retry.py").write_text(
                "import unittest\n\n\nclass RetryTests(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            self._git_init(workspace)

            verification = run_agentic_sim.verify_scenario(
                workspace,
                {
                    "verify_command": "python -m unittest tests.test_retry",
                    "expected_modified_files": [],
                },
            )

        self.assertEqual(
            verification["normalized_verify_command"],
            ["python3", "-m", "unittest", "tests.test_retry"],
        )
        self.assertEqual(verification["verify_returncode"], 0)

    def test_verify_scenario_marks_scope_clean_only_for_expected_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            (workspace / "worker").mkdir()
            (workspace / "worker" / "retry.py").write_text("print('ok')\n", encoding="utf-8")
            (workspace / "tests").mkdir()
            (workspace / "tests" / "test_retry.py").write_text(
                "import unittest\n\n\nclass RetryTests(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            self._git_init(workspace)
            (workspace / "worker" / "retry.py").write_text("print('changed')\n", encoding="utf-8")

            verification = run_agentic_sim.verify_scenario(
                workspace,
                {
                    "verify_command": "python3 -m unittest tests.test_retry",
                    "expected_modified_files": ["worker/retry.py"],
                },
            )

        self.assertEqual(verification["verify_returncode"], 0)
        self.assertTrue(verification["expected_files_only"])
        self.assertEqual(verification["changed_files"], ["worker/retry.py"])

    def test_summarize_result_includes_scope_and_pass_scorecard(self):
        summary = run_agentic_sim.summarize_result(
            "retry_bugfix",
            {
                "title": "Retry helper bugfix",
                "prompt": "Fix the retry helper.",
                "verify_command": "python3 -m unittest tests.test_retry",
                "expected_modified_files": ["worker/retry.py"],
            },
            transcript=[{"turn": 1}, {"turn": 2}],
            verification={
                "verify_returncode": 0,
                "normalized_verify_command": ["python3", "-m", "unittest", "tests.test_retry"],
                "changed_files": ["worker/retry.py"],
                "expected_files_only": True,
                "scope_details": {
                    "extra_files": [],
                    "missing_files": [],
                    "overlap_count": 1,
                },
            },
            total_elapsed=4.5,
            tool_error_count=0,
        )

        self.assertEqual(summary["scenario_family"], "coding_core")
        self.assertTrue(summary["scorecard"]["pass"])
        self.assertTrue(summary["scorecard"]["scope_clean"])
        self.assertTrue(summary["scorecard"]["tool_error_free"])
        self.assertIn("composite", summary["scorecard"])
        self.assertGreater(summary["scorecard"]["composite"], 0.0)

    def test_verify_scenario_reports_scope_details(self):
        with tempfile.TemporaryDirectory() as tempdir:
            workspace = Path(tempdir)
            (workspace / "worker").mkdir()
            (workspace / "worker" / "retry.py").write_text("print('ok')\n", encoding="utf-8")
            (workspace / "tests").mkdir()
            (workspace / "tests" / "test_retry.py").write_text(
                "import unittest\n\n\nclass RetryTests(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            self._git_init(workspace)
            (workspace / "worker" / "retry.py").write_text("print('changed')\n", encoding="utf-8")
            (workspace / "worker" / "extra.py").write_text("print('extra')\n", encoding="utf-8")

            verification = run_agentic_sim.verify_scenario(
                workspace,
                {
                    "verify_command": "python3 -m unittest tests.test_retry",
                    "expected_modified_files": ["worker/retry.py", "worker/missing.py"],
                },
            )

        self.assertEqual(verification["scope_details"]["extra_files"], ["worker/extra.py"])
        self.assertEqual(verification["scope_details"]["missing_files"], ["worker/missing.py"])
        self.assertEqual(verification["scope_details"]["overlap_count"], 1)
        self.assertAlmostEqual(verification["scope_score"], 1 / 3, places=4)

    def test_tool_counts_tracks_called_tools(self):
        transcript = [
            {
                "response": {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {"function": {"name": "read_file"}},
                                    {"function": {"name": "run_tests"}},
                                ]
                            }
                        }
                    ]
                }
            },
            {
                "response": {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {"function": {"name": "run_tests"}},
                                ]
                            }
                        }
                    ]
                }
            },
        ]

        counts = run_agentic_sim.tool_counts(transcript)

        self.assertEqual(counts, {"read_file": 1, "run_tests": 2})


class CompareSummaryTests(GitFixtureMixin, unittest.TestCase):
    def test_replay_run_summary_counts_fixture_and_turn_matches(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_dir = Path(tempdir)
            candidate_dir = results_dir / "qwen" / "fixture_a"
            candidate_dir.mkdir(parents=True)
            (candidate_dir / "result.json").write_text(
                json.dumps(
                    {
                        "all_expectations_met": True,
                        "turns": [
                            {"matches_expectations": True, "partial_score": 1.0, "elapsed_seconds": 1.0},
                            {"matches_expectations": True, "partial_score": 0.75, "elapsed_seconds": 2.0},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = result_summaries.replay_run_summary(results_dir, ["qwen"], ["fixture_a"])

        candidate = summary["candidates"][0]
        self.assertEqual(candidate["passed_fixtures"], 1)
        self.assertEqual(candidate["matched_turns"], 2)
        self.assertEqual(candidate["turn_count"], 2)
        self.assertEqual(candidate["partial_score_avg"], 0.875)

    def test_sim_run_summary_counts_pass_scope_and_tool_hygiene(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_dir = Path(tempdir)
            candidate_dir = results_dir / "qwen" / "retry_bugfix"
            candidate_dir.mkdir(parents=True)
            (candidate_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "scenario_family": "coding_core",
                        "turns": 3,
                        "total_elapsed_seconds": 4.0,
                        "scorecard": {
                            "pass": True,
                            "scope_clean": True,
                            "tool_error_free": False,
                            "efficiency": 1.0,
                            "composite": 0.85,
                        },
                    }
                ),
                encoding="utf-8",
            )

            summary = result_summaries.sim_run_summary(results_dir, ["qwen"], ["retry_bugfix"])

        candidate = summary["candidates"][0]
        self.assertEqual(candidate["pass_count"], 1)
        self.assertEqual(candidate["scope_clean_count"], 1)
        self.assertEqual(candidate["tool_error_free_count"], 0)
        self.assertEqual(candidate["agent_score_avg"], 0.85)


class ConfigTests(unittest.TestCase):
    def test_config_provides_server_defaults_and_suite_items(self):
        self.assertEqual(config.default_context(), 262144)
        self.assertIn("retry_triage_real", config.suite_items("transcript_replay"))
        extra = config.server_extra_args()
        self.assertIn("--reasoning on", extra)
        self.assertIn("--spec-default", extra)

    def test_agentic_sampling_matches_config(self):
        sampling = config.agentic_sampling()
        self.assertEqual(sampling["temperature"], 0.2)
        self.assertTrue(sampling["chat_template_kwargs"]["enable_thinking"])


class BarrageScoreTests(unittest.TestCase):
    def test_tool_restraint_scores_no_tool_call(self):
        from benchmarks import agentic_barrage_score as scorer

        ok = {"choices": [{"message": {"content": "I should not call tools", "tool_calls": []}}]}
        bad = {"choices": [{"message": {"content": "", "tool_calls": [{"function": {"name": "run_tests"}}]}}]}
        self.assertEqual(scorer.tool_names(ok), [])
        self.assertEqual(scorer.tool_names(bad), ["run_tests"])

    def test_full_barrage_scoring_writes_summary(self):
        from benchmarks import agentic_barrage_score as scorer
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "tool_restraint_uncapped_turn1.json").write_text(
                json.dumps({"choices": [{"message": {"content": "skip tools", "tool_calls": []}}]}),
                encoding="utf-8",
            )
            (out / "tool_followthrough_uncapped_turn1.json").write_text(
                json.dumps({"choices": [{"message": {"content": "", "tool_calls": [{"function": {"name": "add", "arguments": "{}"}}]}}]}),
                encoding="utf-8",
            )
            (out / "tool_followthrough_uncapped_turn2.json").write_text(
                json.dumps({"choices": [{"message": {"content": "The answer is 4.", "tool_calls": []}}]}),
                encoding="utf-8",
            )

            with patch("sys.argv", ["agentic_barrage_score.py", str(out)]):
                scorer.main()

            summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["suite"], "agentic_barrage")
            self.assertGreater(summary["average_score"], 0.0)


class CodingScoreTests(unittest.TestCase):
    def test_clean_code_strips_fences(self):
        from benchmarks import coding_compare_score as scorer

        raw = "```python\ndef f():\n    pass\n```"
        self.assertEqual(scorer.clean_code(raw), "def f():\n    pass")

    def test_simple_edit_passes_hidden_test(self):
        from benchmarks import coding_compare_score as scorer

        code = "def normalize_tags(tags):\n    return [t.strip().lower() for t in tags if t.strip()]\n"
        result = scorer.run_test("simple_edit", code, scorer.HIDDEN_TESTS["simple_edit"])
        self.assertTrue(result["passed"], result["stderr"])


class PublishSummaryTests(unittest.TestCase):
    def test_publish_summary_copies_summary_and_manifest(self):
        from benchmarks import publish_summary
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "summary.json").write_text(json.dumps({"score": 1.0}), encoding="utf-8")
            (src / "run_manifest.json").write_text(json.dumps({"run": 1}), encoding="utf-8")

            summaries_root = Path(tmp) / "summaries"
            with patch("benchmarks.publish_summary.SUMMARIES_DIR", summaries_root):
                with patch("sys.argv", ["publish_summary.py", str(src), "transcript_replay", "run1"]):
                    publish_summary.main()

            self.assertTrue((summaries_root / "transcript_replay" / "run1" / "summary.json").exists())
            self.assertTrue((summaries_root / "transcript_replay" / "run1" / "run_manifest.json").exists())


class ResultsMdTests(unittest.TestCase):
    def test_generate_results_md_preserves_marker_and_appends(self):
        from benchmarks import generate_results_md
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            summaries = Path(tmp) / "summaries"
            output = Path(tmp) / "BENCHMARK_RESULTS.md"
            output.write_text("# Old\n\n<!-- BENCHMARK-AUTO-GENERATED -->\n", encoding="utf-8")

            with patch("benchmarks.generate_results_md.SUMMARIES_DIR", summaries):
                with patch("benchmarks.generate_results_md.OUTPUT", output):
                    generate_results_md.main()

            text = output.read_text(encoding="utf-8")
            self.assertIn("# Old", text)
            self.assertIn("# Committed Summary Rollup", text)


class ModelEvalTests(unittest.TestCase):
    def test_parse_candidate_specs_assigns_ports_when_missing(self):
        candidates = model_eval.parse_candidate_specs(
            "alpha|models/a.gguf||32768|-b 256;beta|models/b.gguf|proj.gguf|65536|-b 128",
            base_port=9800,
        )

        self.assertEqual(candidates[0]["alias"], "alpha")
        self.assertEqual(candidates[0]["port"], 9800)
        self.assertEqual(candidates[1]["alias"], "beta")
        self.assertEqual(candidates[1]["port"], 9801)

    def test_coding_compare_spec_uses_config_sampling(self):
        spec = model_eval.coding_compare_spec(
            {
                "alias": "alpha",
                "model": "models/a.gguf",
                "mmproj": "",
                "context": 32768,
                "extra_args": "-b 256",
                "port": 9800,
            }
        )
        parts = spec.split("|")
        self.assertEqual(parts[5], "0.2")  # temperature
        self.assertEqual(parts[6], "0.95")  # top_p
        self.assertEqual(parts[7], "20")  # top_k
        self.assertEqual(parts[8], "0.0")  # presence_penalty
        self.assertEqual(parts[9], "1.05")  # repeat_penalty
        self.assertEqual(parts[10], "9800")  # port

    def test_parse_candidate_specs_keeps_explicit_port(self):
        candidates = model_eval.parse_candidate_specs(
            "alpha|models/a.gguf||32768|-b 256|9950",
            base_port=9800,
        )

        self.assertEqual(candidates[0]["port"], 9950)

    def test_build_model_eval_summary_collects_suite_artifacts(self):
        with tempfile.TemporaryDirectory() as tempdir:
            results_dir = Path(tempdir)
            suite_dir = results_dir / "alpha" / "transcript_replay"
            suite_dir.mkdir(parents=True)
            (suite_dir / "summary.json").write_text(
                json.dumps({"family": "general_agentic", "suite": "transcript_replay"}),
                encoding="utf-8",
            )
            (suite_dir / "run_manifest.json").write_text(
                json.dumps({"requested_candidates": ["alpha"]}),
                encoding="utf-8",
            )
            barrage_dir = results_dir / "alpha" / "agentic_barrage"
            barrage_dir.mkdir(parents=True)
            (barrage_dir / "results.ndjson").write_text('{"label":"turn1"}\n{"label":"turn2"}\n', encoding="utf-8")

            summary = model_eval.build_model_eval_summary(
                results_dir,
                [
                    {
                        "alias": "alpha",
                        "model": "models/a.gguf",
                        "mmproj": "",
                        "context": 32768,
                        "extra_args": "-b 256",
                        "port": 9800,
                    }
                ],
                ["transcript_replay", "agentic_barrage"],
            )

        suites = summary["candidates"][0]["suites"]
        self.assertEqual(suites["transcript_replay"]["summary"]["suite"], "transcript_replay")
        self.assertEqual(suites["agentic_barrage"]["result_count"], 2)



if __name__ == "__main__":
    unittest.main()
