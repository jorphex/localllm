#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

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
cp "${preset_file}" "${active_file}"

systemctl --user daemon-reload
systemctl --user stop localllm-main.service || true
systemctl --user start localllm-main.service

for _ in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:8091/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:8091/health >/dev/null
curl -fsS http://127.0.0.1:8091/props | jq '{model_path, model_alias, default_generation_settings}'
