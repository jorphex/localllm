#!/usr/bin/env bash
set -euo pipefail

COMPARE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${COMPARE_DIR}/common.sh"
source "${COMPARE_DIR}/scenarios.sh"

COMPARE_LABEL="${COMPARE_LABEL:-qwen-vs-gemini}"
COMPARE_RESULTS_DIR="${COMPARE_RESULTS_DIR:-$(compare_results_dir "${COMPARE_LABEL}")}"
COMPARE_SCENARIOS="${COMPARE_SCENARIOS:-$(opencode_scenarios | tr '\n' ' ')}"
COMPARE_CANDIDATES="${COMPARE_CANDIDATES:-qwen-3.5-abl qwen-3.5-g}"
COMPARE_RESTORE_PRESET="${COMPARE_RESTORE_PRESET:-qwen-3.5-abl}"
COMPARE_STOP_MAIN="${COMPARE_STOP_MAIN:-true}"
COMPARE_LOAD_RESTORE="${COMPARE_LOAD_RESTORE:-true}"

DEFAULT_EXTRA_ARGS="-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288"
DEFAULT_CONTEXT=131072

QWEN_SPEC="${QWEN_SPEC:-$(candidate_spec_json "qwen-3.5-abl" "qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-Q4_K_M-mradermacher.gguf" "qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-mmproj-Q8_0-mradermacher.gguf" "${DEFAULT_CONTEXT}" "${DEFAULT_EXTRA_ARGS}" 9511)}"
GEMINI_SPEC="${GEMINI_SPEC:-$(candidate_spec_json "qwen-3.5-g" "qwen-3.5-9b/Qwen3.5-9B-Gemini-3.1-Pro-Reasoning-Distill-Q4_K_M-jackrong.gguf" "qwen-3.5-9b/Qwen3.5-9B-Gemini-3.1-Pro-Reasoning-Distill-mmproj-BF16-jackrong.gguf" "${DEFAULT_CONTEXT}" "${DEFAULT_EXTRA_ARGS}" 9512)}"
UNSLOTH_SPEC="${UNSLOTH_SPEC:-$(candidate_spec_json "qwen-3.5" "qwen-3.5-9b/Qwen3.5-9B-Q4_K_M-unsloth.gguf" "qwen-3.5-9b/Qwen3.5-9B-mmproj-F16-unsloth.gguf" "${DEFAULT_CONTEXT}" "${DEFAULT_EXTRA_ARGS}" 9513)}"

mkdir -p "${COMPARE_RESULTS_DIR}"
compare_require_tools

CURRENT_PID=""
RESTORE_DONE=0

restore_main_service() {
  if [[ "${RESTORE_DONE}" -eq 1 ]]; then
    return
  fi
  if truthy "${COMPARE_LOAD_RESTORE}"; then
    bash "${PROJECT_ROOT}/scripts/load-main-preset.sh" "${COMPARE_RESTORE_PRESET}" >/dev/null
  fi
  RESTORE_DONE=1
}

stop_managed_main_if_needed() {
  if truthy "${COMPARE_STOP_MAIN}"; then
    bash "${PROJECT_ROOT}/scripts/unload-main.sh"
  fi
}

cleanup_compare() {
  if [[ -n "${CURRENT_PID}" ]]; then
    compare_stop_candidate "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  restore_main_service
}

write_request_file() {
  local scenario="$1"
  local turn="$2"
  local alias="$3"
  local request_path="$4"
  opencode_request_json "${scenario}" "${turn}" "${alias}" > "${request_path}"
}

