#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

EMBED_HOST="${EMBED_HOST:-127.0.0.1}"
EMBED_PORT="${EMBED_PORT:-8092}"
EMBED_MODEL="${EMBED_MODEL:-Qwen3-Embedding-0.6B-Q8_0.gguf}"
EMBED_THREADS="${EMBED_THREADS:-12}"
EMBED_CONTEXT="${EMBED_CONTEXT:-8192}"
EMBED_UBATCH="${EMBED_UBATCH:-8192}"
EMBED_DEVICE="${EMBED_DEVICE:-CUDA0}"
EMBED_GPU_LAYERS="${EMBED_GPU_LAYERS:-auto}"
EMBED_FIT="${EMBED_FIT:-true}"
EMBED_EXTRA_ARGS="${EMBED_EXTRA_ARGS:-}"

EMBED_MODEL_PATH="${MODEL_DIR}/${EMBED_MODEL}"
require_file "${LLAMA_SERVER_BIN}"
require_file "${EMBED_MODEL_PATH}"

command=(
  "${LLAMA_SERVER_BIN}"
  -m "${EMBED_MODEL_PATH}"
  --embedding
  --pooling last
  --host "${EMBED_HOST}"
  --port "${EMBED_PORT}"
  -t "${EMBED_THREADS}"
  -c "${EMBED_CONTEXT}"
  -ub "${EMBED_UBATCH}"
)

append_offload_args EMBED command
append_extra_args "${EMBED_EXTRA_ARGS}" command

exec "${command[@]}"
