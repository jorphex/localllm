#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

OUT_DIR="${OUT_DIR:-/tmp/localllm-coding-compare}"
THINKING_BUDGET="${THINKING_BUDGET:-1000}"
CURL_TIMEOUT="${CURL_TIMEOUT:-300}"
PROMPTS="${PROMPTS:-simple_edit retry_bug task_runner}"
CANDIDATE_SPECS="${CANDIDATE_SPECS:-}"

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

if [[ -z "${CANDIDATE_SPECS}" ]]; then
  echo "Set CANDIDATE_SPECS to semicolon-separated candidate specs." >&2
  echo "Format: alias|model|mmproj|context|extra_args|temp|top_p|top_k|presence|repeat|port" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
IFS=';' read -r -a candidates <<< "${CANDIDATE_SPECS}"

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
  trap 'stop_temp_server "${pid}"' EXIT
  wait_for_server "${port}" 180
  echo "MODEL ${alias} PORT ${port} READY"

  local prompt_name response_json
  for prompt_name in ${PROMPTS}; do
    response_json="$(
      jq -cn \
        --arg model "${alias}" \
        --arg prompt "${prompt_text[$prompt_name]}" \
        --argjson temp "${temp}" \
        --argjson top_p "${top_p}" \
        --argjson top_k "${top_k}" \
        --argjson presence "${presence}" \
        --argjson repeat_penalty "${repeat_penalty}" \
        --argjson thinking_budget "${THINKING_BUDGET}" \
        '{
          model: $model,
          messages: [{role:"user", content:$prompt}],
          temperature: $temp,
          top_p: $top_p,
          top_k: $top_k,
          presence_penalty: $presence,
          repeat_penalty: $repeat_penalty,
          thinking_budget_tokens: $thinking_budget,
          chat_template_kwargs: {enable_thinking: true},
          stream: false
        }' \
      | curl -sS --max-time "${CURL_TIMEOUT}" "http://127.0.0.1:${port}/v1/chat/completions" \
          -H 'Content-Type: application/json' \
          -d @-
    )"
    printf '%s' "${response_json}" > "${OUT_DIR}/${alias}_${prompt_name}.json"
    jq -r '.choices[0].message.content // ""' "${OUT_DIR}/${alias}_${prompt_name}.json" > "${OUT_DIR}/${alias}_${prompt_name}.txt"
    jq -c '{alias:$alias,prompt:$prompt,finish_reason:(.choices[0].finish_reason // ""),content_len:((.choices[0].message.content // "")|length),reasoning_len:((.choices[0].message.reasoning_content // "")|length),predicted_per_second:(.timings.predicted_per_second // 0)}' \
      --arg alias "${alias}" --arg prompt "${prompt_name}" "${OUT_DIR}/${alias}_${prompt_name}.json"
  done

  stop_temp_server "${pid}"
  trap - EXIT
}

for candidate in "${candidates[@]}"; do
  [[ -z "${candidate}" ]] && continue
  IFS='|' read -r alias model mmproj context extra_args temp top_p top_k presence repeat port <<< "${candidate}"
  run_candidate "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${temp}" "${top_p}" "${top_k}" "${presence}" "${repeat}" "${port}"
done
