#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

MAIN_HOST="${MAIN_HOST:-127.0.0.1}"
MAIN_PORT="${MAIN_PORT:-8091}"
CHAT_MODEL="${CHAT_MODEL:-Huihui-Qwen3-VL-8B-Thinking-abliterated.Q4_K_M.gguf}"
MAX_TOKENS="${MAX_TOKENS:-512}"
ENABLE_THINKING="${ENABLE_THINKING:-true}"
SHOW_REASONING="${SHOW_REASONING:-false}"
SYSTEM_PROMPT=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/chat.sh [options] "your prompt here"
  printf 'your prompt here\n' | ./scripts/chat.sh [options]

Options:
  -s, --system TEXT       optional system prompt
  -m, --max-tokens N      max completion tokens (default: 512)
  -T, --no-thinking       send enable_thinking=false
  -r, --show-reasoning    print reasoning_content before the visible answer
  -h, --help              show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--system)
      SYSTEM_PROMPT="${2:-}"
      shift 2
      ;;
    -m|--max-tokens)
      MAX_TOKENS="${2:-}"
      shift 2
      ;;
    -T|--no-thinking)
      ENABLE_THINKING="false"
      shift
      ;;
    -r|--show-reasoning)
      SHOW_REASONING="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -gt 0 ]]; then
  PROMPT="$*"
else
  if [[ -t 0 ]]; then
    echo "Prompt required." >&2
    usage >&2
    exit 1
  fi
  PROMPT="$(cat)"
fi

if [[ -z "${PROMPT}" ]]; then
  echo "Prompt required." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for ./scripts/chat.sh" >&2
  exit 1
fi

MESSAGES_JSON="$(jq -n \
  --arg system "${SYSTEM_PROMPT}" \
  --arg prompt "${PROMPT}" '
    if $system == "" then
      [{role:"user", content:$prompt}]
    else
      [{role:"system", content:$system}, {role:"user", content:$prompt}]
    end
  ')"

RESPONSE="$(
  jq -n \
    --arg model "${CHAT_MODEL}" \
    --argjson messages "${MESSAGES_JSON}" \
    --argjson max_tokens "${MAX_TOKENS}" \
    --argjson enable_thinking "$( [[ "${ENABLE_THINKING}" == "true" ]] && echo true || echo false )" \
    '{
      model: $model,
      messages: $messages,
      max_tokens: $max_tokens,
      chat_template_kwargs: {enable_thinking: $enable_thinking}
    }' \
  | curl -fsS "http://${MAIN_HOST}:${MAIN_PORT}/v1/chat/completions" \
      -H 'Content-Type: application/json' \
      -d @-
)"

if [[ "${SHOW_REASONING}" == "true" ]]; then
  REASONING="$(printf '%s' "${RESPONSE}" | jq -r '.choices[0].message.reasoning_content // ""')"
  if [[ -n "${REASONING}" ]]; then
    printf -- '--- reasoning ---\n%s\n\n' "${REASONING}"
  fi
fi

printf '%s\n' "$(printf '%s' "${RESPONSE}" | jq -r '.choices[0].message.content // ""')"
