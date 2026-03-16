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

When `llama_runtime.ManagedLlamaCppRuntime` manages processes directly, it now supports the same extra `llama-server` tuning surface through config keys:
- `llama_cpp_extra_args`
- `llama_cpp_main_extra_args`
- `llama_cpp_embedding_extra_args`
- `llama_cpp_router_extra_args`

Any client can point at those services with:
- main base URL: `http://127.0.0.1:8091/v1`
- embedding base URL: `http://127.0.0.1:8092/v1`
- optional router base URL: `http://127.0.0.1:8093/v1`

Clients that split main, embedding, and optional router URLs can map those endpoints directly onto their own config keys or env vars.

## Compatibility

Preferred runtime roots are:
- `~/.local/share/localllm/llama.cpp/bin/llama-server`
- `~/.cache/localllm/gguf`

For legacy compatibility, path discovery still falls back to:
- `~/.local/share/openwendy/llama.cpp/bin/llama-server`
- `~/.cache/openwendy/gguf`

That fallback exists so older consumers can keep working while migrating. It is not the preferred layout for new setups.
On this host today, the active services still resolve through those legacy compatibility roots.

## Scripts

The scripts live under `scripts/`.

- `./scripts/serve-main.sh`
  Starts one main `llama-server` process in the foreground.
- `./scripts/serve-embedding.sh`
  Starts one embedding `llama-server` process in the foreground.
- `./scripts/serve-router.sh`
  Starts one router `llama-server` process in the foreground.
- `./scripts/chat.sh`
  Connects to a currently loaded chat endpoint, lets you pick among the loaded models, and streams reasoning plus visible reply tokens in the terminal.
- `./scripts/start-stack.sh`
  Launches detached `screen` sessions for main, embedding, and optional router, then waits for health.
- `./scripts/status.sh`
  Shows detached `screen` sessions and current health endpoints.
- `./scripts/stop-stack.sh`
  Stops the detached service screens.

Benchmark helpers live under `benchmarks/`.

- `./benchmarks/sweep_profiles.sh`
  Compares launch-flag profiles for one model at a safe fixed context.
- `./benchmarks/sweep_contexts.sh`
  Climbs context for one chosen profile until VRAM headroom lands near a target.
- `./benchmarks/coding_compare.sh`
  Runs the reusable uncapped coding-quality comparison with one candidate on the GPU at a time.

## Quick Start

Start the current default stack:

```bash
./scripts/start-stack.sh
./scripts/status.sh
```

This now means:
- `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf` main on `CUDA0`
- `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf` embeddings on CPU
- no separate router service by default

This is the durable repo default stack.

Start the same stack with the full proven `8B` profile explicitly:

