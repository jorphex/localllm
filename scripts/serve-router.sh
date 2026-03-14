#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"
ROUTER_PORT="${ROUTER_PORT:-8093}"
ROUTER_MODEL="${ROUTER_MODEL:-Qwen3.5-2B-Q4_K_M.lmstudio.gguf}"
ROUTER_THREADS="${ROUTER_THREADS:-12}"
ROUTER_CONTEXT="${ROUTER_CONTEXT:-4096}"
ROUTER_DEVICE="${ROUTER_DEVICE:-CUDA0}"
ROUTER_GPU_LAYERS="${ROUTER_GPU_LAYERS:-auto}"
ROUTER_FIT="${ROUTER_FIT:-true}"
ROUTER_EXTRA_ARGS="${ROUTER_EXTRA_ARGS:-}"

ROUTER_MODEL_PATH="${MODEL_DIR}/${ROUTER_MODEL}"
require_file "${LLAMA_SERVER_BIN}"
require_file "${ROUTER_MODEL_PATH}"

command=(
  "${LLAMA_SERVER_BIN}"
  -m "${ROUTER_MODEL_PATH}"
  --host "${ROUTER_HOST}"
  --port "${ROUTER_PORT}"
  -t "${ROUTER_THREADS}"
  -c "${ROUTER_CONTEXT}"
)

append_offload_args ROUTER command
append_extra_args "${ROUTER_EXTRA_ARGS}" command

exec "${command[@]}"
