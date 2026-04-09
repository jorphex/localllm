#!/usr/bin/env bash
set -euo pipefail

BENCHMARK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${BENCHMARK_DIR}/.." && pwd)"
source "${PROJECT_ROOT}/scripts/common.sh"

BENCH_THREADS="${BENCH_THREADS:-10}"
BENCH_DEVICE="${BENCH_DEVICE:-}"
BENCH_GPU_LAYERS="${BENCH_GPU_LAYERS:-auto}"
BENCH_FIT="${BENCH_FIT:-true}"
BENCH_CACHE_PROMPT="${BENCH_CACHE_PROMPT:-false}"
BENCH_CACHE_REUSE="${BENCH_CACHE_REUSE:-0}"
BENCH_SLOT_PROMPT_SIMILARITY="${BENCH_SLOT_PROMPT_SIMILARITY:-0.10}"
BENCH_HOST="${BENCH_HOST:-127.0.0.1}"

benchmark_gpu_backend() {
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    printf 'nvidia\n'
    return
  fi
  if command -v rocm-smi >/dev/null 2>&1 && rocm-smi >/dev/null 2>&1; then
    printf 'rocm\n'
    return
  fi
  printf 'unknown\n'
}

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
  append_cache_args BENCH command
  append_extra_args "${extra_args}" command
  "${command[@]}" >"${log_path}" 2>&1 &
  echo $!
}

wait_for_server() {
  local port="$1"
  local timeout="${2:-120}"
  wait_for_health "http://${BENCH_HOST}:${port}/health" "${timeout}"
}

gpu_mem_json() {
  local backend
  backend="$(benchmark_gpu_backend)"
  case "${backend}" in
    nvidia)
      local sample
      sample="$(nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits | head -n1)"
      jq -cn --arg backend "${backend}" --arg sample "${sample}" '
        ($sample | split(",") | map(gsub("^ +| +$"; ""))) as $parts
        | {
            backend:$backend,
            used_mib:(($parts[0] // "0") | tonumber),
            free_mib:(($parts[1] // "0") | tonumber)
          }'
      ;;
    rocm)
      local sample
      sample="$(rocm-smi --showmeminfo vram --json 2>/dev/null | jq -c '
        to_entries
        | map(select(.key | startswith("card")))
        | first
        | .value as $card
        | {
            used_mib: (
              (
                $card["VRAM Total Used Memory (B)"]
                // $card["VRAM Total Used Memory"]
                // 0
              | tonumber
              ) / 1048576
            ),
            total_mib: (
              (
                $card["VRAM Total Memory (B)"]
                // $card["VRAM Total Memory"]
                // 0
              | tonumber
              ) / 1048576
            )
          }
      ' || true)"
      if [[ -n "${sample}" && "${sample}" != "null" ]]; then
        jq -cn --arg backend "${backend}" --argjson sample "${sample}" '
          {
            backend:$backend,
            used_mib:($sample.used_mib | floor),
            free_mib:(($sample.total_mib - $sample.used_mib) | floor)
          }'
      else
        jq -cn --arg backend "${backend}" '{backend:$backend, used_mib:null, free_mib:null}'
      fi
      ;;
    *)
      jq -cn --arg backend "${backend}" '{backend:$backend, used_mib:null, free_mib:null}'
      ;;
  esac
}

gpu_mem() {
  jq -r '[.used_mib, .free_mib] | @csv' <<< "$(gpu_mem_json)" | tr -d '"'
}

probe_chat() {
  local port="$1"
  local prompt="$2"
  local max_tokens="${3:-256}"
  local enable_thinking="${4:-true}"
  local extra_json="${5:-}"
  local prompt_file
  if [[ -z "${extra_json}" ]]; then
    extra_json='{}'
  fi
  prompt_file="$(mktemp)"
  printf '%s' "${prompt}" > "${prompt_file}"
  jq -cn \
    --rawfile prompt "${prompt_file}" \
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
  rm -f "${prompt_file}"
}

stop_temp_server() {
  local pid="$1"
  if [[ -z "${pid}" ]]; then
    return
  fi
  kill "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}
