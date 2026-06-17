#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8091}"
MAIN_MODEL="${MAIN_MODEL:-qwen-3.6/Qwen3.6-27B-UD-Q6_K_XL-unsloth.gguf}"
MAIN_ALIAS="${MAIN_ALIAS:-qwen-3.6-27b-unsloth-q6}"
MAIN_MMPROJ="${MAIN_MMPROJ-qwen-3.6/Qwen3.6-27B-mmproj-F16-unsloth.gguf}"
MAIN_THREADS="${MAIN_THREADS:-10}"
MAIN_CONTEXT="${MAIN_CONTEXT:-196608}"
MAIN_DEVICE="${MAIN_DEVICE:-}"
MAIN_GPU_LAYERS="${MAIN_GPU_LAYERS:-auto}"
MAIN_FIT="${MAIN_FIT:-true}"
MAIN_CACHE_PROMPT="${MAIN_CACHE_PROMPT:-true}"
MAIN_CACHE_REUSE="${MAIN_CACHE_REUSE:-0}"
MAIN_CACHE_RAM="${MAIN_CACHE_RAM:-8192}"
MAIN_SLOT_PROMPT_SIMILARITY="${MAIN_SLOT_PROMPT_SIMILARITY:-0.10}"
MAIN_SPEC_TYPE="${MAIN_SPEC_TYPE:-}"
MAIN_SPEC_NGRAM_SIZE_N="${MAIN_SPEC_NGRAM_SIZE_N:-}"
MAIN_SPEC_NGRAM_SIZE_M="${MAIN_SPEC_NGRAM_SIZE_M:-}"
MAIN_SPEC_NGRAM_MIN_HITS="${MAIN_SPEC_NGRAM_MIN_HITS:-}"
MAIN_DRAFT_MIN="${MAIN_DRAFT_MIN:-}"
MAIN_DRAFT_MAX="${MAIN_DRAFT_MAX:-}"
MAIN_DRAFT_P_MIN="${MAIN_DRAFT_P_MIN:-}"
MAIN_EXTRA_ARGS="${MAIN_EXTRA_ARGS:--np 1 -tb 8 -b 1024 -ub 512 -fa on --threads-http 4 -ctk q8_0 -ctv q8_0 -rea on --metrics --no-warmup --no-mmap --image-max-tokens 12288 --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0.0 --presence-penalty 0.0 --repeat-penalty 1.0 --spec-default --slot-save-path /home/j/projects/localllm/state/main-slots}"

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
append_cache_args MAIN command
append_speculative_args MAIN command
append_extra_args "${MAIN_EXTRA_ARGS}" command

exec "${command[@]}"
