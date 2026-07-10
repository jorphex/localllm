# localllm

`localllm` is a local `llama.cpp` service layer for OpenAI-style clients plus a small CPU TTS sidecar.

## Current Stack

Current live services on this host:

- main chat on `8091`
  - model: `qwen-3.6/Qwen3.6-27B-abliterated-MTP-Q6_K-Huihui.gguf`
  - alias: `qwen-3.6-27b-mtp-huihui-q6-fast-128k`
  - runtime: Vulkan / `Vulkan0`
  - shape: `131072` context, `-np 1`, `-b 2048`, `-ub 1024`, `q8_0/q8_0`, draft-MTP `n=3`
  - auth: none

- embeddings on `8092`
  - model: `embedding/Qwen3-Embedding-4B-Q4_K_M.gguf`
  - runtime: CPU only

- reranker on `8093`
  - model: `embedding/Qwen3-Reranker-4B-Q4_K_M.gguf`
  - alias: `qwen3-reranker-4b-q4`
  - runtime: Vulkan / `Vulkan0`

- OmniVoice TTS on `8094`
  - runtime: CPU only

Runtime paths on this host:

- models: `~/projects/localllm/models`
- source checkout: `~/.local/src/llama.cpp`
- backend selection: `config/localllm-runtime.env`

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

- `qwen-3.6-27b-mtp-huihui-q6-fast-128k` is the daily default because it is the best retained Qwen replay/general-agent fit and can coexist with the reranker in VRAM.
- `qwen-3.6-35b-a3b-huihui-mtp-q6-full-256k-q8` is retained as the stronger coding-sim 35B Huihui option, but it does not leave room for the reranker in VRAM at the tested full-context q8-KV shape.
- Ornith Q5/Q6 are archived comparison points; Q5 benchmarked well but was removed after hands-on prose/editing use, and Q6 lost on speed/VRAM/behavior.
- `benchmarks/BENCHMARK_RESULTS.md` and `benchmarks/summaries/` are archived V1 readouts; V2 run manifests and normalized artifacts are the source of truth for future comparisons.

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
