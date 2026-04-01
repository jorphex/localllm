#!/usr/bin/env bash
set -euo pipefail

SIM_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd -- "${SIM_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd -- "${SIM_DIR}/../.." && pwd)"
source "${BENCHMARK_DIR}/common.sh"

SIM_LABEL="${SIM_LABEL:-sim-retained-9b}"
SIM_RESULTS_DIR="${SIM_RESULTS_DIR:-${SIM_DIR}/results/$(date -u +%Y%m%dT%H%M%SZ)-${SIM_LABEL}}"
SIM_SCENARIOS="${SIM_SCENARIOS:-retry_bugfix queue_bugfix retry_review_feedback session_store_exploration}"
SIM_CANDIDATES="${SIM_CANDIDATES:-qwen-3.5-abl qwen-3.5-g}"
SIM_RESTORE_PRESET="${SIM_RESTORE_PRESET:-qwen-3.5-abl}"
SIM_LOAD_RESTORE="${SIM_LOAD_RESTORE:-true}"

DEFAULT_EXTRA_ARGS="-np 1 -tb 8 -b 512 -ub 256 -cram 0 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288"
DEFAULT_CONTEXT=131072

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

QWEN_SPEC="${QWEN_SPEC:-$(candidate_json "qwen-3.5-abl" "qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-Q4_K_M-mradermacher.gguf" "qwen-3.5-9b/Huihui-Qwen3.5-9B-abliterated-mmproj-Q8_0-mradermacher.gguf" 9521)}"
GEMINI_SPEC="${GEMINI_SPEC:-$(candidate_json "qwen-3.5-g" "qwen-3.5-9b/Qwen3.5-9B-Gemini-3.1-Pro-Reasoning-Distill-Q4_K_M-jackrong.gguf" "qwen-3.5-9b/Qwen3.5-9B-Gemini-3.1-Pro-Reasoning-Distill-mmproj-BF16-jackrong.gguf" 9522)}"
UNSLOTH_SPEC="${UNSLOTH_SPEC:-$(candidate_json "qwen-3.5" "qwen-3.5-9b/Qwen3.5-9B-Q4_K_M-unsloth.gguf" "qwen-3.5-9b/Qwen3.5-9B-mmproj-F16-unsloth.gguf" 9523)}"

write_run_manifest() {
  jq -cn \
    --arg results_dir "${SIM_RESULTS_DIR}" \
    --arg label "${SIM_LABEL}" \
    --arg restore_preset "${SIM_RESTORE_PRESET}" \
    --arg scenarios "${SIM_SCENARIOS}" \
    --arg candidates "${SIM_CANDIDATES}" \
    --arg fixture_root "${SIM_DIR}/fixture_repo" \
    --arg llama_server_bin "${LLAMA_SERVER_BIN}" \
    --arg model_dir "${MODEL_DIR}" \
    --argjson qwen "${QWEN_SPEC}" \
    --argjson gemini "${GEMINI_SPEC}" \
    --argjson unsloth "${UNSLOTH_SPEC}" \
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
      candidates:[$qwen, $gemini, $unsloth]
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
  case "${candidate}" in
    qwen-3.5-abl) run_candidate "${QWEN_SPEC}" ;;
    qwen-3.5-g) run_candidate "${GEMINI_SPEC}" ;;
    qwen-3.5) run_candidate "${UNSLOTH_SPEC}" ;;
    *)
      echo "Unknown candidate: ${candidate}" >&2
      exit 1
      ;;
  esac
done

write_summary
restore_main
trap - EXIT
printf 'SIM_RESULTS_DIR %s\n' "${SIM_RESULTS_DIR}"
