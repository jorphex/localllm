#!/usr/bin/env bash
set -euo pipefail

MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8091}"
EMBED_HOST="${EMBED_HOST:-127.0.0.1}"
EMBED_PORT="${EMBED_PORT:-8092}"
ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"
ROUTER_PORT="${ROUTER_PORT:-8093}"
START_ROUTER="${START_ROUTER:-false}"

echo "Screens:"
screen -wipe >/dev/null 2>&1 || true
screen -ls || true

echo
echo "Health:"
for url in "http://${MAIN_HOST}:${MAIN_PORT}/health" "http://${EMBED_HOST}:${EMBED_PORT}/health"; do
  if curl -fsS "${url}" >/dev/null 2>&1; then
    echo "ok  ${url}"
  else
    echo "bad ${url}"
  fi
done

if [[ "${START_ROUTER,,}" =~ ^(1|true|yes|on)$ ]]; then
  url="http://${ROUTER_HOST}:${ROUTER_PORT}/health"
  if curl -fsS "${url}" >/dev/null 2>&1; then
    echo "ok  ${url}"
  else
    echo "bad ${url}"
  fi
fi
