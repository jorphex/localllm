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
  - model: `qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-Q4_K_M-mradermacher.gguf`
  - `mmproj`: `qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-mmproj-Q8_0-mradermacher.gguf`
  - context: `131072`
  - extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- `qwen-3.5`
  - model: `qwen-3.5-9b/Qwen3.5-9B-Q4_K_M-unsloth.gguf`
  - `mmproj`: `qwen-3.5-9b/Qwen3.5-9B-mmproj-F16-unsloth.gguf`
  - context: `131072`
  - extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- `omnicoder-9b`
  - model: `qwen-3.5-9b/OmniCoder-9B-Q4_K_M-upstream.gguf`
  - `mmproj`: `qwen-3.5-9b/OmniCoder-9B-mmproj-Q8_0-upstream.gguf`
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

## Prompt Caching

Prompt caching is relevant on this stack, but the server and the client do different jobs:

- `llama-server` handles the actual prompt-cache reuse
- apps, bots, and harnesses decide whether requests keep a stable enough prefix for that reuse to hit

Current local policy:

- the managed main service now exposes explicit prompt-cache controls and defaults to cache-friendly behavior for real app use
- scratch benchmark servers default to `BENCH_CACHE_PROMPT=false` so replay/sim/speed comparisons do not silently inherit cache hits across requests unless a run opts in deliberately

Useful server env vars:

- `MAIN_CACHE_PROMPT=true|false`
- `MAIN_CACHE_REUSE=<tokens>`
- `MAIN_SLOT_PROMPT_SIMILARITY=<0.0-1.0>`
- `MAIN_SLOT_SAVE_PATH=<path>`
- `MAIN_SLOTS=true|false`

Scratch benchmark equivalents:

- `BENCH_CACHE_PROMPT=true|false`
- `BENCH_CACHE_REUSE=<tokens>`
- `BENCH_SLOT_PROMPT_SIMILARITY=<0.0-1.0>`
- `BENCH_SLOT_SAVE_PATH=<path>`
- `BENCH_SLOTS=true|false`

Client-side rule:

- keep system prompts, tool schemas, tool ordering, and preserved history stable unless behavior really needs them to change

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

## Temporary Chat TUI

For a lightweight terminal chat client against the currently loaded local model:

```bash
./scripts/chat-tui.sh
```

Behavior:

- full-screen terminal UI
- no client-side context trimming
- no client-side `max_tokens` cap
- default `thinking_budget_tokens` of `1000`
- streamed reasoning in gray
- streamed visible answer in white
- model line breaks preserved

Keys:

- `Enter` send
- `Ctrl-N` insert newline
- `PgUp` and `PgDn` scroll transcript
- `Ctrl-R` reset conversation
- `Ctrl-U` clear the composer
- `Ctrl-C` quit

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

- `benchmarks/run_model_eval.sh`
- `benchmarks/sweep_profiles.sh`
- `benchmarks/sweep_contexts.sh`
- `benchmarks/coding_compare.sh`
- `benchmarks/agentic_barrage.sh`
- `benchmarks/agentic_barrage_compare.sh`
- `benchmarks/final_decision_round.sh`

Recommended candidate-eval flow:

- use `benchmarks/run_model_eval.sh` as the top-level orchestrator
- pass semicolon-separated candidate specs via `MODEL_EVAL_CANDIDATE_SPECS`
- let it load one candidate, run the requested suites, unload it, and move to the next candidate
- read the top-level `run_manifest.json` and `summary.json` under `benchmarks/model_eval/results/...`

Important scoring rule:

- do not collapse the benchmark surface into one blended score
- treat `transcript_replay` and `sim_compare` as separate primary score families
- automate per-test or per-scenario scores instead:
  - replay: fixture pass status and matched-turn count
  - sim: scenario pass status, scope-clean status, and tool-error-free status
  - barrage: per-scenario request summaries, not a single ranking score

Important benchmark rule:

- stop the managed main service before scratch GPU benchmarking
- keep only one GPU-backed chat model loaded at a time
- avoid `max_tokens` caps unless the explicit goal is truncation behavior

## Current Model Store

Current durable GGUF files under `models/`:

- `embedding/Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- `qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-Q4_K_M-mradermacher.gguf`
- `qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-i1-Q6_K-mradermacher.gguf`
- `qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-mmproj-Q8_0-mradermacher.gguf`
- `qwen-3.5-9b/OmniCoder-9B-Q4_K_M-upstream.gguf`
- `qwen-3.5-9b/OmniCoder-9B-mmproj-Q8_0-upstream.gguf`
- `qwen-3.5-9b/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled-v2-Q4_K_M-jackrong.gguf`
- `qwen-3.5-9b/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled-v2-mmproj-BF16-jackrong.gguf`
- `qwen-3.5-9b/Qwen3.5-9B-Gemini-3.1-Pro-Reasoning-Distill-Q4_K_M-jackrong.gguf`
- `qwen-3.5-9b/Qwen3.5-9B-Gemini-3.1-Pro-Reasoning-Distill-mmproj-BF16-jackrong.gguf`
- `qwen-3.5-9b/Qwen3.5-9B-Q4_K_M-unsloth.gguf`
- `qwen-3.5-9b/Qwen3.5-9B-mmproj-F16-unsloth.gguf`
