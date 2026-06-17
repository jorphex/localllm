#!/usr/bin/env bash
set -euo pipefail

SIM_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd -- "${SIM_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd -- "${SIM_DIR}/../.." && pwd)"
source "${BENCHMARK_DIR}/common.sh"

SIM_LABEL="${SIM_LABEL:-sim-qwen36-35b-unsloth}"
SIM_RESULTS_DIR="${SIM_RESULTS_DIR:-${SIM_DIR}/results/$(date -u +%Y%m%dT%H%M%SZ)-${SIM_LABEL}}"
SIM_SCENARIOS="${SIM_SCENARIOS:-retry_bugfix queue_bugfix retry_review_feedback session_store_exploration}"
SIM_CANDIDATES="${SIM_CANDIDATES:-qwen36-35b-unsloth}"
SIM_RESTORE_PRESET="${SIM_RESTORE_PRESET:-qwen-3.6-35b-a3b-unsloth-q6}"
SIM_LOAD_RESTORE="${SIM_LOAD_RESTORE:-true}"

DEFAULT_EXTRA_ARGS="-np 1 -tb 8 -b 1024 -ub 512 -fa on --threads-http 4 -ctk q8_0 -ctv q8_0 -rea on --metrics --no-warmup --no-mmap --image-max-tokens 12288 --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0.0 --presence-penalty 0.0 --repeat-penalty 1.0 --spec-default --slot-save-path /home/j/projects/localllm/state/main-slots"
DEFAULT_CONTEXT=262144

mkdir -p "${SIM_RESULTS_DIR}"
export_llama_runtime_env
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

CURRENT_PID=""
RESTORE_DONE=0

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

QWEN_SPEC="${QWEN_SPEC:-$(candidate_json "qwen36-35b-unsloth" "qwen-3.6/Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf" "qwen-3.6/Qwen3.6-35B-A3B-mmproj-F16-unsloth.gguf" 9521)}"
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

write_run_manifest() {
  local specs_json
  specs_json="$(available_specs_json)"
  jq -cn \
    --arg results_dir "${SIM_RESULTS_DIR}" \
    --arg label "${SIM_LABEL}" \
    --arg restore_preset "${SIM_RESTORE_PRESET}" \
    --arg scenarios "${SIM_SCENARIOS}" \
    --arg candidates "${SIM_CANDIDATES}" \
    --arg fixture_root "${SIM_DIR}/fixture_repo" \
    --arg llama_server_bin "${LLAMA_SERVER_BIN}" \
    --arg model_dir "${MODEL_DIR}" \
    --argjson specs "${specs_json}" \
    '{
      family:"coding_agentic",
      suite:"sim_compare",
      results_dir:$results_dir,
      label:$label,
      restore_preset:$restore_preset,
      requested_scenarios:($scenarios | split(" ") | map(select(length > 0))),
      requested_candidates:($candidates | split(" ") | map(select(length > 0))),
      fixture_root:$fixture_root,
      llama_server_bin:$llama_server_bin,
      model_dir:$model_dir,
      candidates:$specs
    }' > "${SIM_RESULTS_DIR}/run_manifest.json"
}

write_summary() {
  python3 - <<'PY' "${SIM_RESULTS_DIR}" "${SIM_CANDIDATES}" "${SIM_SCENARIOS}"
import json
import sys
from pathlib import Path

from benchmarks.result_summaries import sim_run_summary

results_dir = Path(sys.argv[1])
candidates = [item for item in sys.argv[2].split() if item]
scenarios = [item for item in sys.argv[3].split() if item]
summary = sim_run_summary(results_dir, candidates, scenarios)
(results_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
PY
}

restore_main() {
  if [[ "${RESTORE_DONE}" -eq 1 ]]; then
    return
  fi
  if truthy "${SIM_LOAD_RESTORE}" && [[ -n "${SIM_RESTORE_PRESET}" ]]; then
    bash "${PROJECT_ROOT}/scripts/load-main-preset.sh" "${SIM_RESTORE_PRESET}" >/dev/null
  fi
  RESTORE_DONE=1
}

cleanup_sim_compare() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  restore_main
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
  CURRENT_PID="${pid}"
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
  CURRENT_PID=""
}

bash "${PROJECT_ROOT}/scripts/unload-main.sh"
trap cleanup_sim_compare EXIT
write_run_manifest

for candidate in ${SIM_CANDIDATES}; do
  if ! spec="$(find_candidate_spec "${candidate}")"; then
    echo "Unknown candidate: ${candidate}" >&2
    exit 1
  fi
  run_candidate "${spec}"
done

write_summary
restore_main
trap - EXIT
printf 'SIM_RESULTS_DIR %s\n' "${SIM_RESULTS_DIR}"
