# localllm

`localllm` owns the local `llama.cpp` service layer that `openwendy` talks to over HTTP.

`openwendy` now keeps the bot, memory, tool orchestration, prompt/tool contracts, and the HTTP model client interface. This project is for the model-serving side only.

## What lives here

- `llama.cpp` process/runtime supervision helpers
- service launch scripts
- device placement decisions
- standalone runtime tests

Current extracted Python files:
- `llama_runtime.py`
- `tests/test_llama_runtime.py`

## Service shape

The intended runtime shape is:
- main chat or chat+vision service on `/v1/chat/completions`
- embedding service on `/v1/embeddings`
- optional router service on its own `/v1/chat/completions` endpoint

The router does not need its own persistent memory. It can either:
- run as a separate small model on its own endpoint
- reuse the main chat endpoint if you want to avoid loading a second model and can accept the extra serial call on routed turns

`openwendy` should point at those services with:
- `LLAMA_CPP_BASE_URL`
- `LLAMA_CPP_EMBEDDING_BASE_URL`
- optional `LLAMA_CPP_ROUTER_BASE_URL`
- `LLAMA_CPP_MANAGE_PROCESSES=false`

## Scripts

The scripts live under `scripts/`.

- `./scripts/serve-main.sh`
  Starts one main `llama-server` process in the foreground.
- `./scripts/serve-embedding.sh`
  Starts one embedding `llama-server` process in the foreground.
- `./scripts/serve-router.sh`
  Starts one router `llama-server` process in the foreground.
- `./scripts/start-stack.sh`
  Launches detached `screen` sessions for main, embedding, and optional router, then waits for health.
- `./scripts/status.sh`
  Shows detached `screen` sessions and current health endpoints.
- `./scripts/stop-stack.sh`
  Stops the detached service screens.

## Quick Start

Start the default stable stack:

```bash
./scripts/start-stack.sh
./scripts/status.sh
```

Start the same stack but force embeddings onto CPU:

```bash
EMBED_DEVICE=none EMBED_GPU_LAYERS=0 ./scripts/start-stack.sh
```

Start a `9B` main model test with CPU embeddings and no router:

```bash
MAIN_MODEL=Huihui-Qwen3.5-9B-abliterated.Q4_K_S.gguf \
MAIN_MMPROJ=Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf \
EMBED_MODEL=Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf \
EMBED_DEVICE=none \
EMBED_GPU_LAYERS=0 \
START_ROUTER=false \
./scripts/start-stack.sh
```

Start the current proven `9B` profile with tuned main settings and lean CPU embeddings:

```bash
MAIN_MODEL=Huihui-Qwen3.5-9B-abliterated.Q4_K_S.gguf \
MAIN_MMPROJ=Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf \
MAIN_THREADS=10 \
MAIN_CONTEXT=8192 \
MAIN_EXTRA_ARGS='-np 1 -tb 20 -b 4096 -ub 1024 -cram 1024 -fa on' \
EMBED_MODEL=Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf \
EMBED_DEVICE=none \
EMBED_GPU_LAYERS=0 \
EMBED_FIT=false \
EMBED_THREADS=8 \
EMBED_CONTEXT=2048 \
EMBED_UBATCH=128 \
EMBED_EXTRA_ARGS='-np 1 -b 256 -tb 4 -cram 0 --no-warmup -fa off' \
START_ROUTER=false \
./scripts/start-stack.sh
```

Stop the detached services:

```bash
./scripts/stop-stack.sh
```

## Default Script Values

These are the built-in defaults for the scripts unless you override them with environment variables:

- main model: `Qwen3VL-4B-Instruct-Q4_K_M.gguf`
- main `mmproj`: `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`
- embedding model: `Qwen3-Embedding-0.6B-Q8_0.gguf`
- router model: `Qwen3.5-2B-Q4_K_M.lmstudio.gguf`
- ports: `8091`, `8092`, `8093`
- device defaults: `CUDA0` with `--gpu-layers auto` and `--fit on`

## Current Preferred Stack

For this host, the current preferred `9B` stack is:

- main: `Huihui-Qwen3.5-9B-abliterated.Q4_K_S.gguf`
- main `mmproj`: `Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf`
- embedding: `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- router: disabled for now

Current tuning:

- main runs on `CUDA0` with `-t 10 -c 8192 -np 1 -tb 20 -b 4096 -ub 1024 -cram 1024 -fa on`
- embeddings run mostly on CPU with `--device none --gpu-layers 0 -t 8 -c 2048 -ub 128 -np 1 -b 256 -tb 4 -cram 0 --no-warmup -fa off`

Observed steady-state footprint:

- main GPU usage: about `7.0 GiB`
- embedding GPU usage: about `214 MiB`
- embedding RAM usage: about `1.08 GiB` RSS

GGUF cache root:

- `~/.cache/openwendy/gguf`

`llama-server` binary default:

- `~/.local/share/openwendy/llama.cpp/bin/llama-server`

## Current Cached Models

These are the model files currently present under `~/.cache/openwendy/gguf`.

### Main / Vision

- `Qwen3VL-4B-Instruct-Q4_K_M.gguf`
- `mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`
- `Huihui-Qwen3.5-4B-abliterated.Q4_K_S.gguf`
- `Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf`
- `Huihui-Qwen3.5-4B-abliterated.mmproj-Q8_0.gguf`
- `Huihui-Qwen3.5-9B-abliterated.Q4_K_S.gguf`
- `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf`
- `Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf`

### Embeddings

- `Qwen3-Embedding-0.6B-Q8_0.gguf`
- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- `Qwen.Qwen3-VL-Embedding-2B.Q4_K_M.gguf`
- `mmproj-Qwen.Qwen3-VL-Embedding-2B.f16.gguf`
- `embeddinggemma-300m-Q4_0.gguf`

### Router

- `Qwen3.5-2B-Q4_K_M.lmstudio.gguf`
- `Qwen3.5-2B-Q4_K_M.gguf`
- `Qwen3.5-0.8B-Q4_K_M.gguf`
