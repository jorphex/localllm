#!/usr/bin/env bash
set -euo pipefail

BENCH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${BENCH_DIR}/common.sh"

OUT_DIR="${OUT_DIR:-/tmp/localllm-agentic-compare}"
BARRAGE_BUDGETS="${BARRAGE_BUDGETS:-uncapped}"
BARRAGE_SCENARIOS="${BARRAGE_SCENARIOS:-plan_then_revise review_then_retry evidence_triage tool_restraint tool_followthrough}"
BARRAGE_TIMEOUT="${BARRAGE_TIMEOUT:-300}"
CANDIDATE_SPECS="${CANDIDATE_SPECS:-qwen36-35b-unsloth|qwen-3.6/Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf|qwen-3.6/Qwen3.6-35B-A3B-mmproj-F16-unsloth.gguf|262144|-np 1 -tb 8 -b 1024 -ub 512 -fa on --threads-http 4 -ctk q8_0 -ctv q8_0 -rea on --metrics --no-warmup --no-mmap --image-max-tokens 12288 --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0.0 --presence-penalty 0.0 --repeat-penalty 1.0 --spec-default --slot-save-path /home/j/projects/localllm/state/main-slots|9502}"
COMPARE_STOP_MAIN="${COMPARE_STOP_MAIN:-true}"
COMPARE_RESTORE_PRESET="${COMPARE_RESTORE_PRESET:-qwen-3.6-35b-a3b-unsloth-q6}"
COMPARE_LOAD_RESTORE="${COMPARE_LOAD_RESTORE:-false}"

mkdir -p "${OUT_DIR}"
IFS=';' read -r -a candidates <<< "${CANDIDATE_SPECS}"

CURRENT_PID=""
RESTORE_DONE=0

cleanup_barrage_compare() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  if [[ "${RESTORE_DONE}" -eq 0 ]] && truthy "${COMPARE_LOAD_RESTORE}" && [[ -n "${COMPARE_RESTORE_PRESET}" ]]; then
    bash "${BENCH_DIR}/../scripts/load-main-preset.sh" "${COMPARE_RESTORE_PRESET}" >/dev/null
    RESTORE_DONE=1
  fi
}

run_candidate() {
  local alias="$1"
  local model="$2"
  local mmproj="$3"
  local context="$4"
  local extra_args="$5"
  local port="$6"
  local log_path="${OUT_DIR}/${alias}.server.log"
  local candidate_out="${OUT_DIR}/${alias}"

  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  require_benchmark_env

  local pid
  pid="$(start_temp_server "${port}" "${context}" "${extra_args}" "${alias}" "${log_path}")"
  CURRENT_PID="${pid}"
  wait_for_server "${port}" 180
  echo "CANDIDATE ${alias} PORT ${port} READY"

  OUT_DIR="${candidate_out}" \
  BARRAGE_HOST="127.0.0.1" \
  BARRAGE_PORT="${port}" \
  BARRAGE_MODEL="${alias}" \
  BARRAGE_BUDGETS="${BARRAGE_BUDGETS}" \
  BARRAGE_SCENARIOS="${BARRAGE_SCENARIOS}" \
  CURL_TIMEOUT="${BARRAGE_TIMEOUT}" \
  bash "${BENCH_DIR}/agentic_barrage.sh"

  stop_temp_server "${pid}"
  CURRENT_PID=""
}

trap cleanup_barrage_compare EXIT

if truthy "${COMPARE_STOP_MAIN}"; then
  bash "${BENCH_DIR}/../scripts/unload-main.sh"
fi

for candidate in "${candidates[@]}"; do
  [[ -z "${candidate}" ]] && continue
  IFS='|' read -r alias model mmproj context extra_args port <<< "${candidate}"
  run_candidate "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${port}"
done
