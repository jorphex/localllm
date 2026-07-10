# Benchmark Barrage V2

V2 is the default evaluation system. It measures four separate things and never combines them into one model score:

- `performance`: repeated cold short/long PP, fixed-workload TG, streamed agent-shaped TTFT/TG, warm append-only cache reuse, and a transparent two-request reference agent loop.
- `tool_contract`: executable tool restraint and tool-followthrough checks, including exact JSON arguments.
- `sandbox`: independent disposable coding tasks with public tests and separate acceptance checks. Completion is primary; tool errors, turns, and file scope are diagnostics.
- `production`: an external-driver protocol for the real OpenWendy or multillm harness. This is deliberately a separate profile class.

## Fair runs

Fair runs use the fixed `fair-v1-128k-q8` profile in `benchmarks/barrage_v2/config.json`. Candidate specs contain only an alias, model path, optional mmproj path, and optional port; per-model tuning is rejected.

```bash
BARRAGE_V2_CANDIDATES='qwen27|qwen-3.6/Qwen3.6-27B-MTP-Q6_K-unsloth.gguf|qwen-3.6/Qwen3.6-27B-MTP-mmproj-F16-unsloth.gguf' \
  bash benchmarks/run_barrage_v2.sh
```

The launcher stops the managed stack, waits for the configured cooldown, verifies that baseline VRAM is at or below `max_baseline_vram_mib`, then runs one scratch server at a time and restores the stack. Set `BARRAGE_V2_STOP_STACK=false` only when GPU residency is already known to be safe; the same baseline gate still applies.

Every candidate writes:

```text
benchmarks/barrage-v2-results/<timestamp>/<alias>/
  manifest.json
  run.json
  trials/*.json
```

The manifest includes the exact profile class/id, resolved process argv, post-load `/props` and `/slots` state, GPU-residency evidence, cache settings, candidate/workload ordering seed, cooldown and baseline-GPU state, config and workload digests, server version, actual GPU probe, and model SHA-256. Fair runs force verbose llama.cpp logging and require every logged tensor layer to be assigned to a non-CPU device, reject any partial aggregate offload report, require `--gpu-layers auto`, and retain a full-model-sized post-load VRAM delta as supporting evidence. Missing verbose layer-placement records invalidate a fair run. Every trial retains its full request and response payload, including warm-cache prime and append calls and any completed turns before a tool or sandbox request fails. A preflight failure writes `trials/preflight-failure.json` plus an `invalid` run summary containing the raw runtime evidence.

The runner exits `0` only for a complete candidate, `1` for a completed candidate with workload errors, and `2` for a preflight-invalid candidate. The launcher continues through every candidate, restores the managed stack, then exits nonzero when any candidate was incomplete or invalid.

## Core and holdout evaluation

Performance trials use the configured repeat count. Tool contracts and coding-agent sandbox tasks use `quality_repeats` (currently three) with a trial-specific seed. Every capability task is labeled `core` or `holdout`; core is the default tuning/comparison set, while holdout is a separately reported release-validation set with independent acceptance checks. This is a governance split, not a secret benchmark: the task definitions remain visible and no core/holdout score is blended into one model rank.

Run the holdout set explicitly:

```bash
BARRAGE_V2_INCLUDE_HOLDOUT=true \
  bash benchmarks/run_barrage_v2.sh
```

Use `BARRAGE_V2_REPEATS` and `BARRAGE_V2_QUALITY_REPEATS` only for smoke or diagnostic runs; their actual values are retained in the manifest. The reference agent loop is a V2-owned two-request tool cycle for timing a visible protocol. It is not a substitute for OpenWendy or another production harness.

## Publishing V2 results

Raw `barrage-v2-results/` artifacts remain local and ignored. Publish a compact, commit-ready summary after inspecting a run:

```bash
python3 -m benchmarks.barrage_v2.publish \
  benchmarks/barrage-v2-results/<timestamp> <label>
python3 benchmarks/generate_results_md.py
```

This writes `benchmarks/summaries/barrage_v2/<label>/summary.json` and updates the committed benchmark rollup without copying raw prompts, responses, or sandbox transcripts.

## Production profiles

Production runs may use a named model-specific service profile, but they are not comparable with fair results or other production profiles by default. Production capability tasks use the same core/holdout selection and `quality_repeats` policy as fair quality tasks.

