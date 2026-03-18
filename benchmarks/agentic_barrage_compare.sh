#!/usr/bin/env bash
set -euo pipefail

BENCH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${BENCH_DIR}/common.sh"

OUT_DIR="${OUT_DIR:-/tmp/localllm-agentic-compare}"
BARRAGE_BUDGETS="${BARRAGE_BUDGETS:-uncapped 500 1000}"
BARRAGE_SCENARIOS="${BARRAGE_SCENARIOS:-plan_then_revise review_then_retry evidence_triage tool_restraint tool_followthrough}"
BARRAGE_TIMEOUT="${BARRAGE_TIMEOUT:-300}"
CANDIDATE_SPECS="${CANDIDATE_SPECS:-qwen-3.5|Qwen3.5-9B-Q4_K_M.unsloth.gguf|mmproj-Qwen3.5-9B-F16.unsloth.gguf|131072|-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288|9502;qwen-3.5-abl|Huihui-Qwen3.5-9B-abliterated-Q4_K_M.mradermacher.gguf|mmproj-Huihui-Qwen3.5-9B-abliterated-Q8_0.mradermacher.gguf|131072|-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288|9503;glm-4.6v|Huihui-GLM-4.6V-Flash-abliterated-Q4_K_M.gguf|Huihui-GLM-4.6V-Flash-abliterated-mmproj-f16.gguf|131072|-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 1792|9504}"

mkdir -p "${OUT_DIR}"
IFS=';' read -r -a candidates <<< "${CANDIDATE_SPECS}"

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
  trap "stop_temp_server '${pid}'" EXIT
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
  trap - EXIT
}

for candidate in "${candidates[@]}"; do
  [[ -z "${candidate}" ]] && continue
  IFS='|' read -r alias model mmproj context extra_args port <<< "${candidate}"
  run_candidate "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${port}"
done
