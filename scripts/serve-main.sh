#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8091}"
MAIN_MODEL="${MAIN_MODEL:-Qwen3VL-4B-Instruct-Q4_K_M.gguf}"
MAIN_MMPROJ="${MAIN_MMPROJ:-mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf}"
MAIN_THREADS="${MAIN_THREADS:-12}"
MAIN_CONTEXT="${MAIN_CONTEXT:-8192}"
MAIN_DEVICE="${MAIN_DEVICE:-CUDA0}"
MAIN_GPU_LAYERS="${MAIN_GPU_LAYERS:-auto}"
MAIN_FIT="${MAIN_FIT:-true}"
MAIN_EXTRA_ARGS="${MAIN_EXTRA_ARGS:-}"

MAIN_MODEL_PATH="${MODEL_DIR}/${MAIN_MODEL}"
require_file "${LLAMA_SERVER_BIN}"
require_file "${MAIN_MODEL_PATH}"

command=(
  "${LLAMA_SERVER_BIN}"
  -m "${MAIN_MODEL_PATH}"
  --host "${MAIN_HOST}"
  --port "${MAIN_PORT}"
  -t "${MAIN_THREADS}"
  -c "${MAIN_CONTEXT}"
)

if [[ -n "${MAIN_MMPROJ}" ]]; then
  MAIN_MMPROJ_PATH="${MODEL_DIR}/${MAIN_MMPROJ}"
  require_file "${MAIN_MMPROJ_PATH}"
  command+=(-mm "${MAIN_MMPROJ_PATH}")
fi

append_offload_args MAIN command
append_extra_args "${MAIN_EXTRA_ARGS}" command

exec "${command[@]}"
