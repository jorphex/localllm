#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <preset-name>" >&2
  exit 1
fi

preset="$1"
preset_file="${PROJECT_ROOT}/config/presets/main-${preset}.env"
active_file="${PROJECT_ROOT}/config/localllm-main.env"

if [[ ! -f "${preset_file}" ]]; then
  echo "Unknown preset: ${preset}" >&2
  exit 1
fi

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

mkdir -p "${PROJECT_ROOT}/config"
validate_main_preset_file "${preset_file}"

backup_file=""
if [[ -f "${active_file}" ]]; then
  backup_file="$(mktemp)"
  cp "${active_file}" "${backup_file}"
fi

restore_previous_preset() {
  if [[ -n "${backup_file}" && -f "${backup_file}" ]]; then
    cp "${backup_file}" "${active_file}"
    systemctl --user daemon-reload
    systemctl --user stop localllm-main.service || true
    systemctl --user start localllm-main.service || true
    wait_for_health http://127.0.0.1:8091/health 180 >/dev/null 2>&1 || true
  else
    rm -f "${active_file}"
    systemctl --user stop localllm-main.service || true
  fi
}

cleanup_backup() {
  if [[ -n "${backup_file}" && -f "${backup_file}" ]]; then
    rm -f "${backup_file}"
  fi
}

trap cleanup_backup EXIT

cp "${preset_file}" "${active_file}"

systemctl --user daemon-reload
systemctl --user stop localllm-main.service || true
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

curl -fsS http://127.0.0.1:8091/props | jq '{model_path, model_alias, default_generation_settings}'
