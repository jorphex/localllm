# Benchmark Families

This repo now treats benchmark suites as two separate families:

- `general_agentic`
  - primary: `transcript_replay`
  - secondary: `agentic_barrage`
- `coding_agentic`
  - primary: `sim_compare`
  - secondary: `opencode_compare`
  - tertiary: `coding_compare`

## Why The Split Exists

The user’s real workflow is not one thing.

- Some failures are about general agent flow:
  continuation behavior, tool choice, revision after feedback, long-session drift, and whether the model keeps moving without getting weird.
- Other failures are about coding-agent execution:
  reading the right files, making a narrow patch, rerunning the right test, recovering from tool friction, and not touching the wrong files.

Those should not be collapsed into a single score because the failure modes are different.

## Which Suites Should Decide Model Rankings

Top-level orchestration now lives at `benchmarks/run_model_eval.sh`.

- Feed it semicolon-separated candidate specs in `MODEL_EVAL_CANDIDATE_SPECS`.
- It runs the requested suites one candidate at a time: load model, run suite, unload, move to the next candidate.
- It writes a top-level `run_manifest.json` and `summary.json` under `benchmarks/model_eval/results/...`.
- It preserves suite-local scoring instead of inventing one blended benchmark number.

Default automated score shapes:

- `transcript_replay`
  - per fixture: `all_expectations_met`, `matched_turns`, `turn_count`
- `sim_compare`
  - per scenario: `scorecard.pass`, `scorecard.scope_clean`, `scorecard.tool_error_free`
- `agentic_barrage`
  - per request: JSON-line summaries for finish reason, tool count, reasoning size, and speed

This is intentional. The repo should automate scores per test or per scenario, not force all model behavior into one rank number.

Use these as the decision-makers:

- `benchmarks/transcript_replay/run_compare.sh`
  - best for real client-shaped turn flow because fixtures come from real exported sessions.
  - emits `run_manifest.json` and `summary.json` so reruns stay comparable without scraping every per-turn artifact.
- `benchmarks/sim_compare/run_compare.sh`
  - best for coding-agent quality because it forces inspect/patch/verify loops inside a disposable repo and scores scope cleanliness.
  - emits `run_manifest.json` and `summary.json` so pass rate, scope cleanliness, and tool-hygiene totals are preserved at the suite level.

Use these as supporting diagnostics only:

- `benchmarks/agentic_barrage.sh`
  - useful for surfacing obvious verbosity, planning, and tool-restraint pathologies.
- `benchmarks/opencode_compare/run_compare.sh`
  - useful for OpenCode-style prompt and tool behavior without depending on the external CLI.
- `benchmarks/coding_compare.sh`
  - useful as a quick smoke check, but too synthetic to rank serious candidates by itself.

## OpenCode Or PI CLI

Do not make OpenCode or PI CLI the primary benchmark harness.

- They are valuable as transcript sources because they capture real client turn shape.
- They are valuable as spot-check clients when a model looks suspicious.
- They are not ideal as the canonical scoring driver because their own client behavior, timeouts, and environment details can become part of the benchmark result.

Preferred policy:

1. Capture real transcripts from the client you actually use.
2. Convert them into replay fixtures.
3. Score models inside the local harness where the environment and result schema are controlled.

That keeps the benchmark focused on the model, not on client-side noise.
