# Benchmarks

All model evaluation code lives in this folder.

## Quick start

Run every scored suite against one or more candidates:

```bash
MODEL_EVAL_CANDIDATE_SPECS="qwen|qwen-3.6/Qwen3.6-27B-abliterated-MTP-Q6_K-Huihui.gguf||131072||9711" \
  bash benchmarks/run_model_eval.sh
```

By default this stops the full localllm service stack before the first candidate and restarts it when the run finishes, so each candidate gets a clean GPU.

```bash
# keep the stack running (not recommended if VRAM is tight)
MODEL_EVAL_STOP_STACK=false bash benchmarks/run_model_eval.sh
```

## Families and decision weight

The repo splits behavior into two families and keeps their scores separate:

- `general_agentic`
  - primary: `transcript_replay`
  - secondary: `agentic_barrage`
- `coding_agentic`
  - primary: `sim_compare`
  - secondary: `opencode_compare`
  - tertiary: `coding_compare`

Primary suites decide rankings. Secondary/tertiary suites explain variance.

## Shared configuration

Server defaults, sampling parameters, and scenario lists are centralized in:

- `benchmarks/config.json`
- `benchmarks/config.py` (Python loader/builder)
- `benchmarks/config.sh` (bash loader)

Individual harnesses read from these files instead of duplicating `DEFAULT_EXTRA_ARGS`.

## Scoring

### `transcript_replay`

Replays real exported session fixtures and checks each turn.

Primary metrics:

- `all_expectations_met` / `passed_fixtures` — exact finish_reason and exact tool-name list match.
- `matched_turns` / `turn_count` — turn-level exact match.

Partial-credit diagnostics (new):

- `finish_reason_match`
- `tool_set_jaccard` — order-independent tool-name overlap.
- `tool_count_match`
- `partial_score_avg` — average of the three above.

### `sim_compare`

Drops the model into a disposable repo with failing tests and lets it inspect, patch, and verify.

Primary metrics:

- `scorecard.pass` — target tests pass.
- `scorecard.scope_clean` — only expected files were modified.
- `scorecard.tool_error_free` — no tool execution errors.
- `scorecard.efficiency` — turns used vs scenario max.
- `scorecard.composite` / `agent_score_avg` — weighted composite:
  - `0.40 * pass + 0.25 * scope_clean + 0.20 * tool_error_free + 0.15 * efficiency`

Diagnostics (new):

- `scope_score` — Jaccard overlap of changed files vs expected files.
- `scope_details` — extra files, missing files, overlap count.

### Diagnostic suites (now scored but still secondary)

- `agentic_barrage_score.py` — scenario-specific rubrics for planning, revision, evidence triage, tool restraint, and tool followthrough.
- `opencode_compare/score_compare.py` — rubrics for repo triage, revise-after-feedback, and tool followthrough.
- `coding_compare_score.py` — executes generated code against hidden tests for `simple_edit`, `retry_bug`, `task_runner`, and `merge_intervals`.

## Result publishing and reporting

After each run, `benchmarks/publish_summary.py` copies `summary.json` and `run_manifest.json` into:

```
benchmarks/summaries/<suite>/<run-label>/
```

`benchmarks/generate_results_md.py` reads those committed summaries and regenerates the auto-generated section of `benchmarks/BENCHMARK_RESULTS.md`. The historical content of that file is preserved behind a marker.

## Environment metadata

Every `run_manifest.json` now records:

- `llama-server --version`
- `llama.cpp` git commit (derived from the binary path when possible)
- GPU backend/driver
- Model artifact fingerprint (size + mtime)
- Benchmark config digest

## Entrypoints

- `benchmarks/run_model_eval.sh` — run all suites across candidates.
- `benchmarks/transcript_replay/run_compare.sh` — replay fixtures for one candidate.
- `benchmarks/sim_compare/run_compare.sh` — coding-agent scenarios for one candidate.
- `benchmarks/opencode_compare/run_compare.sh` — OpenCode-shaped prompts for one candidate.
- `benchmarks/coding_compare.sh` — single-turn coding smoke test.
- `benchmarks/agentic_barrage.sh` / `benchmarks/agentic_barrage_compare.sh` — synthetic agent diagnostics.

## External CLI policy

OpenCode or PI CLI are useful for capturing real transcripts and for spot-checks, but they are not the canonical scoring driver. Capture real transcripts, convert them to replay fixtures, and score models inside the local harness where the environment and schema are controlled.
