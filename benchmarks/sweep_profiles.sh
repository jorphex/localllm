#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

BENCH_CONTEXT="${BENCH_CONTEXT:-32768}"
BENCH_PROFILE_SPECS="${BENCH_PROFILE_SPECS:-}"
BENCH_ALIAS="${BENCH_ALIAS:-bench-model}"
BENCH_OK_PROMPT="${BENCH_OK_PROMPT:-Reply with exactly OK.}"
BENCH_DIRECT_PROMPT="${BENCH_DIRECT_PROMPT:-You are answering a Telegram chat. Briefly explain what the /props endpoint exposes and why it is useful.}"
BENCH_STOP_MAIN="${BENCH_STOP_MAIN:-true}"
BENCH_RESTORE_PRESET="${BENCH_RESTORE_PRESET:-}"
BENCH_LOAD_RESTORE="${BENCH_LOAD_RESTORE:-false}"

if [[ -z "${BENCH_PROFILE_SPECS}" ]]; then
  echo "Set BENCH_PROFILE_SPECS to 'name::args;name2::args2'" >&2
  exit 1
fi

require_benchmark_env
IFS=';' read -r -a profile_specs <<< "${BENCH_PROFILE_SPECS}"

CURRENT_PID=""
RESTORE_DONE=0

cleanup_sweep_profiles() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  if [[ "${RESTORE_DONE}" -eq 0 ]] && truthy "${BENCH_LOAD_RESTORE}" && [[ -n "${BENCH_RESTORE_PRESET}" ]]; then
    bash "${SCRIPT_DIR}/../scripts/load-main-preset.sh" "${BENCH_RESTORE_PRESET}" >/dev/null
    RESTORE_DONE=1
  fi
}

trap cleanup_sweep_profiles EXIT

if truthy "${BENCH_STOP_MAIN}"; then
  bash "${SCRIPT_DIR}/../scripts/unload-main.sh"
fi

for i in "${!profile_specs[@]}"; do
  spec="${profile_specs[$i]}"
  [[ -z "${spec}" ]] && continue
  name="${spec%%::*}"
  args="${spec#*::}"
  port=$((9300 + i))
  log_path="/tmp/localllm-bench-profile-${name}.log"
  pid="$(start_temp_server "${port}" "${BENCH_CONTEXT}" "${args}" "${BENCH_ALIAS}" "${log_path}")"
  CURRENT_PID="${pid}"
  wait_for_server "${port}" 180
  mem="$(gpu_mem)"
  ok_resp="$(probe_chat "${port}" "${BENCH_OK_PROMPT}" 128 true | jq -c '{predicted_per_second:(.timings.predicted_per_second // 0), completion_tokens:(.usage.completion_tokens // 0), content:(.choices[0].message.content // ""), reasoning_len:((.choices[0].message.reasoning_content // "")|length)}')"
  direct_resp="$(probe_chat "${port}" "${BENCH_DIRECT_PROMPT}" 512 true | jq -c '{predicted_per_second:(.timings.predicted_per_second // 0), completion_tokens:(.usage.completion_tokens // 0), content_len:((.choices[0].message.content // "")|length), reasoning_len:((.choices[0].message.reasoning_content // "")|length), finish_reason:(.choices[0].finish_reason // "")}')"
  echo "PROFILE ${name} MEM ${mem} OK ${ok_resp} DIRECT ${direct_resp}"
  stop_temp_server "${pid}"
  CURRENT_PID=""
  sleep 2
done

trap - EXIT
