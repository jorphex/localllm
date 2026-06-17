#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

RERANK_HOST="${RERANK_HOST:-127.0.0.1}"
RERANK_PORT="${RERANK_PORT:-8093}"
RERANK_MODEL="${RERANK_MODEL:-embedding/Qwen3-Reranker-4B-Q4_K_M.gguf}"
RERANK_ALIAS="${RERANK_ALIAS:-qwen3-reranker-4b-q4}"
RERANK_THREADS="${RERANK_THREADS:-8}"
RERANK_CONTEXT="${RERANK_CONTEXT:-2048}"
RERANK_UBATCH="${RERANK_UBATCH:-512}"
RERANK_DEVICE="${RERANK_DEVICE:-none}"
RERANK_GPU_LAYERS="${RERANK_GPU_LAYERS:-0}"
RERANK_FIT="${RERANK_FIT:-false}"
RERANK_EXTRA_ARGS="${RERANK_EXTRA_ARGS:--np 1 -b 512 -tb 4 -cram 0 --no-warmup -fa off --threads-http 2}"

RERANK_MODEL_PATH="${MODEL_DIR}/${RERANK_MODEL}"
require_file "${LLAMA_SERVER_BIN}"
require_file "${RERANK_MODEL_PATH}"
export_llama_runtime_env

command=(
  "${LLAMA_SERVER_BIN}"
  -m "${RERANK_MODEL_PATH}"
  --embedding
  --pooling rank
  --reranking
  --host "${RERANK_HOST}"
  --port "${RERANK_PORT}"
  --alias "${RERANK_ALIAS}"
  -t "${RERANK_THREADS}"
  -c "${RERANK_CONTEXT}"
  -ub "${RERANK_UBATCH}"
)

append_offload_args RERANK command
append_extra_args "${RERANK_EXTRA_ARGS}" command

exec "${command[@]}"
