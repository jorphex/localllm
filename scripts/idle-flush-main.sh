#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

MAIN_URL="${MAIN_URL:-http://${MAIN_HOST:-127.0.0.1}:${MAIN_PORT:-8091}}"
IDLE_SECONDS="${MAIN_IDLE_FLUSH_SECONDS:-900}"
MIN_SLOT_TOKENS="${MAIN_IDLE_FLUSH_MIN_SLOT_TOKENS:-8192}"
STATE_FILE="${MAIN_IDLE_FLUSH_STATE_FILE:-${PROJECT_ROOT}/state/main-idle-flush.state}"
LOCK_FILE="${MAIN_IDLE_FLUSH_LOCK_FILE:-${PROJECT_ROOT}/state/main-idle-flush.lock}"
FLUSH_PROMPT="${MAIN_IDLE_FLUSH_PROMPT:-boop}"
FLUSH_PREDICT="${MAIN_IDLE_FLUSH_PREDICT:-1}"
CURL_MAX_TIME="${MAIN_IDLE_FLUSH_CURL_MAX_TIME:-5}"

mkdir -p "$(dirname -- "${STATE_FILE}")"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "idle flush already running"
  exit 0
fi

now_epoch() {
  date +%s
}

write_state() {
  local last_activity="$1"
  local signature="$2"
  local last_flush="${3:-0}"
  {
    printf 'last_activity=%s\n' "${last_activity}"
    printf 'signature=%q\n' "${signature}"
    printf 'last_flush=%s\n' "${last_flush}"
  } > "${STATE_FILE}.tmp"
  mv "${STATE_FILE}.tmp" "${STATE_FILE}"
}

metrics_text() {
  curl -fsS --max-time "${CURL_MAX_TIME}" "${MAIN_URL}/metrics"
}

metric_value() {
  local metrics="$1"
  local name="$2"
  awk -v name="${name}" '$1 == name { print $2; found = 1 } END { if (!found) exit 1 }' <<< "${metrics}"
}

current_signature() {
  local metrics="$1"
  local prompt_total predicted_total decode_total
  prompt_total="$(metric_value "${metrics}" "llamacpp:prompt_tokens_total")"
  predicted_total="$(metric_value "${metrics}" "llamacpp:tokens_predicted_total")"
  decode_total="$(metric_value "${metrics}" "llamacpp:n_decode_total")"
  printf '%s:%s:%s\n' "${prompt_total}" "${predicted_total}" "${decode_total}"
}

slot_json() {
  curl -fsS --max-time "${CURL_MAX_TIME}" "${MAIN_URL}/slots"
}

flush_slot() {
  local code body payload

  body="$(mktemp)"
  code="$(
    curl -sS --max-time "${CURL_MAX_TIME}" -o "${body}" -w '%{http_code}' \
      -X POST "${MAIN_URL}/slots/0?action=erase" || true
  )"
  if [[ "${code}" =~ ^2 ]]; then
    rm -f "${body}"
    echo "erased slot 0 through /slots"
    return 0
  fi

  if [[ "${code}" != "501" ]] && ! grep -qi 'not_supported' "${body}"; then
    echo "slot erase failed with HTTP ${code}: $(cat "${body}")" >&2
    rm -f "${body}"
    return 1
  fi
  rm -f "${body}"

  payload="$(
    jq -n \
      --arg prompt "${FLUSH_PROMPT}" \
      --argjson n_predict "${FLUSH_PREDICT}" \
      '{prompt: $prompt, n_predict: $n_predict, temperature: 0, cache_prompt: false, id_slot: 0, stream: false}'
  )"
  curl -fsS --max-time "${CURL_MAX_TIME}" -X POST "${MAIN_URL}/completion" \
    -H 'Content-Type: application/json' \
    -d "${payload}" >/dev/null
  echo "flushed slot 0 through one-token fallback request"
}

main() {
  local now metrics signature requests_processing slots processing_slots max_slot_tokens
  local last_activity=0 last_signature="" last_flush=0 idle_for

  now="$(now_epoch)"
  if ! metrics="$(metrics_text)"; then
    echo "main metrics unavailable; skipping idle flush check"
    exit 0
  fi
  signature="$(current_signature "${metrics}")"
  requests_processing="$(metric_value "${metrics}" "llamacpp:requests_processing")"
  if ! slots="$(slot_json)"; then
    echo "main slots unavailable; skipping idle flush check"
    exit 0
  fi
  processing_slots="$(jq '[.[] | select(.is_processing == true)] | length' <<< "${slots}")"
  max_slot_tokens="$(
    jq '[.[] | [(.n_prompt_tokens // 0), (.n_prompt_tokens_cache // 0)] | max] | max // 0' <<< "${slots}"
  )"

  if [[ -f "${STATE_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${STATE_FILE}"
    last_signature="${signature:-}"
    signature="$(current_signature "${metrics}")"
  fi

  if [[ ! -f "${STATE_FILE}" ]]; then
    write_state "${now}" "${signature}" "0"
    echo "initialized idle flush state"
    exit 0
  fi

  if [[ "${requests_processing}" != "0" || "${processing_slots}" != "0" ]]; then
    write_state "${now}" "${signature}" "${last_flush}"
    echo "main is busy; idle timer reset"
    exit 0
  fi

  if [[ "${signature}" != "${last_signature}" ]]; then
    write_state "${now}" "${signature}" "${last_flush}"
    echo "main activity changed; idle timer reset"
    exit 0
  fi

  idle_for=$((now - last_activity))
  if (( idle_for < IDLE_SECONDS )); then
    echo "main idle for ${idle_for}s; threshold is ${IDLE_SECONDS}s"
    exit 0
  fi

  if (( max_slot_tokens < MIN_SLOT_TOKENS )); then
    echo "slot is small (${max_slot_tokens} tokens); no flush needed"
    exit 0
  fi

  flush_slot
  metrics="$(metrics_text)"
  signature="$(current_signature "${metrics}")"
  write_state "${now}" "${signature}" "${now}"
}

main "$@"
