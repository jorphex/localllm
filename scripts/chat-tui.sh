#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CHAT_TUI_API_KEY="${LOCALLLM_CHAT_API_KEY:-stupidfatcutebutterbear}"
exec python3 "${SCRIPT_DIR}/chat_tui.py" --api-key "${CHAT_TUI_API_KEY}" "$@"
