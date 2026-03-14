#!/usr/bin/env bash
set -euo pipefail

MAIN_SESSION="${MAIN_SESSION:-localllm-main}"
EMBED_SESSION="${EMBED_SESSION:-localllm-embedding}"
ROUTER_SESSION="${ROUTER_SESSION:-localllm-router}"

for session in "${ROUTER_SESSION}" "${EMBED_SESSION}" "${MAIN_SESSION}"; do
  screen -S "${session}" -X quit >/dev/null 2>&1 || true
done

screen -wipe >/dev/null 2>&1 || true
echo "localllm stack stop requested."
