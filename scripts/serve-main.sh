#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8091}"
MAIN_MODEL="${MAIN_MODEL:-Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf}"
MAIN_ALIAS="${MAIN_ALIAS:-glm-4.6v}"
MAIN_MMPROJ="${MAIN_MMPROJ:-Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf}"
MAIN_THREADS="${MAIN_THREADS:-10}"
MAIN_CONTEXT="${MAIN_CONTEXT:-131072}"
MAIN_DEVICE="${MAIN_DEVICE:-CUDA0}"
MAIN_GPU_LAYERS="${MAIN_GPU_LAYERS:-auto}"
MAIN_FIT="${MAIN_FIT:-true}"
MAIN_EXTRA_ARGS="${MAIN_EXTRA_ARGS:--np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup}"

MAIN_MODEL_PATH="${MODEL_DIR}/${MAIN_MODEL}"
require_file "${LLAMA_SERVER_BIN}"
require_file "${MAIN_MODEL_PATH}"
export_llama_runtime_env

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

if [[ -n "${MAIN_ALIAS}" ]]; then
  command+=(--alias "${MAIN_ALIAS}")
fi

append_offload_args MAIN command
append_extra_args "${MAIN_EXTRA_ARGS}" command

exec "${command[@]}"
