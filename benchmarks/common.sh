#!/usr/bin/env bash
set -euo pipefail

BENCHMARK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${BENCHMARK_DIR}/.." && pwd)"
source "${PROJECT_ROOT}/scripts/common.sh"

BENCH_THREADS="${BENCH_THREADS:-10}"
BENCH_DEVICE="${BENCH_DEVICE:-CUDA0}"
BENCH_GPU_LAYERS="${BENCH_GPU_LAYERS:-auto}"
BENCH_FIT="${BENCH_FIT:-true}"
BENCH_HOST="${BENCH_HOST:-127.0.0.1}"

require_benchmark_env() {
  : "${BENCH_MODEL:?Set BENCH_MODEL to a GGUF filename}"
  local model_path="${MODEL_DIR}/${BENCH_MODEL}"
  require_file "${LLAMA_SERVER_BIN}"
  require_file "${model_path}"
  if [[ -n "${BENCH_MMPROJ:-}" ]]; then
    require_file "${MODEL_DIR}/${BENCH_MMPROJ}"
  fi
  export_llama_runtime_env
}

start_temp_server() {
  local port="$1"
  local context="$2"
  local extra_args="$3"
  local alias="${4:-}"
  local log_path="${5:-/tmp/localllm-bench-${port}.log}"
  local model_path="${MODEL_DIR}/${BENCH_MODEL}"
  local -a command=(
    "${LLAMA_SERVER_BIN}"
    -m "${model_path}"
    --host "${BENCH_HOST}"
    --port "${port}"
    -t "${BENCH_THREADS}"
    -c "${context}"
  )

  if [[ -n "${BENCH_MMPROJ:-}" ]]; then
    command+=(-mm "${MODEL_DIR}/${BENCH_MMPROJ}")
  fi
  if [[ -n "${alias}" ]]; then
    command+=(--alias "${alias}")
  fi
  if [[ -n "${BENCH_DEVICE}" ]]; then
    command+=(--device "${BENCH_DEVICE}")
  fi
  if [[ -n "${BENCH_GPU_LAYERS}" ]]; then
    command+=(--gpu-layers "${BENCH_GPU_LAYERS}")
  fi
  if truthy "${BENCH_FIT}"; then
    command+=(--fit on)
  fi
  append_extra_args "${extra_args}" command
  "${command[@]}" >"${log_path}" 2>&1 &
  echo $!
}

wait_for_server() {
  local port="$1"
  local timeout="${2:-120}"
  wait_for_health "http://${BENCH_HOST}:${port}/health" "${timeout}"
}

gpu_mem() {
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader | head -n1
}

probe_chat() {
  local port="$1"
  local prompt="$2"
  local max_tokens="${3:-256}"
  local enable_thinking="${4:-true}"
  local extra_json="${5:-{}}"
  jq -cn \
    --arg prompt "${prompt}" \
    --argjson max_tokens "${max_tokens}" \
    --argjson enable_thinking "$( [[ "${enable_thinking}" == "true" ]] && echo true || echo false )" \
    --argjson extra "${extra_json}" \
    '{
      messages: [{role:"user", content:$prompt}],
      max_tokens: $max_tokens,
      chat_template_kwargs: {enable_thinking: $enable_thinking}
    } + $extra' \
  | curl -sS "http://${BENCH_HOST}:${port}/v1/chat/completions" \
      -H 'Content-Type: application/json' \
      -d @-
}

stop_temp_server() {
  local pid="$1"
  kill "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}
