#!/usr/bin/env bash
set -euo pipefail

SIM_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd -- "${SIM_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd -- "${SIM_DIR}/../.." && pwd)"
source "${BENCHMARK_DIR}/common.sh"

SIM_LABEL="${SIM_LABEL:-sim-qwen-vs-omnicoder}"
SIM_RESULTS_DIR="${SIM_RESULTS_DIR:-${SIM_DIR}/results/$(date -u +%Y%m%dT%H%M%SZ)-${SIM_LABEL}}"
SIM_SCENARIOS="${SIM_SCENARIOS:-retry_bugfix queue_bugfix retry_review_feedback session_store_exploration}"
SIM_CANDIDATES="${SIM_CANDIDATES:-qwen-3.5-abl omnicoder-9b}"
SIM_RESTORE_PRESET="${SIM_RESTORE_PRESET:-qwen-3.5-abl}"

DEFAULT_EXTRA_ARGS="-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288"
DEFAULT_CONTEXT=131072

mkdir -p "${SIM_RESULTS_DIR}"
export_llama_runtime_env

candidate_json() {
  local alias="$1"
  local model="$2"
  local mmproj="$3"
  local port="$4"
  jq -cn \
    --arg alias "${alias}" \
    --arg model "${model}" \
    --arg mmproj "${mmproj}" \
    --argjson context "${DEFAULT_CONTEXT}" \
    --arg extra_args "${DEFAULT_EXTRA_ARGS}" \
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

QWEN_SPEC="${QWEN_SPEC:-$(candidate_json "qwen-3.5-abl" "Huihui-Qwen3.5-9B-abliterated-Q4_K_M.mradermacher.gguf" "mmproj-Huihui-Qwen3.5-9B-abliterated-Q8_0.mradermacher.gguf" 9521)}"
OMNICODER_SPEC="${OMNICODER_SPEC:-$(candidate_json "omnicoder-9b" "OmniCoder-9B.Q4_K_M.gguf" "OmniCoder-9B.mmproj-Q8_0.gguf" 9522)}"
NEMOTRON_SPEC="${NEMOTRON_SPEC:-$(candidate_json "nemotron-30b" "Nemotron-3-Nano-30B-A3B-Q4_K_M.gguf" "" 9523)}"

restore_main() {
  bash "${PROJECT_ROOT}/scripts/load-main-preset.sh" "${SIM_RESTORE_PRESET}" >/dev/null
}

run_candidate() {
  local spec="$1"
  local alias model mmproj context extra_args port log_path candidate_dir pid scenario
  alias="$(jq -r '.alias' <<< "${spec}")"
  model="$(jq -r '.model' <<< "${spec}")"
  mmproj="$(jq -r '.mmproj' <<< "${spec}")"
  context="$(jq -r '.context' <<< "${spec}")"
  extra_args="$(jq -r '.extra_args' <<< "${spec}")"
  port="$(jq -r '.port' <<< "${spec}")"
  log_path="${SIM_RESULTS_DIR}/${alias}.server.log"
  candidate_dir="${SIM_RESULTS_DIR}/${alias}"
  mkdir -p "${candidate_dir}"

  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  require_benchmark_env

  pid="$(start_temp_server "${port}" "${context}" "${extra_args}" "${alias}" "${log_path}")"
  trap "stop_temp_server '${pid}'; restore_main" EXIT
  wait_for_server "${port}" 180

  for scenario in ${SIM_SCENARIOS}; do
    python3 "${SIM_DIR}/run_agentic_sim.py" \
      --base-url "http://127.0.0.1:${port}" \
      --model "${alias}" \
      --scenario "${scenario}" \
      --fixture-root "${SIM_DIR}/fixture_repo" \
      --out-dir "${candidate_dir}/${scenario}"
  done

  stop_temp_server "${pid}"
  trap "restore_main" EXIT
}

bash "${PROJECT_ROOT}/scripts/unload-main.sh"

for candidate in ${SIM_CANDIDATES}; do
  case "${candidate}" in
    qwen-3.5-abl) run_candidate "${QWEN_SPEC}" ;;
    omnicoder-9b) run_candidate "${OMNICODER_SPEC}" ;;
    nemotron-30b) run_candidate "${NEMOTRON_SPEC}" ;;
    *)
      echo "Unknown candidate: ${candidate}" >&2
      exit 1
      ;;
  esac
done

restore_main
trap - EXIT
printf 'SIM_RESULTS_DIR %s\n' "${SIM_RESULTS_DIR}"
