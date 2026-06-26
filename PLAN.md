# Benchmark Standardization Plan

Goal: rework the local model evaluation pipeline so comparisons are reproducible, fairly scored, and automatically documented.

Current state:
- 35 unit tests pass, but they only cover infrastructure.
- Behavior benchmarks are scattered across `transcript_replay`, `sim_compare`, `opencode_compare`, `coding_compare`, and `agentic_barrage`.
- Each harness duplicates server defaults (`DEFAULT_EXTRA_ARGS`, `DEFAULT_CONTEXT`) and has its own scoring rules.
- Some harnesses (`opencode_compare`, `coding_compare`) have no automated scoring.
- `agentic_barrage` uses fragile regex keyword scoring.
- Results are not committed; `BENCHMARK_RESULTS.md` is hand-maintained.
- Run manifests do not capture `llama.cpp` version, GPU driver, model hashes, or seed.

Target state:
1. One canonical benchmark config file drives every harness.
2. Every harness emits a machine-readable `summary.json`.
3. Primary ranking stays split by family (general-agent vs coding-agent); diagnostics are scored but reported separately.
4. Scoring is partial-credit where appropriate and composite for coding agents.
5. Run manifests include environment/version/model-hash metadata.
6. Summaries are committed and `BENCHMARK_RESULTS.md` is regenerated from them.

## Phase 1: Centralize config

- [x] Create `benchmarks/config.json` with shared server defaults, sampling parameters, and scenario/fixture lists.
- [x] Add `benchmarks/config.sh` loader so bash harnesses can source shared values.
- [x] Replace duplicated `DEFAULT_EXTRA_ARGS` / `DEFAULT_CONTEXT` in `transcript_replay/run_compare.sh`, `sim_compare/run_compare.sh`, `opencode_compare/run_compare.sh`.
- [x] Update `run_model_eval.sh` to read defaults from config and allow per-candidate override.

## Phase 2: Improve transcript_replay scoring

- [x] Keep exact-match `matches_expectations` as the primary metric.
- [x] Add partial-credit metrics:
  - `finish_reason_match`
  - `tool_set_jaccard` (set overlap of expected vs observed tool names, ignoring order)
  - `tool_count_match`
- [x] Track per-fixture and aggregate `partial_score` (average of the above).
- [x] Update `result_summaries.replay_run_summary` to include both exact and partial metrics.
- [x] Add tests for partial-credit math in `test_benchmark_harnesses.py`.

## Phase 3: Improve sim_compare scoring

- [x] Keep `pass`, `scope_clean`, and `tool_error_free`.
- [x] Add `efficiency_score` = `1 / median(turns_to_solve)` capped at a sensible max.
- [x] Add `scope_details` reporting extra files and missing files separately.
- [x] Compute composite `agent_score` = `0.40*pass + 0.25*scope_clean + 0.20*tool_error_free + 0.15*efficiency`.
- [x] Update `result_summaries.sim_run_summary` to include composite and component scores.
- [x] Add tests for composite scoring.

## Phase 4: Score the diagnostic harnesses

- [x] `agentic_barrage`: replace regex keyword checks with scenario-specific rubrics.
  - `plan_then_revise`: did the plan mention scope, evidence, validation, and stop condition?
  - `codex_workflow`: did it call `read_file` before `apply_patch`?
  - `tool_restraint`: did it avoid calling `run_tests`?
  - `tool_followthrough`: did it call `add` and then answer correctly on turn 2?
- [x] `opencode_compare`: add pass/fail rubrics for `repo_triage`, `revise_after_feedback`, and `tool_followthrough`.
- [x] `coding_compare`: execute generated code against hidden unit tests for each prompt.
- [x] Emit `summary.json` for each diagnostic harness.

## Phase 5: Lock environment metadata

- [x] Add helpers to capture:
  - `llama-server --version`
  - `llama.cpp` git commit hash
  - GPU driver / backend version
  - Candidate GGUF file hash (sha256 or size+mtime)
  - Benchmark config digest
- [x] Write this metadata into every `run_manifest.json`.

## Phase 6: Store and publish results

- [x] Move committed summaries to `benchmarks/results/<suite>/<timestamp>-<label>/`.
- [x] Add a script `benchmarks/generate_results_md.py` that reads stored summaries and regenerates `BENCHMARK_RESULTS.md`.
- [x] Update `.gitignore` if needed so that only `summary.json`, `run_manifest.json`, and per-run `summary.json` are kept; full per-turn dumps stay in `/tmp` or ignored.
- [x] Run a calibration pass on the current retained model to produce the first committed summaries.

## Phase 7: Add calibration and relative scoring

- [x] Include a baseline candidate in `run_model_eval.sh` runs.
- [x] Report relative metrics (e.g., `replay_relative_to_baseline`, `agent_score_relative_to_baseline`) alongside absolute scores.

## Out of scope for this pass

- Rewriting the unit tests.
- Adding new scenarios or fixtures.
- Changing the model-selection decision rules (e.g., still split by family).

## Success criteria

- `ruff check .` passes.
- `pytest -q` passes.
- Running `run_model_eval.sh` with one candidate produces one `summary.json` per suite and a regenerated `BENCHMARK_RESULTS.md`.
- No duplicated `DEFAULT_EXTRA_ARGS` remain in the benchmark scripts.