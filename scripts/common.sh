#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${LOCALLLM_LOG_DIR:-${PROJECT_ROOT}/logs}"

default_llama_server_bin() {
  local localllm_bin="${HOME}/.local/share/localllm/llama.cpp/bin/llama-server"
  local legacy_bin="${HOME}/.local/share/openwendy/llama.cpp/bin/llama-server"
  if [[ -f "${localllm_bin}" ]]; then
    printf '%s\n' "${localllm_bin}"
    return
  fi
  if [[ -f "${legacy_bin}" ]]; then
    printf '%s\n' "${legacy_bin}"
    return
  fi
  printf '%s\n' "${localllm_bin}"
}

default_model_dir() {
  local repo_models="${HOME}/projects/localllm/models"
  local localllm_models="${HOME}/.cache/localllm/gguf"
  local legacy_models="${HOME}/.cache/openwendy/gguf"
  if [[ -d "${repo_models}" ]]; then
    printf '%s\n' "${repo_models}"
    return
  fi
  if [[ -d "${localllm_models}" ]]; then
    printf '%s\n' "${localllm_models}"
    return
  fi
  if [[ -d "${legacy_models}" ]]; then
    printf '%s\n' "${legacy_models}"
    return
  fi
  printf '%s\n' "${localllm_models}"
}

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$(default_llama_server_bin)}"
MODEL_DIR="${LLAMA_CPP_MODEL_DIR:-$(default_model_dir)}"

export_llama_runtime_env() {
  local llama_bin_dir
  llama_bin_dir="$(cd -- "$(dirname -- "${LLAMA_SERVER_BIN}")" && pwd)"
  export LD_LIBRARY_PATH="${llama_bin_dir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
}

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

env_file_value() {
  local file="$1"
  local key="$2"
  grep "^${key}=" "${file}" | head -n1 | cut -d= -f2-
}

validate_main_preset_file() {
  local preset_file="$1"
  local model mmproj
  model="$(env_file_value "${preset_file}" "MAIN_MODEL")"
  mmproj="$(env_file_value "${preset_file}" "MAIN_MMPROJ")"

  if [[ -z "${model}" ]]; then
    echo "Preset missing MAIN_MODEL: ${preset_file}" >&2
    return 1
  fi
  if [[ ! -f "${MODEL_DIR}/${model}" ]]; then
    echo "Preset model missing: ${MODEL_DIR}/${model}" >&2
    return 1
  fi
  if [[ -n "${mmproj}" && ! -f "${MODEL_DIR}/${mmproj}" ]]; then
    echo "Preset mmproj missing: ${MODEL_DIR}/${mmproj}" >&2
    return 1
  fi
}

preset_file_status() {
  local preset_file="$1"
  if validate_main_preset_file "${preset_file}" >/dev/null 2>&1; then
    printf 'ok\n'
  else
    printf 'stale\n'
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
