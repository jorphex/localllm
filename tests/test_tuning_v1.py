from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.tuning_v1.runner import (
    aggregate,
    assert_invariants,
    best_candidate,
    build_command,
    make_candidate,
    parse_acceptance,
    phase_candidates,
    structured_call_valid,
)
from benchmarks.tuning_v1.publish_campaign import _calculation_followthrough_failure


CONFIG_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "tuning_v1" / "config.json"


class TuningV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_main_shape_matrix_is_unique_and_no_spec(self) -> None:
        candidates = phase_candidates(self.config, "main-shape", [])
        self.assertEqual(len(candidates), 7)
        self.assertEqual(len({candidate["id"] for candidate in candidates}), 7)
        self.assertEqual({candidate["spec_type"] for candidate in candidates}, {"none"})

    def test_other_model_matrix_covers_each_non_main_model(self) -> None:
        candidates = phase_candidates(self.config, "other-models", [])
        counts = {
            model_id: sum(candidate["model_id"] == model_id for candidate in candidates)
            for model_id in ("qwen27-huihui", "qwen35-unsloth", "qwen35-huihui")
        }
        self.assertEqual(counts, {"qwen27-huihui": 5, "qwen35-unsloth": 5, "qwen35-huihui": 4})

    def test_validation_controls_include_no_spec_and_current_production(self) -> None:
        candidates = phase_candidates(self.config, "validation-controls", [])
        self.assertEqual(len(candidates), 4)
        self.assertEqual(sum(candidate["spec_type"] == "none" for candidate in candidates), 3)
        current = next(candidate for candidate in candidates if candidate["spec_type"] == "draft-mtp")
        self.assertEqual(current["model_id"], "qwen27-unsloth")
        self.assertEqual((current["mtp_n"], current["threads"], current["threads_batch"]), (2, 10, 8))

    def test_command_keeps_q8_kv_and_spec_settings(self) -> None:
        model = self.config["models"]["qwen27-unsloth"]
        candidate = make_candidate(
            "qwen27-unsloth",
            model,
            context=32768,
            batch=2048,
            ubatch=1024,
            spec_type="draft-mtp",
            mtp_n=3,
        )
        with tempfile.TemporaryDirectory() as tempdir:
            command = build_command(self.config, candidate, Path(tempdir) / "server.log")
        assert_invariants(command)
        self.assertIn("q8_0", command)
        self.assertEqual(command[command.index("--spec-type") + 1], "draft-mtp")
        self.assertEqual(command[command.index("--spec-draft-n-max") + 1], "3")
        self.assertTrue(command[command.index("--slot-save-path") + 1].endswith(candidate["id"]))

    def test_q4_cache_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invariants|Q4"):
            assert_invariants(["llama-server", "-ctk", "q4_0", "-ctv", "q8_0"])

    def test_acceptance_parser_supports_current_and_short_labels(self) -> None:
        full = (
            "slot print_timing: draft acceptance = 0.85185 ( 46 accepted / 54 generated), "
            "mean acceptance length = 2.70, acceptance rate per position = (0.889, 0.815)"
        )
        parsed = parse_acceptance(full)
        self.assertEqual(parsed["accepted"], 46)
        self.assertEqual(parsed["proposed"], 54)
        self.assertEqual(parsed["acceptance_per_position"], [0.889, 0.815])
        short = "draft acceptance = 1.00000 (2 accepted / 2 generated), mean len = 3.00"
        self.assertEqual(parse_acceptance(short)["mean_acceptance_length"], 3.0)

    def test_structured_call_grader_requires_exact_contract(self) -> None:
        valid = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "release_lookup",
                                    "arguments": '{"package":"barrage","channel":"stable"}',
                                }
                            }
                        ]
                    }
                }
            ]
        }
        self.assertTrue(structured_call_valid(valid))
        valid["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "mirror_lookup"
        self.assertFalse(structured_call_valid(valid))

    def test_best_candidate_requires_all_selection_workloads(self) -> None:
        model = self.config["models"]["qwen27-unsloth"]
        fast = make_candidate("qwen27-unsloth", model, context=32768, batch=2048, ubatch=1024)
        slow = make_candidate("qwen27-unsloth", model, context=32768, batch=1024, ubatch=512)
        rows = []
        for candidate, multiplier in ((fast, 1.0), (slow, 2.0)):
            for workload, elapsed in (("cold_pp_long", 1.0), ("sampled_agent_tg", 5.0), ("structured_tool_tg", 2.0)):
                rows.append(
                    {
                        "candidate_id": candidate["id"],
                        "candidate": candidate,
                        "model_id": "qwen27-unsloth",
                        "phase": "main-shape",
                        "workload": workload,
                        "elapsed_seconds": elapsed * multiplier,
                        "status": "ok",
                        "passed": True,
                    }
                )
        self.assertEqual(best_candidate(rows, "qwen27-unsloth")["id"], fast["id"])
        rows.append(
            {
                "candidate_id": fast["id"],
                "candidate": fast,
                "model_id": "qwen27-unsloth",
                "phase": "main-shape",
                "workload": "sampled_agent_tg",
                "status": "error",
                "passed": False,
            }
        )
        self.assertEqual(best_candidate(rows, "qwen27-unsloth")["id"], slow["id"])
        incomplete = [row for row in rows if row["candidate_id"] == fast["id"] and row["workload"] != "structured_tool_tg"]
        self.assertIsNone(best_candidate(incomplete, "qwen27-unsloth"))

    def test_aggregate_weights_accepted_tokens(self) -> None:
        model = self.config["models"]["qwen27-unsloth"]
        candidate = make_candidate("qwen27-unsloth", model, context=32768, batch=2048, ubatch=1024)
        rows = [
            {
                "candidate_id": candidate["id"],
                "candidate": candidate,
                "model_id": "qwen27-unsloth",
                "phase": "main-spec",
                "workload": "deterministic_tg",
                "elapsed_seconds": 1.0,
                "predicted_per_second": 100.0,
                "status": "ok",
                "passed": True,
                "speculation": {"accepted": 8, "proposed": 10},
            },
            {
                "candidate_id": candidate["id"],
                "candidate": candidate,
                "model_id": "qwen27-unsloth",
                "phase": "main-spec",
                "workload": "deterministic_tg",
                "elapsed_seconds": 2.0,
                "predicted_per_second": 50.0,
                "status": "ok",
                "passed": True,
                "speculation": {"accepted": 1, "proposed": 10},
            },
        ]
        manifest = {"models": {"qwen27-unsloth": {}}}
        summary = aggregate(rows, manifest)
        result = summary["candidate_summaries"][0]["workloads"]["deterministic_tg"]
        self.assertEqual(result["elapsed_seconds"], 1.5)
        self.assertEqual(result["speculation"]["acceptance"], 0.45)

    def test_openwendy_publication_requires_tool_success_and_missing_followthrough(self) -> None:
        failure = {
            "task_id": "calculate_core",
            "terminal_type": "run_completed",
            "required_tool_found": True,
            "answer_text": "",
        }
        self.assertTrue(_calculation_followthrough_failure(failure))
        self.assertFalse(_calculation_followthrough_failure({**failure, "answer_text": "323"}))
        concurrent = {
            "task_id": "concurrent_calculations_core",
            "cases": [
                {"terminal_type": "run_completed", "required_tool_found": True, "answer_text": ""},
                {"terminal_type": "run_completed", "required_tool_found": True, "answer_text": ""},
            ],
        }
        self.assertTrue(_calculation_followthrough_failure(concurrent))


if __name__ == "__main__":
    unittest.main()