```bash
BARRAGE_V2_PROFILE_CLASS=production \
BARRAGE_V2_PROFILE_ID=openwendy-r1-qwen27 \
BARRAGE_V2_CONTEXT=131072 \
BARRAGE_V2_EXTRA_ARGS='-np 1 -b 2048 -ub 1024 -fa on -ctk q8_0 -ctv q8_0 --metrics' \
BARRAGE_V2_CACHE_PROMPT=true BARRAGE_V2_CACHE_RAM=2048 BARRAGE_V2_CACHE_REUSE=0 BARRAGE_V2_SLOT_PROMPT_SIMILARITY=0.1 \
BARRAGE_V2_COOLDOWN_SECONDS=30 BARRAGE_V2_MAX_BASELINE_VRAM_MIB=1024 \
BARRAGE_V2_SUITES=production \
BARRAGE_V2_PRODUCTION_DRIVER='/path/to/openwendy-barrage-driver' \
BARRAGE_V2_PRODUCTION_HARNESS='{"id":"openwendy","digest":"immutable-revision-or-config-digest"}' \
BARRAGE_V2_PRODUCTION_TASKS='[{"id":"representative-task-1"}]' \
BARRAGE_V2_CANDIDATES='qwen27|qwen-3.6/Qwen3.6-27B-MTP-Q6_K-unsloth.gguf|qwen-3.6/Qwen3.6-27B-MTP-mmproj-F16-unsloth.gguf' \
  bash benchmarks/run_barrage_v2.sh
```

For an actual external harness, provide a command that reads one JSON request on stdin and writes one JSON result on stdout. Both must include the same `schema_version`, exact `profile` object, and a `harness` object with an `id` and immutable revision/config `digest`. The guard rejects fair requests and profile or harness mismatches:

```bash
python3 -m benchmarks.barrage_v2.production_driver \
  --driver '/path/to/openwendy-barrage-driver' \
  --request production-request.json \
  --out production-result.json
```

This lets the production harness be measured as a versioned dependency rather than hidden inside a supposedly model-only score. The driver must return exactly one result with a boolean `passed` state for every supplied task id; missing, duplicate, unrecognized, or ungraded task results are rejected. A completed production run means the harness executed successfully; its published pass count remains the capability result.

`production` is an isolated suite: it does not stop, restart, probe, or replace the managed stack. It invokes only the external driver and records that fact in the manifest. Provide `BARRAGE_V2_PRODUCTION_DRIVER`, `BARRAGE_V2_PRODUCTION_HARNESS` (JSON with `id` and `digest`), and `BARRAGE_V2_PRODUCTION_TASKS` (JSON task list). The returned external result is stored under `run.json.suites.production`.

OpenWendy has a concrete adapter using its local core API. It creates disposable conversations, pins the supplied OpenWendy model profile, requires a completed named tool event with expected typed arguments and exact tool output plus final assistant-answer text, and deletes each conversation after the task. The harness digest includes the active Git revision, tracked modifications, non-ignored untracked source, local config digest, and adapter source digest, so regenerate it before every run. Before sending work, the adapter identifies the process listening on the configured port, verifies its working directory is the active OpenWendy root, and rejects it when active source files are newer than that process. Restart OpenWendy after source changes before running this profile:

```bash
HARNESS="$(python3 -m benchmarks.barrage_v2.openwendy_driver --metadata)"
BARRAGE_V2_PROFILE_CLASS=production \
BARRAGE_V2_PROFILE_ID=openwendy-core-local \
BARRAGE_V2_CONTEXT=131072 \
BARRAGE_V2_EXTRA_ARGS='managed-by-openwendy' \
BARRAGE_V2_CACHE_PROMPT=true BARRAGE_V2_CACHE_RAM=0 BARRAGE_V2_CACHE_REUSE=0 BARRAGE_V2_SLOT_PROMPT_SIMILARITY=0.1 \
BARRAGE_V2_COOLDOWN_SECONDS=30 BARRAGE_V2_MAX_BASELINE_VRAM_MIB=1024 \
BARRAGE_V2_SUITES=production \
BARRAGE_V2_PRODUCTION_DRIVER='python3 -m benchmarks.barrage_v2.openwendy_driver --model-id local' \
BARRAGE_V2_PRODUCTION_HARNESS="$HARNESS" \
BARRAGE_V2_PRODUCTION_TASKS="$(cat benchmarks/barrage_v2/openwendy_tasks.json)" \
BARRAGE_V2_CANDIDATES='local|qwen-3.6/Qwen3.6-27B-MTP-Q6_K-unsloth.gguf' \
  bash benchmarks/run_barrage_v2.sh
```

The production candidate alias must exactly match the selected OpenWendy model profile; the adapter rejects a mismatch and records non-secret adapter/profile metadata in the result. It does not launch or reconfigure `llama-server`. Production measurements are therefore never fair-profile comparisons.

## Legacy V1

The prior suite is preserved at `legacy/benchmarks-v1-20260710/`. Its historical summaries remain useful observations, but they are not standardized rankings: profile settings varied between candidates; low-level sweeps were not part of the all-model flow; and keyword-based diagnostics are not capability scores.

Keep `transcript_replay` as an OpenCode compatibility regression and `sim_compare` as a legacy production-fit reference until their workloads are migrated into V2. Do not use `agentic_barrage`, `opencode_compare`, or `coding_compare` for model selection.
