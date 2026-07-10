#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

BENCH_CONTEXT="${BENCH_CONTEXT:-32768}"
BENCH_PROFILE_SPECS="${BENCH_PROFILE_SPECS:-}"
BENCH_ALIAS="${BENCH_ALIAS:-bench-model}"
BENCH_PP_REPEAT_COUNTS="${BENCH_PP_REPEAT_COUNTS:-64 256 1024}"
BENCH_PP_BASE_PROMPT="${BENCH_PP_BASE_PROMPT:-The quick brown fox reviews system prompts, tool schemas, and prior chat turns for latency measurement. }"
BENCH_PP_MAX_TOKENS="${BENCH_PP_MAX_TOKENS:-1}"
BENCH_PP_ENABLE_THINKING="${BENCH_PP_ENABLE_THINKING:-false}"
BENCH_PP_EXTRA_JSON="${BENCH_PP_EXTRA_JSON:-}"
BENCH_STOP_MAIN="${BENCH_STOP_MAIN:-true}"
BENCH_RESTORE_PRESET="${BENCH_RESTORE_PRESET:-}"
BENCH_LOAD_RESTORE="${BENCH_LOAD_RESTORE:-false}"

if [[ -z "${BENCH_PP_EXTRA_JSON}" ]]; then
  BENCH_PP_EXTRA_JSON='{}'
fi

if [[ -z "${BENCH_PROFILE_SPECS}" ]]; then
  echo "Set BENCH_PROFILE_SPECS to 'name::args;name2::args2'" >&2
  exit 1
fi

require_benchmark_env
IFS=';' read -r -a profile_specs <<< "${BENCH_PROFILE_SPECS}"

CURRENT_PID=""
RESTORE_DONE=0

build_pp_prompt() {
  local repeat_count="$1"
  local prompt=""
  local i
  for ((i = 0; i < repeat_count; i++)); do
    prompt+="${BENCH_PP_BASE_PROMPT}"
  done
  printf '%s' "${prompt}"
}

cleanup_sweep_pp() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  if [[ "${RESTORE_DONE}" -eq 0 ]] && truthy "${BENCH_LOAD_RESTORE}" && [[ -n "${BENCH_RESTORE_PRESET}" ]]; then
    bash "${SCRIPT_DIR}/../scripts/load-main-preset.sh" "${BENCH_RESTORE_PRESET}" >/dev/null
    RESTORE_DONE=1
  fi
}

trap cleanup_sweep_pp EXIT

if truthy "${BENCH_STOP_MAIN}"; then
  bash "${SCRIPT_DIR}/../scripts/unload-main.sh"
fi

for i in "${!profile_specs[@]}"; do
  spec="${profile_specs[$i]}"
  [[ -z "${spec}" ]] && continue
  name="${spec%%::*}"
  args="${spec#*::}"
  port=$((9350 + i))
  log_path="/tmp/localllm-bench-pp-${name}.log"
  pid="$(start_temp_server "${port}" "${BENCH_CONTEXT}" "${args}" "${BENCH_ALIAS}" "${log_path}")"
  CURRENT_PID="${pid}"
  wait_for_server "${port}" 180
  mem="$(gpu_mem)"

  for repeat_count in ${BENCH_PP_REPEAT_COUNTS}; do
    prompt="$(build_pp_prompt "${repeat_count}")"
    resp="$(probe_chat "${port}" "${prompt}" "${BENCH_PP_MAX_TOKENS}" "${BENCH_PP_ENABLE_THINKING}" "${BENCH_PP_EXTRA_JSON}" | jq -c '{
      prompt_n:(.timings.prompt_n // 0),
      cache_n:(.timings.cache_n // 0),
      prompt_per_second:(.timings.prompt_per_second // 0),
      predicted_n:(.timings.predicted_n // 0),
      predicted_per_second:(.timings.predicted_per_second // 0),
      completion_tokens:(.usage.completion_tokens // 0),
      content_len:((.choices[0].message.content // "")|length),
      reasoning_len:((.choices[0].message.reasoning_content // "")|length),
      finish_reason:(.choices[0].finish_reason // "")
    }')"
    echo "PROFILE ${name} MEM ${mem} REPEAT ${repeat_count} RESP ${resp}"
  done

  stop_temp_server "${pid}"
  CURRENT_PID=""
  sleep 2
done

if [[ "${RESTORE_DONE}" -eq 0 ]] && truthy "${BENCH_LOAD_RESTORE}" && [[ -n "${BENCH_RESTORE_PRESET}" ]]; then
  bash "${SCRIPT_DIR}/../scripts/load-main-preset.sh" "${BENCH_RESTORE_PRESET}" >/dev/null
  RESTORE_DONE=1
fi

trap - EXIT
