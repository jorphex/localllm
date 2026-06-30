# Documentation Durability Plan

Goal: keep the pushed repository's durable docs, notes, benchmark summaries, and current conclusions aligned with the latest retained local-LLM stack.

- [x] Verify the working tree and pushed branch state before editing.
- [x] Audit current docs, notes, benchmark summaries, result JSONL files, presets, and site scaffold for stale claims.
- [x] Fix the benchmark-results generator so committed summaries render newest-first instead of lexicographic-latest.
- [x] Refresh `benchmarks/BENCHMARK_RESULTS.md` with the current Qwen3.6/Ornith decision layer, speed snapshots, prompt-cache conclusions, and regenerated committed-summary rollup.
- [x] Refresh repo/benchmark README pointers so future agents know which files are canonical.
- [x] Record the durable outcome in `NOTES.md`.
- [x] Run syntax/lint checks for changed Python and docs tooling.
- [x] Review final diff and commit the documentation refresh.
