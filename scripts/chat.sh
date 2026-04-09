#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

DEFAULT_ENDPOINTS="127.0.0.1:8091,127.0.0.1:8093"
CHAT_ENDPOINTS="${CHAT_ENDPOINTS:-${DEFAULT_ENDPOINTS}}"
CHAT_HOST="${CHAT_HOST:-127.0.0.1}"
CHAT_PORT="${CHAT_PORT:-}"
CHAT_MODEL="${CHAT_MODEL:-}"
MAX_TOKENS="${MAX_TOKENS:-512}"
CHAT_REQUEST_TIMEOUT="${CHAT_REQUEST_TIMEOUT:-120}"
ENABLE_THINKING="${ENABLE_THINKING:-true}"
SHOW_REASONING="${SHOW_REASONING:-true}"
TEMPERATURE="${TEMPERATURE:-}"
TOP_P="${TOP_P:-}"
TOP_K="${TOP_K:-}"
PRESENCE_PENALTY="${PRESENCE_PENALTY:-}"
REPEAT_PENALTY="${REPEAT_PENALTY:-}"
THINKING_BUDGET="${THINKING_BUDGET:-}"
SYSTEM_PROMPT=""
PROMPT=""

MESSAGES_JSON='[]'
SELECTED_LABEL=""
SELECTED_ENDPOINT=""
SELECTED_MODEL=""

CATALOG_LABELS=()
CATALOG_ENDPOINTS=()
CATALOG_MODELS=()

GRAY=$'\033[90m'
WHITE=$'\033[97m'
CYAN=$'\033[96m'
RESET=$'\033[0m'

usage() {
  cat <<'EOF'
Usage:
  ./scripts/chat.sh [options] ["first prompt"]
  printf 'your prompt here\n' | ./scripts/chat.sh [options]

Interactive TTY mode discovers currently loaded chat endpoints, opens an arrow-key
picker, and streams both reasoning and visible reply tokens from the selected model.

Options:
  -s, --system TEXT       optional system prompt
  -m, --max-tokens N      max completion tokens per turn (default: 512)
  --temp N                request temperature
  --top-p N               request top_p
  --top-k N               request top_k
  --presence N            request presence_penalty
  --repeat N              request repeat_penalty
  -B, --thinking-budget N send thinking_budget_tokens
  -T, --no-thinking       send enable_thinking=false
  -R, --hide-reasoning    do not print streamed reasoning tokens
  -h, --help              show this help

Interactive chat commands:
  /exit, /quit            stop chat
  /reset                  clear conversation history
EOF
}

append_message() {
  local role="$1"
  local content="$2"
  MESSAGES_JSON="$(
    jq -cn \
      --argjson messages "${MESSAGES_JSON}" \
      --arg role "${role}" \
      --arg content "${content}" \
      '$messages + [{role:$role, content:$content}]'
  )"
}

reset_messages() {
  MESSAGES_JSON='[]'
  if [[ -n "${SYSTEM_PROMPT}" ]]; then
    append_message "system" "${SYSTEM_PROMPT}"
  fi
}

add_catalog_entry() {
  CATALOG_LABELS+=("$1")
  CATALOG_ENDPOINTS+=("$2")
  CATALOG_MODELS+=("$3")
}

discover_loaded_models() {
  local endpoint raw_endpoint host port props model
  local IFS=','
  read -r -a raw_endpoint <<< "${CHAT_ENDPOINTS}"
  for endpoint in "${raw_endpoint[@]}"; do
    endpoint="${endpoint//[[:space:]]/}"
    [[ -z "${endpoint}" ]] && continue
    host="${endpoint%:*}"
    port="${endpoint##*:}"
    props="$(curl -fsS --max-time 2 "http://${host}:${port}/props" 2>/dev/null || true)"
    [[ -z "${props}" ]] && continue
    model="$(printf '%s' "${props}" | jq -r '.model_alias // empty')"
    [[ -z "${model}" ]] && continue
    add_catalog_entry "${host}:${port}  ${model}" "${host}:${port}" "${model}"
  done
}

print_menu() {
  local selected="$1"
  local i
  printf '\033[H\033[J'
  printf 'Select a loaded model with up/down arrows and Enter:\n\n'
  for i in "${!CATALOG_LABELS[@]}"; do
    if [[ "${i}" -eq "${selected}" ]]; then
      printf ' > %s\n' "${CATALOG_LABELS[$i]}"
    else
      printf '   %s\n' "${CATALOG_LABELS[$i]}"
    fi
  done
  printf '\n'
}

