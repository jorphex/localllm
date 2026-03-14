#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${LOCALLLM_LOG_DIR:-${PROJECT_ROOT}/logs}"

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-${HOME}/.local/share/openwendy/llama.cpp/bin/llama-server}"
MODEL_DIR="${LLAMA_CPP_MODEL_DIR:-${HOME}/.cache/openwendy/gguf}"

ensure_logs_dir() {
  mkdir -p "${LOG_DIR}"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "Missing required file: ${path}" >&2
    exit 1
  fi
}

truthy() {
  local value="${1:-}"
  case "${value,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

append_offload_args() {
  local prefix="$1"
  local -n command_ref="$2"
  local device_var="${prefix}_DEVICE"
  local gpu_layers_var="${prefix}_GPU_LAYERS"
  local fit_var="${prefix}_FIT"
  local device="${!device_var:-}"
  local gpu_layers="${!gpu_layers_var:-}"
  local fit="${!fit_var:-true}"

  if [[ -n "${device}" ]]; then
    command_ref+=(--device "${device}")
  fi
  if [[ -n "${gpu_layers}" ]]; then
    command_ref+=(--gpu-layers "${gpu_layers}")
  fi
  if truthy "${fit}"; then
    command_ref+=(--fit on)
  fi
}

append_extra_args() {
  local extra="${1:-}"
  local -n command_ref="$2"
  if [[ -z "${extra}" ]]; then
    return
  fi
  read -r -a parsed <<< "${extra}"
  command_ref+=("${parsed[@]}")
}

wait_for_health() {
  local url="$1"
  local timeout="${2:-180}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for health: ${url}" >&2
  return 1
}
