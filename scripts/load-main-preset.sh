#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"
source "${SCRIPT_DIR}/gpu-safety.sh"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <preset-name>" >&2
  exit 1
fi

preset="$1"
preset_dir="${LOCALLLM_PRESET_DIR:-${PROJECT_ROOT}/config/presets}"
preset_file="${preset_dir}/main-${preset}.env"
active_file="${LOCALLLM_ACTIVE_FILE:-${PROJECT_ROOT}/config/localllm-main.env}"
safety_dir=""

if [[ ! -f "${preset_file}" ]]; then
  echo "Unknown preset: ${preset}" >&2
  exit 1
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

mkdir -p "${PROJECT_ROOT}/config"
validate_main_preset_file "${preset_file}"

target_exclusive="$(env_file_value "${preset_file}" "MAIN_EXCLUSIVE_GPU")"
target_exclusive="${target_exclusive:-false}"
target_alias="$(env_file_value "${preset_file}" "MAIN_ALIAS")"
if [[ "${target_exclusive}" != "true" && "${target_exclusive}" != "false" ]]; then
  echo "MAIN_EXCLUSIVE_GPU must be true or false: ${preset_file}" >&2
  exit 1
fi

backup_file=""
main_was_active=false
reranker_was_active=false
if [[ -f "${active_file}" ]]; then
  backup_file="$(mktemp)"
  cp "${active_file}" "${backup_file}"
fi
if systemctl --user is-active --quiet localllm-main.service; then
  main_was_active=true
fi
if systemctl --user is-active --quiet localllm-reranker.service; then
  reranker_was_active=true
fi

wait_for_service_state() {
  local service="$1"
  local expected="$2"
  local timeout="${3:-60}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    if [[ "$(systemctl --user is-active "${service}" 2>/dev/null || true)" == "${expected}" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${service} to become ${expected}" >&2
  return 1
}

set_reranker_state() {
  local should_run="$1"
  if [[ "${should_run}" == "true" ]]; then
    systemctl --user start localllm-reranker.service
    wait_for_service_state localllm-reranker.service active
    wait_for_health http://127.0.0.1:8093/health 180
  else
    systemctl --user stop localllm-reranker.service
    wait_for_service_state localllm-reranker.service inactive
  fi
}

safe_transition_wait() {
  local label="$1"
  if ! gpu_safety_stabilize "${GPU_SAFETY_CURSOR}" "${safety_dir}/${label}.log"; then
    echo "GPU safety check failed during ${label}; stopping GPU services" >&2
    systemctl --user stop localllm-main.service || true
    systemctl --user stop localllm-reranker.service || true
    return 1
  fi
}

safe_journal_scan() {
  local label="$1"
  if ! gpu_safety_scan_after_cursor "${GPU_SAFETY_CURSOR}" "${safety_dir}/${label}.log"; then
    echo "GPU safety check failed during ${label}; stopping GPU services" >&2
    systemctl --user stop localllm-main.service || true
    systemctl --user stop localllm-reranker.service || true
    return 1
  fi
}

restore_previous_preset() {
  gpu_safety_assert_pm
  safe_journal_scan pre-restore
  systemctl --user stop localllm-main.service || true
  systemctl --user stop localllm-reranker.service || true
  safe_transition_wait restore-post-stop
  if [[ -n "${backup_file}" && -f "${backup_file}" ]]; then
    cp "${backup_file}" "${active_file}"
    systemctl --user daemon-reload
    if [[ "${main_was_active}" == "true" ]]; then
      systemctl --user start localllm-main.service
      wait_for_health http://127.0.0.1:8091/health 180
    fi
  else
    rm -f "${active_file}"
  fi
  set_reranker_state "${reranker_was_active}"
  safe_transition_wait restore-complete
}

cleanup() {
  gpu_safety_cleanup
  if [[ -n "${backup_file}" && -f "${backup_file}" ]]; then
    rm -f "${backup_file}"
  fi
  if [[ -n "${safety_dir}" && -d "${safety_dir}" ]]; then
    rm -rf "${safety_dir}"
  fi
}

trap cleanup EXIT

gpu_safety_assert_pm
gpu_safety_assert_clean_boot
GPU_SAFETY_CURSOR="$(gpu_safety_capture_cursor)"
gpu_safety_start_inhibitor
safety_dir="$(mktemp -d)"

if [[ "${target_exclusive}" == "true" ]]; then
  set_reranker_state false
fi
systemctl --user stop localllm-main.service
wait_for_service_state localllm-main.service inactive
safe_transition_wait post-stop

cp "${preset_file}" "${active_file}"

if ! systemctl --user daemon-reload; then
  echo "Failed to reload service configuration for preset: ${preset}" >&2
  restore_previous_preset
  exit 1
fi
if ! systemctl --user start localllm-main.service; then
  echo "Failed to start preset: ${preset}" >&2
  restore_previous_preset
  exit 1
fi

if ! wait_for_health http://127.0.0.1:8091/health 180 >/dev/null 2>&1; then
  echo "Preset failed health check: ${preset}" >&2
  restore_previous_preset
  exit 1
fi

safe_transition_wait post-load

if [[ "${target_exclusive}" == "false" ]]; then
  reranker_needs_start=false
  if ! systemctl --user is-active --quiet localllm-reranker.service; then
    reranker_needs_start=true
  fi
  if ! set_reranker_state true; then
    echo "Reranker failed while loading preset: ${preset}" >&2
    restore_previous_preset
    exit 1
  fi
  if [[ "${reranker_needs_start}" == "true" ]]; then
    safe_transition_wait post-reranker-load
  fi
fi

safe_journal_scan complete

if ! props="$(curl -fsS http://127.0.0.1:8091/props)"; then
  echo "Could not read properties for loaded preset: ${preset}" >&2
  restore_previous_preset
  exit 1
fi
if ! actual_alias="$(jq -er '.model_alias' <<< "${props}")"; then
  echo "Loaded preset returned invalid properties: ${preset}" >&2
  restore_previous_preset
  exit 1
fi
if [[ -n "${target_alias}" && "${actual_alias}" != "${target_alias}" ]]; then
  echo "Loaded main alias does not match preset: expected ${target_alias}, got ${actual_alias:-<empty>}" >&2
  restore_previous_preset
  exit 1
fi
jq '{model_path, model_alias, default_generation_settings}' <<< "${props}"