choose_model_interactive() {
  local selected=0
  local key
  if [[ "${#CATALOG_LABELS[@]}" -eq 0 ]]; then
    echo "No loaded chat models were discovered. Start a chat service first or set CHAT_ENDPOINTS." >&2
    exit 1
  fi
  print_menu "${selected}"
  while true; do
    IFS= read -rsn1 key
    if [[ "${key}" == $'\x1b' ]]; then
      IFS= read -rsn2 -t 0.1 key || true
      case "${key}" in
        '[A')
          if (( selected > 0 )); then
            selected=$((selected - 1))
          else
            selected=$((${#CATALOG_LABELS[@]} - 1))
          fi
          print_menu "${selected}"
          ;;
        '[B')
          if (( selected + 1 < ${#CATALOG_LABELS[@]} )); then
            selected=$((selected + 1))
          else
            selected=0
          fi
          print_menu "${selected}"
          ;;
      esac
      continue
    fi

    if [[ -z "${key}" || "${key}" == $'\n' ]]; then
      SELECTED_LABEL="${CATALOG_LABELS[$selected]}"
      SELECTED_ENDPOINT="${CATALOG_ENDPOINTS[$selected]}"
      SELECTED_MODEL="${CATALOG_MODELS[$selected]}"
      printf '\033[H\033[J'
      return 0
    fi
  done
}

resolve_model_selection() {
  local i target_endpoint

  if [[ -n "${CHAT_PORT}" ]]; then
    target_endpoint="${CHAT_HOST}:${CHAT_PORT}"
    for i in "${!CATALOG_ENDPOINTS[@]}"; do
      if [[ "${CATALOG_ENDPOINTS[$i]}" == "${target_endpoint}" ]]; then
        SELECTED_LABEL="${CATALOG_LABELS[$i]}"
        SELECTED_ENDPOINT="${CATALOG_ENDPOINTS[$i]}"
        SELECTED_MODEL="${CATALOG_MODELS[$i]}"
        return 0
      fi
    done
    echo "Requested endpoint ${target_endpoint} is not currently loaded." >&2
    exit 1
  fi

  if [[ -n "${CHAT_MODEL}" ]]; then
    for i in "${!CATALOG_MODELS[@]}"; do
      if [[ "${CATALOG_MODELS[$i]}" == "${CHAT_MODEL}" || "${CATALOG_LABELS[$i]}" == "${CHAT_MODEL}" ]]; then
        SELECTED_LABEL="${CATALOG_LABELS[$i]}"
        SELECTED_ENDPOINT="${CATALOG_ENDPOINTS[$i]}"
        SELECTED_MODEL="${CATALOG_MODELS[$i]}"
        return 0
      fi
    done
    echo "Requested model ${CHAT_MODEL} is not currently loaded." >&2
    exit 1
  fi

  if [[ "${#CATALOG_LABELS[@]}" -eq 1 ]]; then
    SELECTED_LABEL="${CATALOG_LABELS[0]}"
    SELECTED_ENDPOINT="${CATALOG_ENDPOINTS[0]}"
    SELECTED_MODEL="${CATALOG_MODELS[0]}"
    return 0
  fi

  if [[ -t 0 && -t 1 ]]; then
    choose_model_interactive
    return 0
  fi

  echo "Multiple loaded chat models were found. Set CHAT_MODEL or CHAT_PORT, or run interactively." >&2
  exit 1
}

request_completion_stream() {
  jq -n \
    --arg model "${SELECTED_MODEL}" \
    --argjson messages "${MESSAGES_JSON}" \
    --argjson max_tokens "${MAX_TOKENS}" \
    --argjson enable_thinking "$( [[ "${ENABLE_THINKING}" == "true" ]] && echo true || echo false )" \
    --arg temperature "${TEMPERATURE}" \
    --arg top_p "${TOP_P}" \
    --arg top_k "${TOP_K}" \
    --arg presence_penalty "${PRESENCE_PENALTY}" \
    --arg repeat_penalty "${REPEAT_PENALTY}" \
    --arg thinking_budget "${THINKING_BUDGET}" \
    '{
      model: $model,
      messages: $messages,
      max_tokens: $max_tokens,
      stream: true,
      chat_template_kwargs: {enable_thinking: $enable_thinking}
    }
    + (if ($temperature | length) > 0 then {temperature: ($temperature | tonumber)} else {} end)
    + (if ($top_p | length) > 0 then {top_p: ($top_p | tonumber)} else {} end)
    + (if ($top_k | length) > 0 then {top_k: ($top_k | tonumber)} else {} end)
    + (if ($presence_penalty | length) > 0 then {presence_penalty: ($presence_penalty | tonumber)} else {} end)
    + (if ($repeat_penalty | length) > 0 then {repeat_penalty: ($repeat_penalty | tonumber)} else {} end)
    + (if ($thinking_budget | length) > 0 then {thinking_budget_tokens: ($thinking_budget | tonumber)} else {} end)' \
  | curl -NfsS "http://${SELECTED_ENDPOINT}/v1/chat/completions" \
      -H 'Content-Type: application/json' \
      --max-time "${CHAT_REQUEST_TIMEOUT}" \
      -d @-
}

print_streamed_response() {
  local line data reasoning_delta content_delta tool_delta
  local assistant_content=""
  local current_color=""
  local printed_any="false"

  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    [[ "${line}" != data:* ]] && continue

    data="${line#data: }"
    if [[ "${data}" == "[DONE]" ]]; then
      break
    fi

    reasoning_delta="$(printf '%s' "${data}" | jq -r '.choices[0].delta.reasoning_content // ""' 2>/dev/null || true)"
    content_delta="$(printf '%s' "${data}" | jq -r '.choices[0].delta.content // ""' 2>/dev/null || true)"
    tool_delta="$(printf '%s' "${data}" | jq -r '
      if (.choices[0].delta.tool_calls // [] | length) > 0 then
        (.choices[0].delta.tool_calls | tostring)
      else
        ""
      end
    ' 2>/dev/null || true)"

    if [[ "${SHOW_REASONING}" == "true" && -n "${reasoning_delta}" ]]; then
      if [[ "${current_color}" != "gray" ]]; then
        printf '%s' "${GRAY}"
        current_color="gray"
      fi
      printf '%s' "${reasoning_delta}"
      printed_any="true"
    fi

    if [[ -n "${content_delta}" ]]; then
      if [[ "${current_color}" != "white" ]]; then
        if [[ "${printed_any}" == "true" ]]; then
          printf '\n'
        fi
        printf '%s' "${WHITE}"
        current_color="white"
      fi
      printf '%s' "${content_delta}"
      assistant_content+="${content_delta}"
      printed_any="true"
    fi

    if [[ -n "${tool_delta}" ]]; then
      if [[ "${current_color}" != "cyan" ]]; then
        if [[ "${printed_any}" == "true" ]]; then
          printf '\n'
        fi
        printf '%s' "${CYAN}"
        current_color="cyan"
      fi
      printf '[tool_calls] %s' "${tool_delta}"
      printed_any="true"
    fi
  done < <(request_completion_stream)

  printf '%s\n' "${RESET}"

  if [[ -n "${assistant_content}" ]]; then
    append_message "assistant" "${assistant_content}"
  fi
}

single_turn() {
  append_message "user" "${PROMPT}"
  print_streamed_response
}

interactive_loop() {
  local line

  printf 'Connected to %s\n' "${SELECTED_LABEL}"
  printf 'Type /exit to stop, /reset to clear history.\n\n'

  if [[ -n "${PROMPT}" ]]; then
    printf 'you> %s\n' "${PROMPT}"
    single_turn
    printf '\n'
  fi

  while true; do
    read -r -p 'you> ' line || break
    case "${line}" in
      /exit|/quit)
        break
        ;;
      /reset)
        reset_messages
        printf 'Conversation reset.\n\n'
        continue
        ;;
      "")
        continue
        ;;
    esac
    PROMPT="${line}"
    single_turn
    printf '\n'
  done
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
    --temp)
      TEMPERATURE="${2:-}"
      shift 2
      ;;
    --top-p)
      TOP_P="${2:-}"
      shift 2
      ;;
    --top-k)
      TOP_K="${2:-}"
      shift 2
      ;;
    --presence)
      PRESENCE_PENALTY="${2:-}"
      shift 2
      ;;
    --repeat)
      REPEAT_PENALTY="${2:-}"
      shift 2
      ;;
    -B|--thinking-budget)
      THINKING_BUDGET="${2:-}"
      shift 2
      ;;
    -T|--no-thinking)
      ENABLE_THINKING="false"
      shift
      ;;
    -R|--hide-reasoning)
      SHOW_REASONING="false"
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
elif [[ ! -t 0 ]]; then
  PROMPT="$(cat)"
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for ./scripts/chat.sh" >&2
  exit 1
fi

discover_loaded_models
resolve_model_selection
reset_messages

if [[ -t 0 && -t 1 ]]; then
  interactive_loop
else
  if [[ -z "${PROMPT}" ]]; then
    echo "Prompt required in non-interactive mode." >&2
    exit 1
  fi
  single_turn
fi
