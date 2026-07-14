# localllm

`localllm` is a local `llama.cpp` service layer for OpenAI-style clients plus a small CPU TTS sidecar.

## Current Stack

Current live services on this host:

- main chat on `8091`
  - model: `qwen-3.6/Qwen3.6-27B-MTP-Q6_K-unsloth.gguf`
  - alias: `qwen-3.6-27b-mtp-unsloth-q6-fast-128k`
  - runtime: Vulkan / `Vulkan0`
  - shape: `131072` context, `-np 1`, `-b 2048`, `-ub 1024`, `q8_0/q8_0`, draft-MTP `n=2`
  - auth: none

- embeddings on `8092`
  - model: `embedding/Qwen3-Embedding-4B-Q4_K_M.gguf`
  - runtime: CPU only
  - shape: 8 slots, 2048 context per slot, `t12/tb12`, `b1024/ub1024`

- reranker on `8093`
  - model: `embedding/Qwen3-Reranker-4B-Q4_K_M.gguf`
  - alias: `qwen3-reranker-4b-q4`
  - runtime: Vulkan / `Vulkan0`
  - shape: 1 slot, 2048 context, `t8/tb4`, `b512/ub512`, flash attention on

- OmniVoice TTS on `8094`
  - runtime: CPU only

Runtime paths on this host:

- models: `~/projects/localllm/models`
- source checkout: `~/.local/src/llama.cpp`
- backend selection: `config/localllm-runtime.env`

## Repository Boundaries

The repository root owns the local LLM stack and its evidence:

- `config/`, `scripts/`, and `systemd/` define and operate the live services.
- `benchmarks/` owns benchmark definitions, raw local runs, compact published summaries, and the canonical result rollup.
- `NOTES.md` records durable stack and benchmark decisions; `PLAN.md` is used for active non-trivial stack work.

`site/` is a separate frontend consumer of published evidence. Its agent owns the interface, normalization code, display data, and `site/NOTES.md`/`site/PLAN.md`. Stack and benchmark work should not edit frontend implementation or generated site data unless explicitly requested. Frontend work should consume compact summaries under `benchmarks/summaries/`, not ignored raw result directories.

The handoff contract is:

1. Benchmark work validates local raw evidence and publishes a compact, commit-ready `summary.json` with no prompts, responses, transcripts, or generated media.
2. The benchmark rollup in `benchmarks/BENCHMARK_RESULTS.md` provides interpretation and historical context.
3. The frontend adds or updates a schema-specific normalizer under `site/` and verifies the rendered data against the compact summary.

Benchmark families remain separate in both layers. Fair model/runtime results, model-specific tuning, and production-harness behavior must not be blended into one score.

## Service Config

Primary config files:

- `config/localllm-main.env`
- `config/localllm-reranker.env`
- `config/localllm-runtime.env`

Embedding and TTS defaults are currently set in their user-service unit files.

Current retained main-model preset inventory:

- `config/presets/main-qwen-3.6-27b-mtp-huihui-q6-fast-128k.env`
- `config/presets/main-qwen-3.6-27b-mtp-unsloth-q6-fast-128k.env`
- `config/presets/main-qwen-3.6-35b-a3b-huihui-mtp-q6-full-256k-q8.env`
- `config/presets/main-qwen-3.6-35b-a3b-unsloth-q6-fast-160k.env`

## Common Commands

Inspect the live main model:

```bash
./scripts/current-main.sh
```

List retained main presets:

```bash
./scripts/list-presets.sh
```

Reload one of the retained main presets:

```bash
./scripts/load-main-preset.sh qwen-3.6-35b-a3b-huihui-mtp-q6-full-256k-q8
```

Start or stop the current service set:

```bash
./scripts/start-stack.sh
./scripts/stop-stack.sh
./scripts/status.sh
```

## Endpoints

Main chat:

- `GET http://127.0.0.1:8091/health`
- `GET http://127.0.0.1:8091/props`
- `GET http://127.0.0.1:8091/metrics`
- `POST http://127.0.0.1:8091/v1/chat/completions`

Embeddings:

- `GET http://127.0.0.1:8092/health`
- `POST http://127.0.0.1:8092/v1/embeddings`

Reranking:

- `GET http://127.0.0.1:8093/health`
- `POST http://127.0.0.1:8093/v1/rerank`

OmniVoice:

- `GET http://127.0.0.1:8094/health`

## Chat Helpers

Main model TUI:

```bash
./scripts/chat-tui.sh
```

Multi-endpoint CLI chat:

```bash
./scripts/chat.sh
```

`scripts/chat.sh` discovers active local chat services; the default private chat surface is `8091`.

There is no retained localllm shared-chat service or public Tailscale Funnel route.

## Benchmarks

Run a standardized fair evaluation pass:

```bash
BARRAGE_V2_CANDIDATES="qwen|qwen-3.6/Qwen3.6-27B-MTP-Q6_K-unsloth.gguf|qwen-3.6/Qwen3.6-27B-MTP-mmproj-F16-unsloth.gguf" \
  bash benchmarks/run_barrage_v2.sh
```

This stops the full service stack, runs one scratch candidate at a time, and writes a versioned manifest, normalized run summary, and per-trial artifacts under `benchmarks/barrage-v2-results/`. It completes the candidate list and restores the stack even when one candidate is invalid, then exits nonzero so automation cannot treat incomplete results as clean.

See `benchmarks/README.md` for the fair-vs-production profile boundary, scoring details, and the external production-driver protocol. The prior `run_model_eval.sh` results are archived observations, not standardized rankings.

Current durable benchmark read:

- `qwen-3.6-27b-mtp-unsloth-q6-fast-128k` at draft-MTP `n=2`, `t10/tb8` is the current daily default. A tuning finalist at `n=4`, `t12/tb12` improved selected direct TG workloads but tied production-harness task outcomes and was 26% slower by median end-to-end time, so it was not promoted.
- `qwen-3.6-35b-a3b-huihui-mtp-q6-full-256k-q8` is retained as the stronger coding-sim 35B Huihui option, but it does not leave room for the reranker in VRAM at the tested full-context q8-KV shape.
- Ornith Q5/Q6 are archived comparison points; Q5 benchmarked well but was removed after hands-on prose/editing use, and Q6 lost on speed/VRAM/behavior.
- Raw run artifacts are the local source of truth for audit and regrading. Compact summaries under `benchmarks/summaries/` are the publication and frontend-ingestion boundary; `benchmarks/BENCHMARK_RESULTS.md` is the canonical human-readable rollup.
- Retrieval Runtime Tuning V1 promoted eight CPU embedding slots while retaining 2048 context per request; the GPU reranker stayed at one slot after parallel slots caused severe relevance regressions. Compact evidence is under `benchmarks/summaries/retrieval_v1/qwen3-retrieval-runtime-20260714/`.

## Prompt Cache Notes

Relevant server-side knobs:

- `MAIN_CACHE_PROMPT=true|false`
- `MAIN_CACHE_REUSE=<tokens>`
- `MAIN_CACHE_RAM=<MiB>`
- `MAIN_SLOT_PROMPT_SIMILARITY=<0.0-1.0>`
- `MAIN_SLOT_SAVE_PATH=<path>`
- `MAIN_SLOTS=true|false`

Important current behavior:

- prompt cache and slot reuse are enabled for the active main chat service
- `-np 1` means the active main chat service currently has one slot
- large conversations stay associated with that slot until overwritten, cleared, or explicitly erased
