#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

BENCH_CONTEXTS="${BENCH_CONTEXTS:-}"
BENCH_EXTRA_ARGS="${BENCH_EXTRA_ARGS:-}"
BENCH_ALIAS="${BENCH_ALIAS:-bench-model}"
BENCH_PROMPT="${BENCH_PROMPT:-Reply with exactly OK.}"
BENCH_MAX_TOKENS="${BENCH_MAX_TOKENS:-128}"
BENCH_STOP_MAIN="${BENCH_STOP_MAIN:-true}"
BENCH_RESTORE_PRESET="${BENCH_RESTORE_PRESET:-}"
BENCH_LOAD_RESTORE="${BENCH_LOAD_RESTORE:-false}"

if [[ -z "${BENCH_CONTEXTS}" ]]; then
  echo "Set BENCH_CONTEXTS to a space-separated list of contexts" >&2
  exit 1
fi

require_benchmark_env

CURRENT_PID=""
RESTORE_DONE=0

cleanup_sweep_contexts() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  if [[ "${RESTORE_DONE}" -eq 0 ]] && truthy "${BENCH_LOAD_RESTORE}" && [[ -n "${BENCH_RESTORE_PRESET}" ]]; then
    bash "${SCRIPT_DIR}/../scripts/load-main-preset.sh" "${BENCH_RESTORE_PRESET}" >/dev/null
    RESTORE_DONE=1
  fi
}

trap cleanup_sweep_contexts EXIT

if truthy "${BENCH_STOP_MAIN}"; then
  bash "${SCRIPT_DIR}/../scripts/unload-main.sh"
fi

index=0
for context in ${BENCH_CONTEXTS}; do
  port=$((9400 + index))
  log_path="/tmp/localllm-bench-context-${context}.log"
  pid="$(start_temp_server "${port}" "${context}" "${BENCH_EXTRA_ARGS}" "${BENCH_ALIAS}" "${log_path}")"
  CURRENT_PID="${pid}"
  wait_for_server "${port}" 180
  mem="$(gpu_mem)"
  resp="$(probe_chat "${port}" "${BENCH_PROMPT}" "${BENCH_MAX_TOKENS}" true | jq -c '{predicted_per_second:(.timings.predicted_per_second // 0), completion_tokens:(.usage.completion_tokens // 0), content:(.choices[0].message.content // ""), reasoning_len:((.choices[0].message.reasoning_content // "")|length)}')"
  echo "CTX ${context} MEM ${mem} RESP ${resp}"
  stop_temp_server "${pid}"
  CURRENT_PID=""
  sleep 2
  index=$((index + 1))
done

trap - EXIT
