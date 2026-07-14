from __future__ import annotations

import unittest
from pathlib import Path

from benchmarks.tuning_v1.reranker_fit import PROFILES, build_command, layer_candidates


class RerankerFitTests(unittest.TestCase):
    def test_layer_search_descends_from_maximum(self) -> None:
        for profile in PROFILES.values():
            candidates = layer_candidates(profile)
            self.assertEqual(candidates[0], profile["max_gpu_layers"])
            self.assertEqual(candidates[-1], profile["min_gpu_layers"])
            self.assertEqual(candidates, sorted(candidates, reverse=True))

    def test_commands_keep_production_invariants_and_disable_fit(self) -> None:
        for model_id, profile in PROFILES.items():
            with self.subTest(model_id=model_id):
                command = build_command(profile, profile["max_gpu_layers"], Path("/tmp/slots"))
                joined = " ".join(command)
                self.assertIn("--fit off", joined)
                self.assertIn(" -v ", f" {joined} ")
                self.assertIn("-ctk q8_0 -ctv q8_0", joined)
                self.assertIn(f"-c {profile['context']}", joined)
                self.assertIn(f"-b {profile['batch']} -ub {profile['ubatch']}", joined)
                self.assertIn("--image-max-tokens 8192", joined)
                self.assertNotIn("q4_", joined)

    def test_only_huihui_uses_validated_mtp(self) -> None:
        unsloth = " ".join(build_command(PROFILES["qwen35-unsloth"], 41, Path("/tmp/slots")))
        huihui = " ".join(build_command(PROFILES["qwen35-huihui"], 42, Path("/tmp/slots")))
        self.assertNotIn("--spec-type", unsloth)
        self.assertIn("--spec-type draft-mtp --spec-draft-n-max 3", huihui)


if __name__ == "__main__":
    unittest.main()
