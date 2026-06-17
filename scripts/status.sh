#!/usr/bin/env bash
set -euo pipefail

check_url() {
  local label="$1"
  local url="$2"
  if curl -fsS "${url}" >/dev/null 2>&1; then
    printf 'ok   %s  %s\n' "${label}" "${url}"
  else
    printf 'bad  %s  %s\n' "${label}" "${url}"
  fi
}

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

systemctl --user list-units 'localllm*' --all --no-pager

echo
echo "Health:"
check_url "main" "http://127.0.0.1:8091/health"
check_url "embed" "http://127.0.0.1:8092/health"
check_url "rerank" "http://127.0.0.1:8093/health"
check_url "tts" "http://127.0.0.1:8094/health"
