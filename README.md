# localllm

`localllm` is a local `llama.cpp` service layer for any client that can speak OpenAI-style HTTP.

This repo now keeps durable GGUF assets under the repo-local `models/` directory instead of treating `~/.cache/openwendy/gguf` as the primary model store. Legacy fallback support still exists for older consumers, but the preferred layout on this host is:

- models: `~/projects/localllm/models`
- binary: `~/.local/share/localllm/llama.cpp/bin/llama-server`
- legacy fallback models: `~/.cache/openwendy/gguf`
- legacy fallback binary: `~/.local/share/openwendy/llama.cpp/bin/llama-server`

## Current Main Presets

The repo keeps three durable main-model presets:

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
- `glm-4.6v`
  - model: `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
  - `mmproj`: `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
  - context: `131072`
  - extra args: `-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 1792`

The active default preset in `config/localllm-main.env` is now `qwen-3.5-abl`.

## Why DeepSeek Was Removed

`DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf` was tested heavily and then removed from disk.

Measured result on this 10 GB GPU:

- `128k` technically fit, but only by spilling more layers to CPU
- large first-turn `~10k` preload timed out at `128k`, `96k`, and `88k`
- even at improved `-b 128 -ub 64`, `128k` DeepSeek still did not return a first byte within `450s`
- agentic barrage behavior stayed clean, but tool-taking was weak compared with plain Qwen

Practical conclusion: DeepSeek was not a good operational fit for this host and workload.

## Model Switching

The main user service now reads its model config from:

- `config/localllm-main.env`

Preset files live under:

- `config/presets/`

Use these helper scripts to switch models:

```bash
./scripts/load-qwen-3.5-abl.sh
./scripts/load-qwen-3.5.sh
./scripts/load-glm-4.6v.sh
./scripts/unload-main.sh
```

These scripts:

- stop the current `localllm-main.service`
- replace `config/localllm-main.env` with the chosen preset
- restart the service
- wait for `/health`

If you want the generic entry point instead:

```bash
./scripts/load-main-preset.sh qwen-3.5-abl
./scripts/load-main-preset.sh qwen-3.5
./scripts/load-main-preset.sh glm-4.6v
```

## Services

Intended runtime shape:

- main chat or chat+vision service on `8091`
- embedding service on `8092`
- optional router service on `8093`

Current local URLs:

- main base URL: `http://127.0.0.1:8091/v1`
- embedding base URL: `http://127.0.0.1:8092/v1`
- optional router base URL: `http://127.0.0.1:8093/v1`

Useful endpoints:

- `GET http://127.0.0.1:8091/health`
- `GET http://127.0.0.1:8092/health`
- `GET http://127.0.0.1:8091/props`
- `GET http://127.0.0.1:8091/metrics`
- `POST http://127.0.0.1:8091/v1/chat/completions`
- `POST http://127.0.0.1:8092/v1/embeddings`

The local service does not require a real API key. If a client insists on one, use a placeholder string such as `unused`.

## Scripts

Main runtime scripts:

- `scripts/serve-main.sh`
- `scripts/serve-embedding.sh`
- `scripts/serve-router.sh`
- `scripts/start-stack.sh`
- `scripts/stop-stack.sh`
- `scripts/status.sh`
- `scripts/chat.sh`

Preset-switching scripts:

- `scripts/load-main-preset.sh`
- `scripts/list-presets.sh`
- `scripts/current-main.sh`
- `scripts/load-qwen-3.5.sh`
- `scripts/load-qwen-3.5-abl.sh`
- `scripts/load-glm-4.6v.sh`
- `scripts/unload-main.sh`

## systemd --user

The durable main user unit now loads model-specific settings from `config/localllm-main.env`.

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

Important benchmark rule:

- for fair scratch benchmarks, stop the main user service first
- use `scripts/unload-main.sh` or `systemctl --user stop localllm-main.service`
- otherwise the auto-restarting service can contaminate fit or preload results

If `systemctl --user` complains about the bus in a shell, export:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
```

## Benchmarks

Repo-managed benchmark entry points:

- `benchmarks/sweep_profiles.sh`
  - compare launch profiles for one model at a fixed context
- `benchmarks/sweep_contexts.sh`
  - climb context until VRAM headroom reaches a target band
- `benchmarks/coding_compare.sh`
  - coding prompt comparison
  - now supports budget matrices through `THINKING_BUDGETS="uncapped 500 1000"`
  - now includes `merge_intervals` in addition to the older coding prompts
- `benchmarks/agentic_barrage.sh`
  - live-endpoint multi-turn coding-agent barrage
- `benchmarks/agentic_barrage_compare.sh`
  - scratch compare runner for the current durable three-model set
- `benchmarks/final_decision_round.sh`
  - optional mixed-scenario tie-breaker round for final model choices

## Current Findings

On this host, the most important current results are:

- `qwen-3.5`
  - best tool user in the barrage
  - strongest candidate when harness tool-taking behavior matters most
- `qwen-3.5-abl`
  - strong practical local default
  - much faster than expected on the practical large preload-follow-up test
  - still drifts more than plain `qwen-3.5` in some long planning outputs
- `glm-4.6v`
  - fastest and most stable on the practical preload-follow-up path
  - weaker than plain Qwen on sustained agent/tool workflow
  - vision VRAM is sticky after larger image workloads, so keep `--image-max-tokens 1792`

Current practical ranking on this machine:

- best tool-using agent behavior: `qwen-3.5`
- best durable default for the user right now: `qwen-3.5-abl`
- best preload/follow-up speed: `glm-4.6v`

## Vision Safety

Qwen presets:

- keep `--image-max-tokens 12288`
- this preserved useful detail while keeping comfortable VRAM headroom on the 10 GB card
- `14336` worked, but pushed plain `qwen-3.5` too close to the danger band

GLM preset:

- keep `--image-max-tokens 1792`
- larger image-token caps moved too close to OOM on this host
- GLM vision allocations can ratchet upward and stay resident until restart

Text-only note:

- large text prompts mainly spend the already reserved context/KV budget
- the sticky high-water-mark problem observed on this host came from vision, not text-only turns

## Current Model Store

Current durable GGUF files under `models/`:

- `Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf`
- `Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf`
- `Huihui-Qwen3.5-9B-abliterated-Q4_K_M.mradermacher.gguf`
- `mmproj-Huihui-Qwen3.5-9B-abliterated-Q8_0.mradermacher.gguf`
- `Qwen3.5-9B-Q4_K_M.unsloth.gguf`
- `mmproj-Qwen3.5-9B-F16.unsloth.gguf`
- `Qwen3-Embedding-0.6B-Q4_K_M-imat.gguf`
- `Qwen3.5-35B-A3B-Q4_K_M.gguf`
- `mmproj-F16-Qwen3.5-35B-A3B.gguf`

`Qwen3-Coder-30B-A3B` and DeepSeek are no longer present in the model store.
