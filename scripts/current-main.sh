#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
active_file="${PROJECT_ROOT}/config/localllm-main.env"

if [[ -f "${active_file}" ]]; then
  echo "ACTIVE_ENV ${active_file}"
  sed -n '1,120p' "${active_file}"
else
  echo "ACTIVE_ENV missing"
fi

if curl -fsS http://127.0.0.1:8091/health >/dev/null 2>&1; then
  echo "LIVE_SERVICE ok"
  curl -fsS http://127.0.0.1:8091/props \
  | jq '{model_alias, model_path, default_generation_settings}'
else
  echo "LIVE_SERVICE down"
fi