```bash
MAIN_MODEL=Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf \
MAIN_ALIAS=glm-4.6v \
MAIN_MMPROJ=Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf \
MAIN_THREADS=10 \
MAIN_CONTEXT=131072 \
MAIN_EXTRA_ARGS='-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup' \
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

If you want a separate router service anyway, opt in explicitly with your own smaller router model. On this 10 GB host, running a second large multimodal model beside the main `8B` service is not the recommended default:

```bash
START_ROUTER=true \
ROUTER_MODEL=/absolute/path/to/your-router-model.gguf \
./scripts/start-stack.sh
```

Stop the detached services:

```bash
./scripts/stop-stack.sh
```

Quick terminal chat tests against currently loaded chat services:

```bash
./scripts/chat.sh
CHAT_PORT=8091 ./scripts/chat.sh 'Reply with exactly OK.'
CHAT_PORT=8091 ./scripts/chat.sh -T 'Reply with exactly OK.'
```

Notes:

- In a real terminal with no explicit `CHAT_PORT` or `CHAT_MODEL`, `./scripts/chat.sh` discovers loaded chat endpoints from `CHAT_ENDPOINTS` and opens an arrow-key picker for them.
- The default discovery list is `127.0.0.1:8091,127.0.0.1:8093`; override it with `CHAT_ENDPOINTS=host1:port1,host2:port2`.
- Streamed reasoning tokens print in gray, visible reply tokens in white, and streamed tool-call deltas in cyan.
- Sampling and reasoning controls can be set per request with `--temp`, `--top-p`, `--top-k`, `--presence`, `--repeat`, and `-B` / `--thinking-budget`.
- `-T` sends `enable_thinking=false`, but on some model families that still may not yield a clean no-thinking reply.

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

## Optional boot-time GPU power cap

On headless NVIDIA hosts, a simple way to reduce peak board power is to apply a lower power limit at boot.

The repo includes a root-level system unit for that:

```bash
sudo ln -sf ~/projects/localllm/systemd/localllm-gpu-power-limit.service /etc/systemd/system/localllm-gpu-power-limit.service
printf 'GPU_POWER_LIMIT_WATTS=300\n' | sudo tee /etc/default/localllm-gpu-power-limit >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now localllm-gpu-power-limit.service
```

Verify it with:

```bash
nvidia-smi --query-gpu=power.draw,power.limit --format=csv,noheader
```

Notes:

- `nvidia-smi -pl` requires root, so this is a system unit rather than a `systemd --user` unit.
- The RTX 3080 on this host reports a supported power-limit range of `100 W` to `370 W`.
- `localllm-gpu-power-limit.service` is a `Type=oneshot` unit, so `systemctl status` showing `inactive (dead)` after `status=0/SUCCESS` is the expected healthy state.
- `nvidia-smi` may warn that persistence mode is disabled; that warning does not prevent the power limit from being applied.

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
- `GET http://127.0.0.1:8091/metrics`

OpenAI-compatible endpoints:
- `POST http://127.0.0.1:8091/v1/chat/completions`
- `POST http://127.0.0.1:8092/v1/embeddings`
- optional `POST http://127.0.0.1:8093/v1/chat/completions`
- `GET http://127.0.0.1:8091/props`

The services do not require a real API key for local use. Clients that insist on one can use any placeholder string such as `dummy` or `unused`.

When only one model is loaded on an endpoint, the local `llama.cpp` server can accept chat requests without an explicit `model` field. Many OpenAI-compatible clients still insist on sending `model` anyway, so practical client behavior may differ. If you want a shorter stable name than the GGUF filename, `llama-server` also supports `--alias`.

`GET /props` is the simplest endpoint for discovering what a live service is actually serving. It includes fields such as `model_alias`, `model_path`, modality flags, and endpoint capabilities. When a service is started with `--alias`, that alias is what downstream clients and `./scripts/chat.sh` will see.

### curl examples

Chat:

```bash
curl http://127.0.0.1:8091/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Huihui-Qwen3-VL-8B-Thinking-abliterated.Q4_K_M.gguf",
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
    "model": "Huihui-Qwen3-VL-8B-Thinking-abliterated.Q4_K_M.gguf",
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
    model="Huihui-Qwen3-VL-8B-Thinking-abliterated.Q4_K_M.gguf",
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

- main model: `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
- main alias: `glm-4.6v`
- main `mmproj`: `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
- embedding model: `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- separate router service: off by default
- router model if you opt in: set `ROUTER_MODEL` explicitly
- ports: `8091`, `8092`, `8093`
- main device defaults: `CUDA0` with `--gpu-layers auto` and `--fit on`
- embedding device defaults: `none` with `--gpu-layers 0` and no `--fit`
- script path discovery prefers the `localllm` roots above and then the legacy compatibility roots

## Current Preferred Stack

For this host, the current preferred main stack is:

