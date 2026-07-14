# Benchmark Barrage V2

V2 is the default evaluation system. It measures six separate things and never combines them into one model score:

- `performance`: repeated cold PP, deterministic recall at approximately 8k/32k/64k/120k prompt sizes, fixed-workload TG, streamed agent-shaped TTFT/TG, 8k/32k warm append reuse, and a transparent two-request reference agent loop.
- `tool_contract`: executable restraint, exact arguments, dependent sequences, parallel calls, tool-error recovery, duplicate-call avoidance, and final evidence use.
- `sandbox`: disposable coding tasks ranging from small fixes to repository discovery, multi-file changes, and injected test-runner failure. Acceptance, exact file scope, required test execution, and required recovery all determine pass/fail.
- `concurrency`: two simultaneous generation requests and mixed prefill/generation contention, reported independently from single-request throughput.
- `vision`: a deterministic 1024x1024 quadrant task that exercises image ingestion and multimodal decoding; non-vision servers are reported as not applicable.
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

The manifest includes the exact profile class/id, resolved process argv, post-load `/props` and `/slots` state, GPU-residency evidence, cache settings, candidate/workload ordering seed, cooldown and baseline-GPU state, config and workload digests, server version, actual GPU probe, and model SHA-256. Fair runs force verbose llama.cpp logging and require every logged tensor layer to be assigned to a non-CPU device, reject any partial aggregate offload report, require `--gpu-layers auto`, and retain a full-model-sized post-load VRAM delta as supporting evidence. Missing verbose layer-placement records invalidate a fair run. Every trial retains its full request and response payload, including warm-cache prime and append calls and any completed turns before a tool or sandbox request fails. Long-context labels are approximate targets; the actual tokenizer-reported `prompt_n` is authoritative. A preflight failure writes `trials/preflight-failure.json` plus an `invalid` run summary containing the raw runtime evidence.

The runner exits `0` only for a complete candidate, `1` for a completed candidate with workload errors, and `2` for a preflight-invalid candidate. The launcher continues through every candidate, restores the managed stack, then exits nonzero when any candidate was incomplete or invalid.

## Smoke, standard, and release runs

Performance and concurrency trials use `performance_repeats` (normally five). Tool, sandbox, and vision tasks use `quality_repeats` (normally three) with a trial-specific seed. Summaries report median, mean, p95, population standard deviation, pass/error rates, and a 95% Wilson interval where applicable.

Warm append trials use workload- and trial-specific prefix namespaces so unrelated prompt-cache entries cannot masquerade as same-session reuse. A warm trial requires a reported cache hit and permits reprocessing of at most one configured ubatch plus eight template-boundary tokens, capped at 20% of the prime prompt. This accounts for llama.cpp ubatch alignment without allowing a weak cache hit to pass; exact cache counts and the derived threshold remain in raw evidence.

A quick implementation smoke deliberately does not qualify as release evidence:

```bash
BARRAGE_V2_REPEATS=1 BARRAGE_V2_QUALITY_REPEATS=1 \
BARRAGE_V2_CANDIDATES='qwen27|qwen-3.6/model.gguf|qwen-3.6/mmproj.gguf' \
  bash benchmarks/run_barrage_v2.sh
```

A standard core run uses the configured five/three repeats by default. Every capability task is labeled `core` or `holdout`; core is the tuning/comparison set, while holdout is separately reported release validation. This is a governance split, not a secret benchmark: definitions remain visible and no core/holdout score is blended into one rank.

Release mode forces holdouts and fails its explicit gate when repeats are below the configured minimum, a required suite is missing, any required trial fails, or a holdout split is absent:

```bash
BARRAGE_V2_RELEASE_RUN=true \
  bash benchmarks/run_barrage_v2.sh
```

Use `BARRAGE_V2_REPEATS` and `BARRAGE_V2_QUALITY_REPEATS` only for smoke or diagnostic runs; their values and release eligibility are retained. The default fair suites are `performance,tool_contract,sandbox,concurrency,vision`. Vision runs only when `/props` reports `vision=true`, which requires a candidate mmproj. The reference agent loop remains a transparent V2-owned timing protocol, not a substitute for OpenWendy.

## Publishing V2 results

Raw `barrage-v2-results/` artifacts remain local and ignored. Publish a compact, commit-ready summary after inspecting a run:

```bash
python3 -m benchmarks.barrage_v2.publish \
  benchmarks/barrage-v2-results/<timestamp> <label>
python3 benchmarks/generate_results_md.py
```

