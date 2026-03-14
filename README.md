# localllm

`localllm` is a local `llama.cpp` service layer for any client that can speak OpenAI-style HTTP.

`openwendy` is one consumer, but the point of this repo is broader reuse: coding-agent harnesses, scripts, and other local apps can all talk to the same model services over HTTP.

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

Any client can point at those services with:
- main base URL: `http://127.0.0.1:8091/v1`
- embedding base URL: `http://127.0.0.1:8092/v1`
- optional router base URL: `http://127.0.0.1:8093/v1`

For `openwendy`, the matching env vars are:
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

Start the current default stack:

```bash
./scripts/start-stack.sh
./scripts/status.sh
```

This now means:
- `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf` main on `CUDA0`
- `Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf`
- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf` embeddings on CPU
- no separate router service by default

Start the same stack but use the lighter `Q4_K_S` main:

```bash
MAIN_MODEL=Huihui-Qwen3.5-9B-abliterated.Q4_K_S.gguf ./scripts/start-stack.sh
```

Start the current proven `9B` profile explicitly:

```bash
MAIN_MODEL=Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf \
MAIN_MMPROJ=Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf \
MAIN_THREADS=10 \
MAIN_CONTEXT=131072 \
MAIN_EXTRA_ARGS='-np 1 -tb 20 -b 4096 -ub 1024 -cram 1024 -fa on -rea on --reasoning-budget 1000' \
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

If you want a separate router service anyway, opt in explicitly:

```bash
START_ROUTER=true \
ROUTER_MODEL=Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf \
./scripts/start-stack.sh
```

Stop the detached services:

```bash
./scripts/stop-stack.sh
```

## systemd --user

For a durable setup, prefer the user-service units under `systemd/` instead of `screen`.

Install or refresh the units:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/projects/localllm/systemd/localllm-main.service ~/.config/systemd/user/localllm-main.service
ln -sf ~/projects/localllm/systemd/localllm-embedding.service ~/.config/systemd/user/localllm-embedding.service
systemctl --user daemon-reload
systemctl --user enable --now localllm-main.service localllm-embedding.service
```

Useful commands:

```bash
systemctl --user status localllm-main.service localllm-embedding.service
systemctl --user restart localllm-main.service
systemctl --user restart localllm-embedding.service
journalctl --user -u localllm-main.service -f
journalctl --user -u localllm-embedding.service -f
```

For startup after reboot without logging in first, enable linger once:

```bash
loginctl enable-linger "$USER"
```

If that command needs elevated privileges on your system, run it once as an administrator.

## API Endpoints

Health:
- `GET http://127.0.0.1:8091/health`
- `GET http://127.0.0.1:8092/health`
- optional `GET http://127.0.0.1:8093/health`

OpenAI-compatible endpoints:
- `POST http://127.0.0.1:8091/v1/chat/completions`
- `POST http://127.0.0.1:8092/v1/embeddings`
- optional `POST http://127.0.0.1:8093/v1/chat/completions`

The services do not require a real API key for local use. Clients that insist on one can use any placeholder string such as `dummy` or `unused`.

### curl examples

Chat:

```bash
curl http://127.0.0.1:8091/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf",
    "messages": [
      {
        "role": "user",
        "content": "Write a Python function that merges overlapping intervals."
      }
    ],
    "temperature": 0.2
  }'
```

Embeddings:

```bash
curl http://127.0.0.1:8092/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf",
    "input": "Refactor the retry loop to handle transient failures."
  }'
```

Vision chat on the same main endpoint:

```bash
curl http://127.0.0.1:8091/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "Describe the UI issues in this screenshot."},
          {"type": "image_url", "image_url": {"url": "https://example.com/screenshot.png"}}
        ]
      }
    ]
  }'
```

### Python client example

```python
from openai import OpenAI

chat = OpenAI(base_url="http://127.0.0.1:8091/v1", api_key="unused")
reply = chat.chat.completions.create(
    model="Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf",
    messages=[{"role": "user", "content": "Suggest a clean Python project layout."}],
    temperature=0.2,
)
print(reply.choices[0].message.content)

embed = OpenAI(base_url="http://127.0.0.1:8092/v1", api_key="unused")
vector = embed.embeddings.create(
    model="Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf",
    input="retry logic for flaky network requests",
)
print(len(vector.data[0].embedding))
```

For a coding-agent harness, the usual split is:
- chat and tool-using reasoning against `http://127.0.0.1:8091/v1`
- embeddings against `http://127.0.0.1:8092/v1`
- optional separate router only if the harness wants a distinct classification endpoint

## Default Script Values

These are the built-in defaults for the scripts unless you override them with environment variables:

- main model: `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf`
- main `mmproj`: `Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf`
- embedding model: `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- separate router service: off by default
- router model if you opt in: `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf`
- ports: `8091`, `8092`, `8093`
- main device defaults: `CUDA0` with `--gpu-layers auto` and `--fit on`
- embedding device defaults: `none` with `--gpu-layers 0` and no `--fit`
- script path discovery prefers `~/.local/share/localllm` and `~/.cache/localllm`, then falls back to the existing `openwendy` locations if that is where your binaries or GGUFs live today

## Current Preferred Stack

For this host, the current preferred `9B` stack is:

- main: `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf`
- main `mmproj`: `Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf`
- embedding: `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- router: shared-main routing inside `openwendy`; no separate router service by default

Current tuning:

- main runs on `CUDA0` with `-t 10 -c 131072 -np 1 -tb 20 -b 4096 -ub 1024 -cram 1024 -fa on -rea on --reasoning-budget 1000`
- embeddings run mostly on CPU with `--device none --gpu-layers 0 -t 8 -c 2048 -ub 128 -np 1 -b 256 -tb 4 -cram 0 --no-warmup -fa off`

Observed steady-state footprint:

- main GPU usage: about `9.4 GiB`
- embedding GPU usage: about `214 MiB`
- embedding RAM usage: about `1.08 GiB` RSS

Preferred GGUF cache root:

- `~/.cache/localllm/gguf`

Fallback GGUF cache root on this host:

- `~/.cache/openwendy/gguf`

Preferred `llama-server` binary path:

- `~/.local/share/localllm/llama.cpp/bin/llama-server`

Fallback binary path on this host:

- `~/.local/share/openwendy/llama.cpp/bin/llama-server`

## Current Cached Models

These are the model files currently present under the active GGUF cache.

### Main / Vision

- `Huihui-Qwen3.5-9B-abliterated.Q4_K_S.gguf`
- `Huihui-Qwen3.5-9B-abliterated.Q4_K_M.gguf`
- `Huihui-Qwen3.5-9B-abliterated.mmproj-Q8_0.gguf`
- source: https://huggingface.co/mradermacher/Huihui-Qwen3.5-9B-abliterated-GGUF

### Embeddings

- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- source: https://huggingface.co/PeterAM4/Qwen3-Embedding-0.6B-GGUF
