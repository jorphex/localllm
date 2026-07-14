from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from benchmarks.retrieval_v1.runner import (
    EMBED_PROFILES,
    EMBED_WORKLOADS,
    RERANK_DOCUMENTS,
    RERANK_PROFILES,
    RetrievalTuningRunner,
    cosine,
    embedding_command,
    embedding_vectors,
    reranker_command,
    reranker_scores,
    validate_props,
)


class RetrievalTuningTests(unittest.TestCase):
    def test_runner_safety_directory_initialization_is_compatible_with_run_output(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "run"
            RetrievalTuningRunner(output, repeats=3, cooldown=30, restore=False)
            output.mkdir(parents=True, exist_ok=True)
            self.assertTrue((output / "safety").is_dir())

    def test_workloads_match_openwendy_bounds(self) -> None:
        self.assertEqual(len(EMBED_WORKLOADS["openwendy_batch8"]), 8)
        self.assertEqual(len(RERANK_DOCUMENTS), 8)
        self.assertTrue(all(len(document) <= 420 for document in RERANK_DOCUMENTS))

    def test_embedding_profiles_keep_cpu_context_and_pooling(self) -> None:
        for profile in EMBED_PROFILES:
            command = embedding_command(profile, 18092)
            joined = " ".join(command)
            self.assertIn(f"-c {profile['slots'] * 2048}", joined)
            self.assertIn(f"-np {profile['slots']}", joined)
            self.assertIn("--device none --gpu-layers 0", joined)
            self.assertIn("--pooling last", joined)
            self.assertIn("-fa off", joined)

    def test_reranker_profiles_keep_gpu_context_and_pooling(self) -> None:
        for profile in RERANK_PROFILES:
            command = reranker_command(profile, 18093)
            joined = " ".join(command)
            self.assertIn(f"-c {profile['slots'] * 2048}", joined)
            self.assertIn(f"-np {profile['slots']}", joined)
            self.assertIn("--device Vulkan0 --gpu-layers auto --fit on", joined)
            self.assertIn("--pooling rank --reranking", joined)

    def test_embedding_response_validation(self) -> None:
        vector = [0.0] * 2559 + [1.0]
        vectors = embedding_vectors({"data": [{"index": 0, "embedding": vector}]}, 1)
        self.assertEqual(len(vectors[0]), 2560)
        self.assertTrue(math.isclose(cosine(vectors[0], vectors[0]), 1.0))
        with self.assertRaises(ValueError):
            embedding_vectors({"data": [{"index": 0, "embedding": [1.0]}]}, 1)

    def test_reranker_response_validation(self) -> None:
        payload = {
            "results": [
                {"index": 1, "relevance_score": 0.2},
                {"index": 0, "relevance_score": 0.9},
            ]
        }
        indices, scores = reranker_scores(payload, 2)
        self.assertEqual(indices, [1, 0])
        self.assertEqual(scores, [0.2, 0.9])
        with self.assertRaises(ValueError):
            reranker_scores({"results": [{"index": 0, "relevance_score": float("nan")}]}, 1)

    def test_effective_context_is_validated_per_slot(self) -> None:
        validate_props({"default_generation_settings": {"n_ctx": 2048}, "total_slots": 8}, {"slots": 8})
        with self.assertRaises(ValueError):
            validate_props({"default_generation_settings": {"n_ctx": 256}, "total_slots": 8}, {"slots": 8})

    def test_embedding_winner_uses_backfill_to_break_near_tie(self) -> None:
        rows = [
            {
                "status": "passed",
                "profile": {"id": "n8", "slots": 8},
                "workloads": {"openwendy_batch8": {"median_seconds": 1.04}, "backfill_batch32": {"median_seconds": 4.0}},
            },
            {
                "status": "passed",
                "profile": {"id": "n12", "slots": 12},
                "workloads": {"openwendy_batch8": {"median_seconds": 1.0}, "backfill_batch32": {"median_seconds": 5.0}},
            },
        ]
        self.assertEqual(RetrievalTuningRunner.embedding_winner(rows)["profile"]["id"], "n8")

    def test_reranker_winner_enforces_vram_growth_limit(self) -> None:
        def row(profile_id: str, latency: float, vram: int) -> dict:
            return {
                "status": "passed",
                "profile": {"id": profile_id},
                "resources_loaded": {"vram_used_mib": vram},
                "workloads": {"openwendy_docs8": {"median_seconds": latency}},
            }

        rows = [row("current", 1.0, 3500), row("n2", 0.9, 3800), row("n4", 0.8, 4700)]
        self.assertEqual(RetrievalTuningRunner.reranker_winner(rows)["profile"]["id"], "n2")

    def test_validation_requires_material_repeatable_gain(self) -> None:
        def row(profile_id: str, latency: float) -> dict:
            return {
                "status": "passed",
                "profile": {"id": profile_id},
                "workloads": {"primary": {"median_seconds": latency}},
            }

        current = row("current", 1.0)
        self.assertEqual(RetrievalTuningRunner.validated_selection(current, row("noise", 0.99), "primary"), "current")
        self.assertEqual(RetrievalTuningRunner.validated_selection(current, row("winner", 0.5), "primary"), "winner")

    def test_live_embedding_defaults_match_promoted_profile(self) -> None:
        root = Path(__file__).resolve().parents[1]
        unit = (root / "systemd/localllm-embedding.service").read_text(encoding="utf-8")
        script = (root / "scripts/serve-embedding.sh").read_text(encoding="utf-8")
        for text in (unit, script):
            self.assertIn("EMBED_THREADS", text)
            self.assertIn("16384", text)
            self.assertIn("1024", text)
            self.assertIn("-np 8", text)


if __name__ == "__main__":
    unittest.main()
