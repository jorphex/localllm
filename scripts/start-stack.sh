#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

systemctl --user daemon-reload
systemctl --user start \
  localllm-main.service \
  localllm-reranker.service \
  localllm-embedding.service \
  localllm-tts.service

wait_for_health "http://127.0.0.1:8091/health" "${HEALTH_TIMEOUT}"
wait_for_health "http://127.0.0.1:8092/health" "${HEALTH_TIMEOUT}"
wait_for_health "http://127.0.0.1:8093/health" "${HEALTH_TIMEOUT}"
wait_for_health "http://127.0.0.1:8094/health" "${HEALTH_TIMEOUT}"

echo "localllm services are healthy."
