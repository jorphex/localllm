#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

BENCH_CONTEXT="${BENCH_CONTEXT:-32768}"
BENCH_PROFILE_SPECS="${BENCH_PROFILE_SPECS:-}"
BENCH_ALIAS="${BENCH_ALIAS:-bench-model}"
BENCH_OK_PROMPT="${BENCH_OK_PROMPT:-Reply with exactly OK.}"
BENCH_DIRECT_PROMPT="${BENCH_DIRECT_PROMPT:-You are answering a Telegram chat. Briefly explain what the /props endpoint exposes and why it is useful.}"

if [[ -z "${BENCH_PROFILE_SPECS}" ]]; then
  echo "Set BENCH_PROFILE_SPECS to 'name::args;name2::args2'" >&2
  exit 1
fi

require_benchmark_env
IFS=';' read -r -a profile_specs <<< "${BENCH_PROFILE_SPECS}"

for i in "${!profile_specs[@]}"; do
  spec="${profile_specs[$i]}"
  [[ -z "${spec}" ]] && continue
  name="${spec%%::*}"
  args="${spec#*::}"
  port=$((9300 + i))
  log_path="/tmp/localllm-bench-profile-${name}.log"
  pid="$(start_temp_server "${port}" "${BENCH_CONTEXT}" "${args}" "${BENCH_ALIAS}" "${log_path}")"
  trap 'stop_temp_server "${pid}"' EXIT
  wait_for_server "${port}" 180
  mem="$(gpu_mem)"
  ok_resp="$(probe_chat "${port}" "${BENCH_OK_PROMPT}" 128 true | jq -c '{predicted_per_second:(.timings.predicted_per_second // 0), completion_tokens:(.usage.completion_tokens // 0), content:(.choices[0].message.content // ""), reasoning_len:((.choices[0].message.reasoning_content // "")|length)}')"
  direct_resp="$(probe_chat "${port}" "${BENCH_DIRECT_PROMPT}" 512 true | jq -c '{predicted_per_second:(.timings.predicted_per_second // 0), completion_tokens:(.usage.completion_tokens // 0), content_len:((.choices[0].message.content // "")|length), reasoning_len:((.choices[0].message.reasoning_content // "")|length), finish_reason:(.choices[0].finish_reason // "")}')"
  echo "PROFILE ${name} MEM ${mem} OK ${ok_resp} DIRECT ${direct_resp}"
  stop_temp_server "${pid}"
  trap - EXIT
  sleep 2
done