run_turn() {
  local candidate_json="$1"
  local scenario="$2"
  local turn="$3"
  local candidate_dir="$4"
  local port request_path response_path metrics_path gpu_before_path gpu_after_path summary_path

  port="$(jq -r '.port' <<< "${candidate_json}")"
  request_path="${candidate_dir}/${scenario}_turn${turn}.request.json"
  response_path="${candidate_dir}/${scenario}_turn${turn}.response.json"
  metrics_path="${candidate_dir}/${scenario}_turn${turn}.metrics.json"
  gpu_before_path="${candidate_dir}/${scenario}_turn${turn}.gpu_before.json"
  gpu_after_path="${candidate_dir}/${scenario}_turn${turn}.gpu_after.json"
  summary_path="${candidate_dir}/${scenario}_turn${turn}.summary.json"

  write_request_file "${scenario}" "${turn}" "$(jq -r '.alias' <<< "${candidate_json}")" "${request_path}"
  gpu_mem_json > "${gpu_before_path}"
  compare_chat "${port}" "${request_path}" "${response_path}" "${metrics_path}"
  gpu_mem_json > "${gpu_after_path}"
  compare_result_json "${candidate_json}" "${scenario}" "turn${turn}" "${request_path}" "${response_path}" "${metrics_path}" "${gpu_before_path}" "${gpu_after_path}" > "${summary_path}"
  jq -c '.' "${summary_path}"
}

run_candidate() {
  local candidate_json="$1"
  local alias candidate_dir server_log pid
  alias="$(jq -r '.alias' <<< "${candidate_json}")"
  candidate_dir="${COMPARE_RESULTS_DIR}/${alias}"
  server_log="${COMPARE_RESULTS_DIR}/${alias}.server.log"
  mkdir -p "${candidate_dir}"

  pid="$(compare_start_candidate "${candidate_json}" "${server_log}")"
  CURRENT_PID="${pid}"

  jq -c '.' <<< "${candidate_json}" > "${candidate_dir}/candidate.json"
  local scenario turn_count turn
  for scenario in ${COMPARE_SCENARIOS}; do
    turn_count="$(opencode_turn_count "${scenario}")"
    for turn in $(seq 1 "${turn_count}"); do
      run_turn "${candidate_json}" "${scenario}" "${turn}" "${candidate_dir}"
    done
  done

  compare_stop_candidate "${pid}"
  CURRENT_PID=""
}

write_run_manifest() {
  jq -cn \
    --arg results_dir "${COMPARE_RESULTS_DIR}" \
    --arg label "${COMPARE_LABEL}" \
    --arg candidate_list "${COMPARE_CANDIDATES}" \
    --arg restore_preset "${COMPARE_RESTORE_PRESET}" \
    --arg scenarios "${COMPARE_SCENARIOS}" \
    --arg llama_server_bin "${LLAMA_SERVER_BIN}" \
    --arg model_dir "${MODEL_DIR}" \
    --argjson qwen "${QWEN_SPEC}" \
    --argjson gemini "${GEMINI_SPEC}" \
    --argjson unsloth "${UNSLOTH_SPEC}" \
    '{
      label:$label,
      results_dir:$results_dir,
      restore_preset:$restore_preset,
      requested_candidates:($candidate_list | split(" ") | map(select(length > 0))),
      scenarios:($scenarios | split(" ") | map(select(length > 0))),
      llama_server_bin:$llama_server_bin,
      model_dir:$model_dir,
      candidates:[$qwen, $gemini, $unsloth]
    }' > "${COMPARE_RESULTS_DIR}/run_manifest.json"
}

run_requested_candidates() {
  local candidate
  for candidate in ${COMPARE_CANDIDATES}; do
    case "${candidate}" in
      qwen-3.5-abl) run_candidate "${QWEN_SPEC}" ;;
      qwen-3.5-g) run_candidate "${GEMINI_SPEC}" ;;
      qwen-3.5) run_candidate "${UNSLOTH_SPEC}" ;;
      *)
        echo "Unknown candidate in COMPARE_CANDIDATES: ${candidate}" >&2
        return 1
        ;;
    esac
  done
}

stop_managed_main_if_needed
trap cleanup_compare EXIT
write_run_manifest
run_requested_candidates
restore_main_service
trap - EXIT

printf 'COMPARE_RESULTS_DIR %s\n' "${COMPARE_RESULTS_DIR}"
