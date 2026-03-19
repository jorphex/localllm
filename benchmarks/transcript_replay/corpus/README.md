Real OpenCode export corpus used for transcript-derived replay fixtures.

Contents:
- `exports/*.export.json`: raw `opencode export` output captured from disposable copies of `benchmarks/sim_compare/fixture_repo`

Current captured sessions:
- `retry_triage_real.export.json`
- `retry_fix_real.export.json`
- `queue_fix_real.export.json`
- `soak_real.export.json`

Fixture generation:
- regenerate replay fixtures with `python3 benchmarks/transcript_replay/export_to_fixture.py --export ... --out ...`

Notes:
- these exports are provenance artifacts, not replay inputs directly
- replay-safe fixtures live under `benchmarks/transcript_replay/fixtures/`
- the converter adds a continuation user prompt on assistant-only continuation turns because raw OpenCode tool-loop history is not replay-safe against `llama.cpp` as-is
