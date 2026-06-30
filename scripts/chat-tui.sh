#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CHAT_TUI_ARGS=()
if [[ -n "${LOCALLLM_CHAT_API_KEY:-}" ]]; then
  CHAT_TUI_ARGS+=(--api-key "${LOCALLLM_CHAT_API_KEY}")
fi

exec python3 "${SCRIPT_DIR}/chat_tui.py" "${CHAT_TUI_ARGS[@]}" "$@"
