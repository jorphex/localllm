# localllm

`localllm` is a local `llama.cpp` service layer for OpenAI-style clients.

## Current Host State

Current runtime layout on this host:

- models: `~/projects/localllm/models`
- source checkout: `~/.local/src/llama.cpp`
- runtime binary: `~/.local/share/localllm/llama.cpp/bin/llama-server`
- PATH shim: `~/.local/bin/llama-server`

The old `~/.local/share/openwendy/llama.cpp` runtime path is no longer used on this host.

## Current Main Presets

Retained durable main-model presets:

- `qwen-3.5-abl`
  - model: `Huihui-Qwen3.5-9B-abliterated-Q4_K_M.mradermacher.gguf`
  - `mmproj`: `mmproj-Huihui-Qwen3.5-9B-abliterated-Q8_0.mradermacher.gguf`
  - context: `131072`
  - extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- `qwen-3.5`
  - model: `Qwen3.5-9B-Q4_K_M.unsloth.gguf`
  - `mmproj`: `mmproj-Qwen3.5-9B-F16.unsloth.gguf`
  - context: `131072`
  - extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- `omnicoder-9b`
  - model: `OmniCoder-9B.Q4_K_M.gguf`
  - `mmproj`: `OmniCoder-9B.mmproj-Q8_0.gguf`
  - context: `131072`
  - extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`

Current default baseline:

- `qwen-3.5-abl`

Any new candidate should beat this baseline in real client behavior, not just synthetic fit or speed.

## Recommended Qwen 3.5 Request Shape

Recommended defaults for Qwen 3.5 family requests on this host:

- do not set `max_tokens` by default for viability comparisons or real agent tests
- set `chat_template_kwargs.enable_thinking` explicitly instead of relying on template defaults
- prefer uncapped runs for natural behavior
- if a controlled reasoning cap is needed, use `thinking_budget_tokens` explicitly and conservatively
- keep `tool_choice:"auto"` unless the router has already decided a tool must be called
- preserve assistant `tool_calls` and tool messages exactly in follow-up turns

Useful starting request body for thinking-enabled turns:

```json
{
  "model": "qwen-3.5-abl",
  "messages": [
    {
      "role": "system",
      "content": "You are Codex, a coding agent. Workflow: plan -> implement -> check -> fix -> verify -> review."
    },
    {
      "role": "user",
      "content": "..."
    }
  ],
  "temperature": 0.2,
  "top_p": 0.95,
  "top_k": 20,
  "repeat_penalty": 1.05,
  "chat_template_kwargs": {
    "enable_thinking": true
  },
  "stream": false
}
```

Useful starting request body for tool-sensitive or answer-first turns:

```json
{
  "model": "qwen-3.5-abl",
  "messages": [
    {
      "role": "system",
      "content": "You are Codex, a coding agent. Use tools when needed and keep the visible answer concrete."
    },
    {
      "role": "user",
      "content": "..."
    }
  ],
  "tool_choice": "auto",
  "chat_template_kwargs": {
    "enable_thinking": true
  },
  "stream": false
}
```

## Model Switching

The main user service reads model config from:

- `config/localllm-main.env`

Preset files live under:

- `config/presets/`

Generic preset switching:

```bash
./scripts/load-main-preset.sh qwen-3.5-abl
./scripts/load-main-preset.sh qwen-3.5
./scripts/load-main-preset.sh omnicoder-9b
```

Inspection helpers:

```bash
./scripts/current-main.sh
./scripts/list-presets.sh
```

## Services

Runtime shape:

- main service on `8091`
- embedding service on `8092`

Useful endpoints:

- `GET http://127.0.0.1:8091/health`
- `GET http://127.0.0.1:8092/health`
- `GET http://127.0.0.1:8091/props`
- `GET http://127.0.0.1:8091/metrics`
- `POST http://127.0.0.1:8091/v1/chat/completions`
- `POST http://127.0.0.1:8092/v1/embeddings`

If a shell cannot see the user bus:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
```

## Benchmarks

Current repo-managed benchmark entry points:

- `benchmarks/sweep_profiles.sh`
- `benchmarks/sweep_contexts.sh`
- `benchmarks/coding_compare.sh`
- `benchmarks/agentic_barrage.sh`
- `benchmarks/agentic_barrage_compare.sh`
- `benchmarks/final_decision_round.sh`

Important benchmark rule:

- stop the managed main service before scratch GPU benchmarking
- keep only one GPU-backed chat model loaded at a time
- avoid `max_tokens` caps unless the explicit goal is truncation behavior

## Current Model Store

Current durable GGUF files under `models/`:

- `Huihui-Qwen3.5-9B-abliterated-Q4_K_M.mradermacher.gguf`
- `mmproj-Huihui-Qwen3.5-9B-abliterated-Q8_0.mradermacher.gguf`
- `OmniCoder-9B.Q4_K_M.gguf`
- `OmniCoder-9B.mmproj-Q8_0.gguf`
- `Qwen3.5-9B-Q4_K_M.unsloth.gguf`
- `mmproj-Qwen3.5-9B-F16.unsloth.gguf`
- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
