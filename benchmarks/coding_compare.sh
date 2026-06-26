#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
source "${SCRIPT_DIR}/config.sh"

OUT_DIR="${OUT_DIR:-/tmp/localllm-coding-compare}"
THINKING_BUDGET="${THINKING_BUDGET:-}"
THINKING_BUDGETS="${THINKING_BUDGETS:-}"
CURL_TIMEOUT="${CURL_TIMEOUT:-300}"
PROMPTS="${PROMPTS:-$(benchmark_suite_items coding_compare | tr '\n' ' ')}"
CANDIDATE_SPECS="${CANDIDATE_SPECS:-}"
CODING_STOP_MAIN="${CODING_STOP_MAIN:-true}"
CODING_RESTORE_PRESET="${CODING_RESTORE_PRESET:-}"
CODING_LOAD_RESTORE="${CODING_LOAD_RESTORE:-false}"

declare -A prompt_text
prompt_text[simple_edit]=$(cat <<'TXT'
You are editing a tiny Python helper. Return only the corrected code.

def normalize_tags(tags):
    result = []
    for tag in tags:
        tag = tag.lower()
        result.append(tag)
    return result

Requirements:
- strip leading/trailing whitespace
- skip empty items after stripping
- preserve order
TXT
)
prompt_text[retry_bug]=$(cat <<'TXT'
Find the bug and return a corrected function plus 3 short bullet explanations.

import asyncio

async def fetch_with_retry(client, url, retries=3, delay=0.5):
    for attempt in range(retries):
        try:
            return await client.get(url, timeout=5)
        except Exception:
            if attempt == retries:
                raise
            await asyncio.sleep(delay)
            delay *= 2

Assume cancellation must not be swallowed and the retry count should behave correctly.
TXT
)
prompt_text[task_runner]=$(cat <<'TXT'
Design and implement one self-contained Python file that defines a TaskRunner class with these requirements:
- accepts async callables
- runs up to N concurrently
- retries transient failures with exponential backoff
- keeps per-task status
- supports graceful cancellation
- includes a short example usage at the end
Use concise comments and practical structure. Return code only.
TXT
)
prompt_text[merge_intervals]=$(cat <<'TXT'
Return only Python code.

Write a function `merge_intervals(intervals)` that:
- accepts a list of `[start, end]` integer pairs
- merges overlaps and touching ranges
- returns ranges sorted by start
- preserves single-item ranges

Include 4 short doctest-style examples at the end.
TXT
)

if [[ -z "${CANDIDATE_SPECS}" ]]; then
  echo "Set CANDIDATE_SPECS to semicolon-separated candidate specs." >&2
  echo "Format: alias|model|mmproj|context|extra_args|temp|top_p|top_k|presence|repeat|port" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
IFS=';' read -r -a candidates <<< "${CANDIDATE_SPECS}"

CURRENT_PID=""
RESTORE_DONE=0

cleanup_coding_compare() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  if [[ "${RESTORE_DONE}" -eq 0 ]] && truthy "${CODING_LOAD_RESTORE}" && [[ -n "${CODING_RESTORE_PRESET}" ]]; then
    bash "${SCRIPT_DIR}/../scripts/load-main-preset.sh" "${CODING_RESTORE_PRESET}" >/dev/null
    RESTORE_DONE=1
  fi
}

declare -a budgets
if [[ -n "${THINKING_BUDGETS}" ]]; then
  read -r -a budgets <<< "${THINKING_BUDGETS}"
else
  budgets=("${THINKING_BUDGET}")
fi

run_candidate() {
  local alias="$1"
  local model="$2"
  local mmproj="$3"
  local context="$4"
  local extra_args="$5"
  local temp="$6"
  local top_p="$7"
  local top_k="$8"
  local presence="$9"
  local repeat_penalty="${10}"
  local port="${11}"
  local log="${OUT_DIR}/${alias}.log"

  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  require_benchmark_env
  local pid
  pid="$(start_temp_server "${port}" "${context}" "${extra_args}" "${alias}" "${log}")"
  CURRENT_PID="${pid}"
  wait_for_server "${port}" 180
  echo "MODEL ${alias} PORT ${port} READY"

  local budget prompt_name response_json budget_label request_json
  for budget in "${budgets[@]}"; do
    budget_label="${budget}"
    if [[ -z "${budget_label}" || "${budget_label}" == "uncapped" ]]; then
      budget_label="uncapped"
    fi
    for prompt_name in ${PROMPTS}; do
      request_json="$(
        jq -cn \
          --arg model "${alias}" \
          --arg prompt "${prompt_text[$prompt_name]}" \
          --argjson temp "${temp}" \
          --argjson top_p "${top_p}" \
          --argjson top_k "${top_k}" \
          --argjson presence "${presence}" \
          --argjson repeat_penalty "${repeat_penalty}" \
          --arg budget "${budget}" \
          '{
            model: $model,
            messages: [{role:"user", content:$prompt}],
            temperature: $temp,
            top_p: $top_p,
            top_k: $top_k,
            presence_penalty: $presence,
            repeat_penalty: $repeat_penalty,
            chat_template_kwargs: {enable_thinking: true},
            stream: false
          } + (if $budget == "" or $budget == "uncapped" then {} else {thinking_budget_tokens: ($budget|tonumber)} end)'
      )"
      response_json="$(
        printf '%s' "${request_json}" \
        | curl -sS --max-time "${CURL_TIMEOUT}" "http://127.0.0.1:${port}/v1/chat/completions" \
            -H 'Content-Type: application/json' \
            -d @-
      )"
      printf '%s' "${response_json}" > "${OUT_DIR}/${alias}_${prompt_name}_${budget_label}.json"
      jq -r '.choices[0].message.content // ""' "${OUT_DIR}/${alias}_${prompt_name}_${budget_label}.json" > "${OUT_DIR}/${alias}_${prompt_name}_${budget_label}.txt"
      jq -c '{alias:$alias,prompt:$prompt,budget:$budget,finish_reason:(.choices[0].finish_reason // ""),content_len:((.choices[0].message.content // "")|length),reasoning_len:((.choices[0].message.reasoning_content // "")|length),predicted_per_second:(.timings.predicted_per_second // 0)}' \
        --arg alias "${alias}" --arg prompt "${prompt_name}" --arg budget "${budget_label}" "${OUT_DIR}/${alias}_${prompt_name}_${budget_label}.json"
    done
  done

  stop_temp_server "${pid}"
  CURRENT_PID=""

  python3 "${SCRIPT_DIR}/coding_compare_score.py" "${OUT_DIR}"
  python3 "${SCRIPT_DIR}/publish_summary.py" "${OUT_DIR}" coding_compare "$(basename "${OUT_DIR}")"
}

trap cleanup_coding_compare EXIT

if truthy "${CODING_STOP_MAIN}"; then
  bash "${SCRIPT_DIR}/../scripts/unload-main.sh"
fi

for candidate in "${candidates[@]}"; do
  [[ -z "${candidate}" ]] && continue
  IFS='|' read -r alias model mmproj context extra_args temp top_p top_k presence repeat port <<< "${candidate}"
  run_candidate "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${temp}" "${top_p}" "${top_k}" "${presence}" "${repeat}" "${port}"
done