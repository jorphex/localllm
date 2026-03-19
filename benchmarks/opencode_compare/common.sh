#!/usr/bin/env bash
set -euo pipefail

COMPARE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd -- "${COMPARE_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd -- "${COMPARE_DIR}/../.." && pwd)"
source "${BENCHMARK_DIR}/common.sh"

COMPARE_OUT_DIR="${COMPARE_OUT_DIR:-${PROJECT_ROOT}/benchmarks/opencode_compare/results}"
COMPARE_TIMEOUT="${COMPARE_TIMEOUT:-300}"
COMPARE_HOST="${COMPARE_HOST:-127.0.0.1}"

compare_require_tools() {
  require_file "${LLAMA_SERVER_BIN}"
  command -v jq >/dev/null 2>&1 || { echo "Missing jq" >&2; exit 1; }
  command -v curl >/dev/null 2>&1 || { echo "Missing curl" >&2; exit 1; }
  command -v nvidia-smi >/dev/null 2>&1 || { echo "Missing nvidia-smi" >&2; exit 1; }
}

compare_timestamp() {
  date -u +%Y%m%dT%H%M%SZ
}

compare_results_dir() {
  local label="${1:-run}"
  local stamp
  stamp="$(compare_timestamp)"
  printf '%s\n' "${COMPARE_OUT_DIR}/${stamp}-${label}"
}

gpu_mem_json() {
  local sample
  sample="$(nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits | head -n1)"
  jq -cn --arg sample "${sample}" '
    ($sample | split(",") | map(gsub("^ +| +$"; ""))) as $parts
    | {
        used_mib: (($parts[0] // "0") | tonumber),
        free_mib: (($parts[1] // "0") | tonumber)
      }'
}

candidate_spec_json() {
  local alias="$1"
  local model="$2"
  local mmproj="$3"
  local context="$4"
  local extra_args="$5"
  local port="$6"
  jq -cn \
    --arg alias "${alias}" \
    --arg model "${model}" \
    --arg mmproj "${mmproj}" \
    --argjson context "${context}" \
    --arg extra_args "${extra_args}" \
    --argjson port "${port}" \
    '{
      alias:$alias,
      model:$model,
      mmproj:$mmproj,
      context:$context,
      extra_args:$extra_args,
      port:$port
    }'
}

compare_start_candidate() {
  local candidate_json="$1"
  local log_path="$2"
  local alias model mmproj context extra_args port
  alias="$(jq -r '.alias' <<< "${candidate_json}")"
  model="$(jq -r '.model' <<< "${candidate_json}")"
  mmproj="$(jq -r '.mmproj' <<< "${candidate_json}")"
  context="$(jq -r '.context' <<< "${candidate_json}")"
  extra_args="$(jq -r '.extra_args' <<< "${candidate_json}")"
  port="$(jq -r '.port' <<< "${candidate_json}")"

  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  require_benchmark_env

  local pid
  pid="$(start_temp_server "${port}" "${context}" "${extra_args}" "${alias}" "${log_path}")"
  wait_for_server "${port}" 180
  printf '%s\n' "${pid}"
}

compare_stop_candidate() {
  local pid="$1"
  stop_temp_server "${pid}"
}

compare_chat() {
  local port="$1"
  local request_path="$2"
  local response_path="$3"
  local metrics_path="$4"

  curl -sS \
    --max-time "${COMPARE_TIMEOUT}" \
    --output "${response_path}" \
    --write-out '{"http_code":"%{http_code}","time_total":%{time_total},"time_starttransfer":%{time_starttransfer},"size_download":%{size_download}}\n' \
    "http://${COMPARE_HOST}:${port}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d @"${request_path}" > "${metrics_path}"
}

compare_tool_names() {
  local response_path="$1"
  jq -c '[.choices[0].message.tool_calls[]?.function.name]' "${response_path}"
}

compare_result_json() {
  local candidate_json="$1"
  local scenario="$2"
  local turn="$3"
  local request_path="$4"
  local response_path="$5"
  local metrics_path="$6"
  local gpu_before_path="$7"
  local gpu_after_path="$8"
  jq -cn \
    --argjson candidate "${candidate_json}" \
    --arg scenario "${scenario}" \
    --arg turn "${turn}" \
    --argjson request "$(cat "${request_path}")" \
    --argjson response "$(cat "${response_path}")" \
    --argjson metrics "$(cat "${metrics_path}")" \
    --argjson gpu_before "$(cat "${gpu_before_path}")" \
    --argjson gpu_after "$(cat "${gpu_after_path}")" \
    '{
      candidate:$candidate,
      scenario:$scenario,
      turn:$turn,
      metrics:{
        http_code:$metrics.http_code,
        time_total:$metrics.time_total,
        time_starttransfer:$metrics.time_starttransfer,
        size_download:$metrics.size_download,
        predicted_per_second:($response.timings.predicted_per_second // 0),
        prompt_per_second:($response.timings.prompt_per_second // 0)
      },
      gpu_before:$gpu_before,
      gpu_after:$gpu_after,
      request:{
        tools:([($request.tools[]?.function.name)]),
        tool_choice:($request.tool_choice // ""),
        message_count:(($request.messages // []) | length)
      },
      response:{
        finish_reason:($response.choices[0].finish_reason // ""),
        content:($response.choices[0].message.content // ""),
        content_len:(($response.choices[0].message.content // "") | length),
        content_preview:(($response.choices[0].message.content // "")[0:400]),
        reasoning_len:(($response.choices[0].message.reasoning_content // "") | length),
        tool_call_count:((($response.choices[0].message.tool_calls // [])) | length),
        tool_names:([($response.choices[0].message.tool_calls[]?.function.name)]),
        stop:($response.stop // false)
      }
    }'
}
