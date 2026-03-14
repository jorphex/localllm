#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

MAIN_SESSION="${MAIN_SESSION:-localllm-main}"
EMBED_SESSION="${EMBED_SESSION:-localllm-embedding}"
ROUTER_SESSION="${ROUTER_SESSION:-localllm-router}"
START_ROUTER="${START_ROUTER:-false}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"

MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8091}"
EMBED_HOST="${EMBED_HOST:-127.0.0.1}"
EMBED_PORT="${EMBED_PORT:-8092}"
ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"
ROUTER_PORT="${ROUTER_PORT:-8093}"

ensure_logs_dir
screen -wipe >/dev/null 2>&1 || true

start_screen() {
  local session="$1"
  local script_path="$2"
  local log_path="$3"
  if screen -ls | grep -q "[.]${session}[[:space:]]"; then
    echo "Screen already running: ${session}"
    return 0
  fi
  screen -DmS "${session}" bash -lc "cd '${PROJECT_ROOT}' && '${script_path}' >> '${log_path}' 2>&1"
}

start_screen "${MAIN_SESSION}" "${PROJECT_ROOT}/scripts/serve-main.sh" "${LOG_DIR}/main.log"
start_screen "${EMBED_SESSION}" "${PROJECT_ROOT}/scripts/serve-embedding.sh" "${LOG_DIR}/embedding.log"

if truthy "${START_ROUTER}"; then
  start_screen "${ROUTER_SESSION}" "${PROJECT_ROOT}/scripts/serve-router.sh" "${LOG_DIR}/router.log"
fi

wait_for_health "http://${MAIN_HOST}:${MAIN_PORT}/health" "${HEALTH_TIMEOUT}"
wait_for_health "http://${EMBED_HOST}:${EMBED_PORT}/health" "${HEALTH_TIMEOUT}"

if truthy "${START_ROUTER}"; then
  wait_for_health "http://${ROUTER_HOST}:${ROUTER_PORT}/health" "${HEALTH_TIMEOUT}"
fi

echo "localllm stack is healthy."
