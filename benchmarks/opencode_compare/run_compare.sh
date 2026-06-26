#!/usr/bin/env bash
set -euo pipefail

COMPARE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${COMPARE_DIR}/common.sh"
source "${COMPARE_DIR}/scenarios.sh"
source "${BENCHMARK_DIR}/config.sh"

COMPARE_LABEL="${COMPARE_LABEL:-qwen36-35b-unsloth}"
COMPARE_RESULTS_DIR="${COMPARE_RESULTS_DIR:-$(compare_results_dir "${COMPARE_LABEL}")}"
COMPARE_SCENARIOS="${COMPARE_SCENARIOS:-$(benchmark_suite_items opencode_compare | tr '\n' ' ')}"
COMPARE_CANDIDATES="${COMPARE_CANDIDATES:-qwen36-35b-unsloth}"
COMPARE_RESTORE_PRESET="${COMPARE_RESTORE_PRESET:-qwen-3.6-35b-a3b-unsloth-q6}"
COMPARE_STOP_MAIN="${COMPARE_STOP_MAIN:-true}"
COMPARE_LOAD_RESTORE="${COMPARE_LOAD_RESTORE:-true}"

DEFAULT_EXTRA_ARGS="${DEFAULT_EXTRA_ARGS:-$(benchmark_server_extra_args)}"
DEFAULT_CONTEXT="${DEFAULT_CONTEXT:-$(benchmark_default_context)}"

QWEN_SPEC="${QWEN_SPEC:-$(candidate_spec_json "qwen36-35b-unsloth" "qwen-3.6/Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf" "qwen-3.6/Qwen3.6-35B-A3B-mmproj-F16-unsloth.gguf" "${DEFAULT_CONTEXT}" "${DEFAULT_EXTRA_ARGS}" 9511)}"
GEMINI_SPEC="${GEMINI_SPEC:-}"
UNSLOTH_SPEC="${UNSLOTH_SPEC:-}"
AVAILABLE_SPECS=()
[[ -n "${QWEN_SPEC}" ]] && AVAILABLE_SPECS+=("${QWEN_SPEC}")
[[ -n "${GEMINI_SPEC}" ]] && AVAILABLE_SPECS+=("${GEMINI_SPEC}")
[[ -n "${UNSLOTH_SPEC}" ]] && AVAILABLE_SPECS+=("${UNSLOTH_SPEC}")

available_specs_json() {
  printf '%s\n' "${AVAILABLE_SPECS[@]}" | jq -s '.'
}

find_candidate_spec() {
  local requested_alias="$1"
  local spec alias
  for spec in "${AVAILABLE_SPECS[@]}"; do
    alias="$(jq -r '.alias' <<< "${spec}")"
    if [[ "${alias}" == "${requested_alias}" ]]; then
      printf '%s\n' "${spec}"
      return 0
    fi
  done
  return 1
}

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

  python3 "${COMPARE_DIR}/score_compare.py" "${candidate_dir}"

  compare_stop_candidate "${pid}"
  CURRENT_PID=""
}

write_run_manifest() {
  local specs_json metadata_json model_path
  specs_json="$(available_specs_json)"
  model_path="${MODEL_DIR}/$(jq -r '.[0].model' <<< "${specs_json}")"
  metadata_json="$(benchmark_env_metadata_json "${LLAMA_SERVER_BIN}" "${model_path}")"
  jq -cn \
    --arg results_dir "${COMPARE_RESULTS_DIR}" \
    --arg label "${COMPARE_LABEL}" \
    --arg candidate_list "${COMPARE_CANDIDATES}" \
    --arg restore_preset "${COMPARE_RESTORE_PRESET}" \
    --arg scenarios "${COMPARE_SCENARIOS}" \
    --arg llama_server_bin "${LLAMA_SERVER_BIN}" \
    --arg model_dir "${MODEL_DIR}" \
    --argjson specs "${specs_json}" \
    --argjson env_metadata "${metadata_json}" \
    '{
      label:$label,
      results_dir:$results_dir,
      restore_preset:$restore_preset,
      requested_candidates:($candidate_list | split(" ") | map(select(length > 0))),
      scenarios:($scenarios | split(" ") | map(select(length > 0))),
      llama_server_bin:$llama_server_bin,
      model_dir:$model_dir,
      candidates:$specs,
      env_metadata:$env_metadata
    }' > "${COMPARE_RESULTS_DIR}/run_manifest.json"
}

run_requested_candidates() {
  local candidate spec
  for candidate in ${COMPARE_CANDIDATES}; do
    if ! spec="$(find_candidate_spec "${candidate}")"; then
      echo "Unknown candidate in COMPARE_CANDIDATES: ${candidate}" >&2
      return 1
    fi
    run_candidate "${spec}"
  done
}

stop_managed_main_if_needed
trap cleanup_compare EXIT
write_run_manifest
run_requested_candidates

python3 - <<'PY' "${COMPARE_RESULTS_DIR}"
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
candidates = []
for summary_path in sorted(root.glob("*/summary.json")):
    candidate = summary_path.parent.name
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    candidates.append({"candidate": candidate, **data})
avg = sum(c["average_score"] for c in candidates) / len(candidates) if candidates else 0.0
merged = {
    "schema_version": 1,
    "suite": "opencode_compare",
    "family": "coding_agentic",
    "results_dir": str(root),
    "candidates": candidates,
    "candidate_count": len(candidates),
    "average_score": round(avg, 4),
}
(root / "summary.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
PY

PUBLISH_LABEL="${BENCHMARK_PUBLISH_LABEL:-$(basename "${COMPARE_RESULTS_DIR}")}"
python3 "${BENCHMARK_DIR}/publish_summary.py" "${COMPARE_RESULTS_DIR}" opencode_compare "${PUBLISH_LABEL}"
restore_main_service
trap - EXIT

printf 'COMPARE_RESULTS_DIR %s\n' "${COMPARE_RESULTS_DIR}"