- main: `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
- main alias: `glm-4.6v`
- main `mmproj`: `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
- embedding: `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- router: no separate router service by default; this host usually reuses the main endpoint when a router decision is needed

Current tuning:

- main runs on `CUDA0` with `-t 10 -c 131072 -np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup`
- no reasoning budget is set on the current main service
- embeddings run mostly on CPU with `--device none --gpu-layers 0 -t 8 -c 2048 -ub 128 -np 1 -b 256 -tb 4 -cram 0 --no-warmup -fa off`

Useful additional knobs exposed by `llama-server` and compatible with the `*_EXTRA_ARGS` hooks:

- `--threads-http N` for busy multi-client request handling
- `--cache-type-k TYPE` and `--cache-type-v TYPE` to shrink KV cache memory use
- `--cache-reuse N` and `--cache-prompt` for repeated prompt reuse patterns
- `--cont-batching` and `-np N` for concurrent serving behavior
- `--no-kv-offload` if KV offload hurts latency on your GPU/CPU mix
- `--mmproj-offload` for vision projector placement
- `--slots` and `--props` for deeper runtime introspection and live tuning
- `--jinja` and `--chat-template*` when you need to override or debug chat-template rendering
- draft/speculative decoding flags such as `--model-draft`, `--draft`, and `--spec-type`

Why the current main tuning looks like this:

- `--threads-http 6` increases the HTTP worker pool so request handling overhead is less likely to bottleneck the model server.
- `-ctk q4_0 -ctv q4_0` keeps both KV cache sides in a lighter format, which materially improved decode speed on this host without breaking the direct reasoning probes.
- `-b 2048 -ub 512 -cram 512` keeps the `8B` multimodal profile stable on this RTX 3080 while still allowing a larger-context fit than the earlier `24K` setting.
- `-rea on` keeps the server in reasoning-capable mode so the same endpoint can serve both thinking and non-thinking turns.
- `--no-warmup` removes startup warmup work and matched the direct probe profile that proved stable for this candidate.

Reasoning mode note:

- The current main service is started with `-rea on`, which makes reasoning a server-level default.
- No `--reasoning-budget` is configured on the current main service, so thinking is not artificially capped at startup.
- Generic OpenAI-style request fields such as `reasoning_effort` and `reasoning: false` were not the correct switch for this setup.
- For Qwen-style switching, the correct request knob is `chat_template_kwargs.enable_thinking`.
- On the current `Huihui-Qwen3-VL-8B-Thinking-abliterated` stack, `chat_template_kwargs: {"enable_thinking": true}` returns a visible answer plus separate `reasoning_content`.
- On the same stack, `chat_template_kwargs: {"enable_thinking": false}` is not a clean no-thinking mode: the model may still inline a `<think> ... </think>` block into `content` before the final answer.
- Any client that wants a strict no-thinking user-visible reply on this stack should be prepared to strip inline `<think>` blocks from `content` or otherwise normalize the response.
- If your client can pass arbitrary request fields through to the OpenAI-compatible server, one endpoint can support both thinking and non-thinking turns.
- Example no-thinking request body:
  `{"model":"Huihui-Qwen3-VL-8B-Thinking-abliterated.Q4_K_M.gguf","messages":[{"role":"user","content":"Reply with exactly OK."}],"chat_template_kwargs":{"enable_thinking":false}}`
- Example thinking-on request body:
  `{"model":"Huihui-Qwen3-VL-8B-Thinking-abliterated.Q4_K_M.gguf","messages":[{"role":"user","content":"Reply with exactly OK."}],"chat_template_kwargs":{"enable_thinking":true}}`

Request-shape guidance:

- `thinking_budget_tokens` is the current request-body knob for budgeting reasoning on this local `llama.cpp` endpoint, and local tests confirmed that it works. It is not the same thing as `chat_template_kwargs.enable_thinking`, and it should not be treated as a replacement for that field.
- Use `chat_template_kwargs.enable_thinking=true` when you want a reasoning turn and `chat_template_kwargs.enable_thinking=false` when you want a fast visible-answer or routing turn.
- Normal chat turns can usually keep only prior visible assistant text in history, but tool turns must preserve the actual assistant tool-call message plus the tool result message. Flattening a previous tool turn into plain assistant text throws away information the model needs.
- If a tool-enabled turn is still deciding whether a tool is needed, use `tool_choice:"auto"`. Reserve `tool_choice:"required"` for turns where routing has already decided that a tool call must happen.
- Thinking is usually disabled on tool-decision and tool-execution turns because the local finalists are more reliable when they emit a tool call or a visible answer immediately instead of burning early tokens on internal reasoning before the tool step.
- Router turns should normally set `chat_template_kwargs.enable_thinking=false` and either omit `thinking_budget_tokens` or set it to `0`; they should not spend reasoning budget on a simple route decision.
- Omitting `max_tokens` is valid on this endpoint and helped thinking-first models finish, but it shifts control to client-side timeouts and stop policies. Use that tradeoff deliberately.
- `--jinja` is already enabled by default in the local `llama.cpp` build on this host. It is useful when you need to override or debug chat-template rendering, but it is not a missing extra switch for the current finalist models while they are using their embedded templates successfully.

Recent local candidate findings:

- These findings describe the current local finalist comparison work. They do not automatically change the durable repo default stack shown above.

- Low `max_tokens` caps can make thinking-first models look much worse than they are. In local Qwen3.5 testing, capped runs often ended with `finish_reason="length"` and empty visible `content`, but uncapped reruns showed the same models could eventually complete with substantial visible answers.
- The practical issue is now better described as reasoning efficiency and handoff quality, not simple inability to finish.
- Thinking budgets are not just on or off. On local Qwen3.5 tests, the clean handoff from reasoning into visible answer depended on the budget value; too little budget could let truncated reasoning leak into the visible answer, while larger budgets could still truncate thought more cleanly before the final answer.
- Earlier second-turn tool-flow failures turned out to be a harness-format issue. Replaying the model's actual first-turn assistant tool-call message fixed second-turn tool integration for the remaining local candidates.
- On the current local comparison path, `Abhiray` and `mradermacher` Qwen3.5 variants behaved similarly enough that `Abhiray` was dropped as redundant.
- On the current shortlist, `unsloth` is the plain Qwen3.5 path, while `GLM` and `mradermacher` are the abliterated-style options. The current practical recommendation is `GLM` for the cleaner mixed-use path and `unsloth` for the stronger plain Qwen3.5 path, with `mradermacher` trailing as a verbose fallback.
- Stable aliases for the current finalists:
  - `glm-4.6v` -> `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
  - `qwen-3.5-abl` -> `Huihui-Qwen3.5-9B-abliterated-Q4_K_M.mradermacher.gguf`
  - `qwen-3.5` -> `Qwen3.5-9B-Q4_K_M.unsloth.gguf`
