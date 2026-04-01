# R9700 Arrival Checklist

This file is the persistent handoff for the AMD Radeon AI PRO R9700 32GB swap and the first 27B model bring-up on this host.

Use this sequence even if the conversation starts from blank context.

## Goals

- Keep GPU-backed model residency to one chat model at a time.
- Preserve a known-good fallback path with the retained Qwen 3.5 9B presets.
- Bring up 27B candidates with the same benchmark discipline used for the 9B passes.

## Current Retained 9B Baselines

- `qwen-3.5-abl` = safest default baseline
- `qwen-3.5-g` = stronger coding-side alternate
- `qwen-3.5` = Unsloth, still pending a fresh hardened-stack rerun

## Hard Rules

- Always unload any loaded GPU-backed chat model before loading a model to test.
- Do not run scratch tuning or benchmark servers while the managed main service is still live.
- Do not use capped `max_tokens` or `thinking_budget_tokens` for viability comparisons unless the explicit goal is truncation testing.
- Do not jump straight into replay/sim/barrage before a candidate has a tuned launch profile.

## Canonical Evaluation Sequence

For every new candidate, especially the first 27B candidates on the R9700:

1. Unload any loaded model.
2. Optimize tunings.
3. Run speed tests on the chosen launch profile.
4. Run the full tests/benches suite.
5. Run barrage/secondary diagnostics last.

In short:

`unload -> optimize tunings -> speed test -> full tests/benches suite -> barrage`

## What The Repo Already Enforces

- `scripts/load-main-preset.sh` stops `localllm-main.service` before starting the requested preset.
- Scratch benchmark entrypoints now unload the managed main service before starting temp candidate servers:
  - `benchmarks/sweep_profiles.sh`
  - `benchmarks/sweep_contexts.sh`
  - `benchmarks/run_model_eval.sh`
  - `benchmarks/coding_compare.sh`
  - `benchmarks/agentic_barrage_compare.sh`
  - `benchmarks/transcript_replay/run_compare.sh`
  - `benchmarks/sim_compare/run_compare.sh`
  - `benchmarks/opencode_compare/run_compare.sh`

## Important Current Caveat

The script layer no longer forces `CUDA0` when device is unset, which helps portability, but the live preset files still explicitly set `MAIN_DEVICE=CUDA0`.

When the R9700 is installed:

- review the preset device/backend fields first
- confirm the correct AMD runtime/backend value for this host
- then update the relevant preset env files before treating the new GPU as ready

## First Post-Install Checks

After hardware install and runtime setup:

1. Confirm the runtime/backend works with a simple `llama-server --version` and one clean service start.
2. Recheck the active preset inventory:
   - `./scripts/list-presets.sh`
3. Load a retained 9B baseline first:
   - `./scripts/load-main-preset.sh qwen-3.5-abl`
4. Confirm service health:
   - `./scripts/current-main.sh`
5. Only then begin 27B bring-up.

## 27B Bring-Up Order

For the first 27B candidate on the R9700:

1. `./scripts/unload-main.sh`
2. Create or stage the 27B preset or candidate spec.
3. Tune launch profile first.
4. Speed-test that tuned profile.
5. Run replay and sim on the tuned profile.
6. Run barrage only after the suite stage.

## Which Scripts To Use

Tuning stage:

- `benchmarks/sweep_profiles.sh`
- `benchmarks/sweep_contexts.sh`

Suite stage:

- `benchmarks/run_model_eval.sh`

Live-model barrage only after the suite stage:

- `benchmarks/agentic_barrage.sh`

## Wrapper Behavior

- Tuning and speed are still separate helpers.
- `benchmarks/run_model_eval.sh` is the suite-stage wrapper.
- `run_model_eval.sh` runs suites in order per candidate.
- Current default suite order there is:
  - `transcript_replay`
  - `sim_compare`
  - `agentic_barrage`

This means there is not yet one single wrapper that performs tuning, speed, and full suites in one command.

The correct top-level flow remains:

1. tuning helper(s)
2. speed helper(s)
3. `run_model_eval.sh` for suite execution

## What To Tune First On 27B

- context ceiling
- batch and ubatch
- warmup vs no-warmup
- fit behavior
- KV cache choice
- backend/build choice on the AMD stack
- any MoE/offload knobs if the chosen 27B candidate needs them

## Success Criteria For First 27B Pass

- one GPU-backed chat model loaded at a time
- one tuned launch profile per candidate before behavior judgment
- speed captured before replay/sim conclusions
- replay and sim complete on the tuned profile
- barrage used only as secondary evidence

## Known Good Fallback

If bring-up gets noisy or ambiguous, return to:

- `./scripts/load-main-preset.sh qwen-3.5-abl`

Then re-check:

- `./scripts/current-main.sh`
