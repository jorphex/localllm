#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${LOCALLLM_LOG_DIR:-${PROJECT_ROOT}/logs}"
RUNTIME_ENV_FILE="${PROJECT_ROOT}/config/localllm-runtime.env"

if [[ -f "${RUNTIME_ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${RUNTIME_ENV_FILE}"
fi

default_llama_server_bin() {
  local runtime_backend="${LOCALLLM_RUNTIME_BACKEND:-}"
  local explicit_runtime_bin="${LOCALLLM_RUNTIME_BIN:-}"
  local localllm_bin="${HOME}/.local/share/localllm/llama.cpp/bin/llama-server"
  local legacy_bin="${HOME}/.local/share/openwendy/llama.cpp/bin/llama-server"
  local hip_bin="${HOME}/.local/src/llama.cpp/build-hip-r9700-current/bin/llama-server"
  local vulkan_bin="${HOME}/.local/src/llama.cpp/build-vulkan-r9700/bin/llama-server"
  local cuda_bin="${HOME}/.local/src/llama.cpp/build-cuda/bin/llama-server"

  if [[ -n "${explicit_runtime_bin}" ]]; then
    printf '%s\n' "${explicit_runtime_bin}"
    return
  fi
  case "${runtime_backend}" in
    hip)
      printf '%s\n' "${hip_bin}"
      return
      ;;
    vulkan)
      printf '%s\n' "${vulkan_bin}"
      return
      ;;
    cuda)
      if [[ -f "${cuda_bin}" ]]; then
        printf '%s\n' "${cuda_bin}"
        return
      fi
      ;;
  esac
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
  local device="${!device_var:-${LOCALLLM_RUNTIME_DEVICE:-}}"
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

append_cache_args() {
  local prefix="$1"
  local -n command_ref="$2"
  local cache_prompt_var="${prefix}_CACHE_PROMPT"
  local cache_reuse_var="${prefix}_CACHE_REUSE"
  local cache_ram_var="${prefix}_CACHE_RAM"
  local slot_similarity_var="${prefix}_SLOT_PROMPT_SIMILARITY"
  local slot_save_path_var="${prefix}_SLOT_SAVE_PATH"
  local slots_var="${prefix}_SLOTS"
  local cache_prompt="${!cache_prompt_var:-}"
  local cache_reuse="${!cache_reuse_var:-}"
  local cache_ram="${!cache_ram_var:-}"
  local slot_similarity="${!slot_similarity_var:-}"
  local slot_save_path="${!slot_save_path_var:-}"
  local slots="${!slots_var:-}"

  if [[ -n "${cache_prompt}" ]]; then
    if truthy "${cache_prompt}"; then
      command_ref+=(--cache-prompt)
    else
      command_ref+=(--no-cache-prompt)
    fi
  fi
  if [[ -n "${cache_reuse}" ]]; then
    command_ref+=(--cache-reuse "${cache_reuse}")
  fi
  if [[ -n "${cache_ram}" ]]; then
    command_ref+=(--cache-ram "${cache_ram}")
  fi
  if [[ -n "${slot_similarity}" ]]; then
    command_ref+=(--slot-prompt-similarity "${slot_similarity}")
  fi
  if [[ -n "${slot_save_path}" ]]; then
    command_ref+=(--slot-save-path "${slot_save_path}")
  fi
  if [[ -n "${slots}" ]]; then
    if truthy "${slots}"; then
      command_ref+=(--slots)
    else
      command_ref+=(--no-slots)
    fi
  fi
}

append_speculative_args() {
  local prefix="$1"
  local -n command_ref="$2"
  local spec_type_var="${prefix}_SPEC_TYPE"
  local spec_ngram_size_n_var="${prefix}_SPEC_NGRAM_SIZE_N"
  local spec_ngram_size_m_var="${prefix}_SPEC_NGRAM_SIZE_M"
  local spec_ngram_min_hits_var="${prefix}_SPEC_NGRAM_MIN_HITS"
  local draft_min_var="${prefix}_DRAFT_MIN"
  local draft_max_var="${prefix}_DRAFT_MAX"
  local draft_p_min_var="${prefix}_DRAFT_P_MIN"
  local spec_type="${!spec_type_var:-}"
  local spec_ngram_size_n="${!spec_ngram_size_n_var:-}"
  local spec_ngram_size_m="${!spec_ngram_size_m_var:-}"
  local spec_ngram_min_hits="${!spec_ngram_min_hits_var:-}"
  local draft_min="${!draft_min_var:-}"
  local draft_max="${!draft_max_var:-}"
  local draft_p_min="${!draft_p_min_var:-}"

  if [[ -n "${spec_type}" ]]; then
    command_ref+=(--spec-type "${spec_type}")
  fi
  if [[ -n "${spec_ngram_size_n}" ]]; then
    command_ref+=(--spec-ngram-size-n "${spec_ngram_size_n}")
  fi
  if [[ -n "${spec_ngram_size_m}" ]]; then
    command_ref+=(--spec-ngram-size-m "${spec_ngram_size_m}")
  fi
  if [[ -n "${spec_ngram_min_hits}" ]]; then
    command_ref+=(--spec-ngram-min-hits "${spec_ngram_min_hits}")
  fi
  if [[ -n "${draft_min}" ]]; then
    command_ref+=(--draft-min "${draft_min}")
  fi
  if [[ -n "${draft_max}" ]]; then
    command_ref+=(--draft-max "${draft_max}")
  fi
  if [[ -n "${draft_p_min}" ]]; then
    command_ref+=(--draft-p-min "${draft_p_min}")
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
