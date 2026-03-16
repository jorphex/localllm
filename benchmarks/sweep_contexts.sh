#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

BENCH_CONTEXTS="${BENCH_CONTEXTS:-}"
BENCH_EXTRA_ARGS="${BENCH_EXTRA_ARGS:-}"
BENCH_ALIAS="${BENCH_ALIAS:-bench-model}"
BENCH_PROMPT="${BENCH_PROMPT:-Reply with exactly OK.}"
BENCH_MAX_TOKENS="${BENCH_MAX_TOKENS:-128}"

if [[ -z "${BENCH_CONTEXTS}" ]]; then
  echo "Set BENCH_CONTEXTS to a space-separated list of contexts" >&2
  exit 1
fi

require_benchmark_env

index=0
for context in ${BENCH_CONTEXTS}; do
  port=$((9400 + index))
  log_path="/tmp/localllm-bench-context-${context}.log"
  pid="$(start_temp_server "${port}" "${context}" "${BENCH_EXTRA_ARGS}" "${BENCH_ALIAS}" "${log_path}")"
  trap 'stop_temp_server "${pid}"' EXIT
  wait_for_server "${port}" 180
  mem="$(gpu_mem)"
  resp="$(probe_chat "${port}" "${BENCH_PROMPT}" "${BENCH_MAX_TOKENS}" true | jq -c '{predicted_per_second:(.timings.predicted_per_second // 0), completion_tokens:(.usage.completion_tokens // 0), content:(.choices[0].message.content // ""), reasoning_len:((.choices[0].message.reasoning_content // "")|length)}')"
  echo "CTX ${context} MEM ${mem} RESP ${resp}"
  stop_temp_server "${pid}"
  trap - EXIT
  sleep 2
  index=$((index + 1))
done