This writes `benchmarks/summaries/barrage_v2/<label>/summary.json` and updates the committed benchmark rollup without copying raw prompts, responses, generated image data, or sandbox transcripts. Compact summaries retain per-suite reliability, core/holdout counts, applicability, and release-gate evidence for later site ingestion.

## Runtime tuning campaigns

Runtime Tuning V1 is a separate staged workflow built on, but not merged into, the default Barrage V2 suite:

1. Direct tuning measures PP/TG, deterministic and sampled generation, tool-shaped generation, context recall, warm-prefix reuse, fit, and speculative acceptance while selecting a runtime shape.
2. Model-specific finalists run the Barrage V2 `performance`, `tool_contract`, and `vision` suites. These are production-profile validations, not a replacement for a complete fair V2 run; sandbox and concurrency are absent unless explicitly requested.
3. Production candidates may run an alternating OpenWendy A/B through the existing production driver. This measures model plus harness behavior and remains separate from direct model/runtime results.
4. Host safety qualification and guards cover lifecycle risk; they are not model-quality measurements.

The current compact tuning publication is:

```text
benchmarks/summaries/tuning_v1/qwen36-runtime-tuning-20260714/
  summary.json
  REPORT.md
```

Its schema is `runtime-tuning-campaign-v1.0`, so it requires a tuning-specific site normalizer rather than the Barrage V2 normalizer. Publish it as a runtime tuning study, not as a complete V2 model ranking. The OpenWendy section should be described publicly as a production or bespoke agent harness. The 35B Unsloth Barrage total includes a documented ubatch-aware reinterpretation of five retained raw warm-cache grader failures; the compact JSON preserves both raw and derived counts.

## Retrieval runtime tuning

Embedding and reranker serving are tuned separately from model-generation Barrage results. The retrieval runner keeps 2048 context per request slot, uses synthetic OpenWendy-shaped batches, checks embedding dimensions/vector similarity/semantic top results, and compares reranker relevance against its one-slot baseline. It stops and restores the full managed stack and applies the same AMDGPU lifecycle guard to every GPU transition.

```bash
uv run python -m benchmarks.retrieval_v1.runner
uv run python -m benchmarks.retrieval_v1.runner --phase reranker
```

Raw artifacts under `benchmarks/retrieval-v1-results/` are ignored. The current compact publication is `benchmarks/summaries/retrieval_v1/qwen3-retrieval-runtime-20260714/summary.json`, schema `retrieval-runtime-tuning-v1.0`. This is a serving-runtime study, not a general retrieval-model leaderboard.

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

OpenWendy has a concrete adapter using its local core API. It creates disposable conversations, pins the supplied OpenWendy model profile, grades ordered or unordered completed tool events with typed argument/output expectations plus final assistant text, and deletes each conversation after the task. The production corpus covers calculation, tool restraint, workspace status, two concurrent conversations, cancellation, and a holdout workspace write/read roundtrip inside a driver-owned temporary directory under `~/.openwendy/benchmark-workspaces`. The harness digest includes the active Git revision, tracked modifications, non-ignored untracked source, local config digest, and adapter source digest, so regenerate it before every run. Before sending work, the adapter identifies the process listening on the configured port, verifies its working directory is the active OpenWendy root, and rejects it when active source files are newer than that process. Restart OpenWendy after source changes before running this profile:

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

Add `BARRAGE_V2_RELEASE_RUN=true` to the production command for three-repeat core plus holdout release validation. Production concurrency and cancellation are OpenWendy/harness outcomes; fair concurrency remains a raw model/runtime outcome. They are never compared as the same measurement.

The production candidate alias must exactly match the selected OpenWendy model profile; the adapter rejects a mismatch and records non-secret adapter/profile metadata in the result. It does not launch or reconfigure `llama-server`. Production measurements are therefore never fair-profile comparisons.

## Legacy V1

The prior suite is preserved at `legacy/benchmarks-v1-20260710/`. Its historical summaries remain useful observations, but they are not standardized rankings: profile settings varied between candidates; low-level sweeps were not part of the all-model flow; and keyword-based diagnostics are not capability scores.

Keep `transcript_replay` as an OpenCode compatibility regression and `sim_compare` as a legacy production-fit reference until their workloads are migrated into V2. Do not use `agentic_barrage`, `opencode_compare`, or `coding_compare` for model selection.
