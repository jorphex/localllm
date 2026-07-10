# Benchmark Barrage V2 Completion Plan

Goal: finish the original standardized-barrage scope without conflating model capability with harness behavior.

Criteria:
- Fair results use one locked runtime profile and retain all raw evidence, environment state, failure state, and repeated-trial distributions.
- Fair capability evaluation has explicit core and holdout splits, repeat counts for every scored suite, and no aggregate cross-family rank.
- Low-level direct PP/TG, warm-cache, streamed interaction, and a transparent reference agent-loop lane remain separate metrics.
- Production-harness results run through a versioned driver/task contract and are explicitly incomparable with fair results.
- Raw V2 outputs remain local/ignored; a deterministic publisher produces commit-ready normalized summaries without touching `site/`.
- The implementation, V1 backup, test suite, docs, and a real scratch-server smoke run are persisted in Git without including unrelated working-tree changes.

Out of scope:
- Changing `site/` or its frontend/data implementation.
- Ranking fair and production profiles together.
- Treating repository-visible holdouts as secret benchmarks; they are governance splits with independent acceptance checks.

- [x] Preserve this baseline plan and inventory the current V2/V1 ownership boundary.
- [x] Add versioned core/holdout task metadata and repeat controls for tool, sandbox, and reference-agent evaluation.
- [x] Implement the transparent reference agent-loop timing lane and aggregate its per-turn metrics without blending it into direct PP/TG.
- [x] Add a concrete production-driver adapter/task contract for the locally available harness, or record the external-harness blocker precisely while keeping the generic protocol usable.
- [x] Add deterministic V2 summary publishing with result validation and commit-ready artifacts outside `site/`.
- [x] Expand regression coverage for splits, repeats, agent-loop evidence, publishing, and real-launch lifecycle boundaries.
- [x] Run a real scratch-server V2 smoke candidate, inspect its artifacts, then update docs/notes and verify all checks.
- [x] Persist only V2-related sources, backup, tests, docs, and configuration in Git; leave unrelated working-tree changes untouched.