- When manually swapping models with `./scripts/serve-main.sh`, set `MAIN_ALIAS` to one of those names so `/props` and downstream clients see the stable alias instead of the raw GGUF filename.
- Model-maker request-parameter guidance to keep in mind:
  - `glm-4.6v`: `temperature 0.8`, `top_p 0.6`, `top_k 2`, `repeat_penalty 1.1`, and `128k` effective context or less.
  - `qwen-3.5` and `qwen-3.5-abl`: `temperature 1.0`, `top_p 0.95`, `top_k 20`, `presence_penalty 0.0`, `repeat_penalty 1.0`.
- Local tuning outcome for the two Qwen3.5 finalists on this host:
  - `qwen-3.5` was best on `-np 1 -tb 8 -b 256 -ub 128 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup`, and the closest tested `~500 MiB` idle headroom point was `-c 362496` with about `508 MiB` free.
  - `qwen-3.5-abl` was best on the same launch profile, and the closest tested `~500 MiB` idle headroom point was `-c 397312` with about `506 MiB` free.

Current temporary `GLM` test profile:

- This is an experimental live-test profile, not the durable repo default stack.
- model: `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
- alias: `glm-4.6v`
- `mmproj`: `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
- launch context: `131072`
- effective context: `131072`
- threads: `10`
- extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup`
- on this host, that profile currently leaves about `862 MiB` free VRAM at idle and keeps the `glm-4.6v` alias visible through `/props`
- local tuning lesson: for `GLM`, a safe `-c 32768` sweep was the right way to compare flags first, then raise context on the winning profile; the older `160768` launch proved that the runtime caps this model at `131072` anyway, so the live profile now launches directly at `128k`

Benchmark workflow note:

- Keep reproducible tuning logic in `benchmarks/`, not in ad hoc `/tmp` scratch scripts.
- The current helpers expect GGUF filenames and sweep settings through environment variables such as `BENCH_MODEL`, `BENCH_MMPROJ`, `BENCH_PROFILE_SPECS`, and `BENCH_CONTEXTS`.
- The same workflow that worked for `GLM` also worked for the Qwen3.5 finalists: sweep flags at `-c 32768`, keep the best profile, then climb context until idle VRAM lands near the target headroom.

Qwen3-VL handoff note:

- Treat this as a thinking-first model, not a reliably switchable hybrid.
- Prefer `chat_template_kwargs.enable_thinking=true` if you want structured `reasoning_content`.
- If you send `enable_thinking=false`, still normalize the reply by stripping any inline `<think> ... </think>` block from `message.content` before showing it to the user.
- Do not rely on the absence of `reasoning_content` alone to decide whether hidden reasoning was emitted.

Observed steady-state footprint:

- at `-c 98304` with live `-ctk q4_0 -ctv q4_0`, the model still loads cleanly with normal `auto` offload on this host and leaves about `352 MiB` free on the GPU with embeddings still active
- targeted sweeps found this to be the highest tested context that stayed inside the requested `300` to `500 MiB` VRAM headroom band and completed the tiny direct reasoning probe cleanly
- before the KV-cache retune, nearby contexts showed the old tradeoff clearly: `67584` left about `420 MiB` free at about `37.0 tok/s`, `69632` fell below the requested headroom floor at about `278 MiB` free, and `73728` switched into a slower fit regime that left more free VRAM but dropped the tiny probe to about `29.5 tok/s`
- the later KV-cache sweep found batch-size changes mostly irrelevant on this workload, while `-ctk q4_0 -ctv q4_0` was a large win: the exact-OK reasoning probe improved from about `37.4 tok/s` to about `111.3 tok/s`, and the longer agent-looping prompt improved from about `35.4 tok/s` to about `110.4 tok/s`
- the follow-up context sweep showed that `98304` is the best live ceiling on the new `q4_0/q4_0` profile: it stayed effectively as fast as `69120` at about `110.0 tok/s` on the longer reasoning prompt, while `102400` dropped to about `76.2 tok/s`, `106496` to about `59.5 tok/s`, `110592` to about `48.3 tok/s`, and `114688` to about `40.8 tok/s`
- a `131072` retry did load and answer the tiny probe on this `mmproj-Q8_0` package, but it was only about `14.9 tok/s`, so it is not the recommended live setting for this machine
- embedding GPU usage: about `214 MiB`
- embedding RAM usage: about `1.08 GiB` RSS

Preferred GGUF cache root:

- `~/.cache/localllm/gguf`

Preferred `llama-server` binary path:

- `~/.local/share/localllm/llama.cpp/bin/llama-server`

## Current Stack Files

These are the model files the current preferred stack expects under the active GGUF cache.
On this host today, that active cache root still resolves to `~/.cache/openwendy/gguf` via the compatibility fallback.

### Main / Vision

- `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
- `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
- source: https://huggingface.co/huihui-ai/Huihui-GLM-4.6V-Flash-abliterated-GGUF

### Embeddings

- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- source: https://huggingface.co/PeterAM4/Qwen3-Embedding-0.6B-GGUF
