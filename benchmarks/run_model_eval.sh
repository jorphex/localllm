#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"
source "${SCRIPT_DIR}/config.sh"

MODEL_EVAL_LABEL="${MODEL_EVAL_LABEL:-model-eval}"
MODEL_EVAL_RESULTS_DIR="${MODEL_EVAL_RESULTS_DIR:-${PROJECT_ROOT}/benchmarks/model_eval/results/$(date -u +%Y%m%dT%H%M%SZ)-${MODEL_EVAL_LABEL}}"
MODEL_EVAL_SUITES="${MODEL_EVAL_SUITES:-transcript_replay sim_compare agentic_barrage}"
MODEL_EVAL_RESTORE_PRESET="${MODEL_EVAL_RESTORE_PRESET:-qwen-3.6-35b-a3b-unsloth-q6}"
MODEL_EVAL_LOAD_RESTORE="${MODEL_EVAL_LOAD_RESTORE:-false}"
MODEL_EVAL_CANDIDATE_SPECS="${MODEL_EVAL_CANDIDATE_SPECS:-}"
MODEL_EVAL_BASE_PORT="${MODEL_EVAL_BASE_PORT:-9711}"
MODEL_EVAL_REPLAY_FIXTURES="${MODEL_EVAL_REPLAY_FIXTURES:-$(benchmark_suite_items transcript_replay | tr '\n' ' ')}"
MODEL_EVAL_SIM_SCENARIOS="${MODEL_EVAL_SIM_SCENARIOS:-$(benchmark_suite_items sim_compare | tr '\n' ' ')}"
MODEL_EVAL_OPENCODE_SCENARIOS="${MODEL_EVAL_OPENCODE_SCENARIOS:-$(benchmark_suite_items opencode_compare | tr '\n' ' ')}"
MODEL_EVAL_BARRAGE_SCENARIOS="${MODEL_EVAL_BARRAGE_SCENARIOS:-$(benchmark_suite_items agentic_barrage | tr '\n' ' ')}"
MODEL_EVAL_CODING_PROMPTS="${MODEL_EVAL_CODING_PROMPTS:-$(benchmark_suite_items coding_compare | tr '\n' ' ')}"

if [[ -z "${MODEL_EVAL_CANDIDATE_SPECS}" ]]; then
  echo "Set MODEL_EVAL_CANDIDATE_SPECS to semicolon-separated alias|model|mmproj|context|extra_args[|port] specs." >&2
  exit 1
fi

mkdir -p "${MODEL_EVAL_RESULTS_DIR}"
export_llama_runtime_env
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

CURRENT_PID=""

cleanup_model_eval() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
}

trap cleanup_model_eval EXIT

mapfile -t NORMALIZED_CANDIDATES < <(
  python3 - <<'PY' "${MODEL_EVAL_CANDIDATE_SPECS}" "${MODEL_EVAL_BASE_PORT}"
from benchmarks.model_eval import parse_candidate_specs
import sys

for candidate in parse_candidate_specs(sys.argv[1], base_port=int(sys.argv[2])):
    print(
        f"{candidate['alias']}|{candidate['model']}|{candidate['mmproj']}|"
        f"{candidate['context']}|{candidate['extra_args']}|{candidate['port']}"
    )
PY
)

write_run_manifest() {
  python3 - <<'PY' "${MODEL_EVAL_RESULTS_DIR}" "${MODEL_EVAL_SUITES}" "${MODEL_EVAL_LABEL}" "${MODEL_EVAL_RESTORE_PRESET}" "${MODEL_EVAL_CANDIDATE_SPECS}" "${MODEL_EVAL_BASE_PORT}" "${LLAMA_SERVER_BIN}" "${MODEL_DIR}"
from benchmarks.model_eval import parse_candidate_specs
from benchmarks.env_metadata import collect_metadata
import json
import os
import sys
from pathlib import Path

results_dir = Path(sys.argv[1])
suites = [item for item in sys.argv[2].split() if item]
candidates = parse_candidate_specs(sys.argv[5], base_port=int(sys.argv[6]))
llama_server_bin = sys.argv[7]
model_dir = Path(sys.argv[8])
model_path = model_dir / candidates[0]["model"] if candidates else None
payload = {
    "label": sys.argv[3],
    "restore_preset": sys.argv[4],
    "results_dir": str(results_dir),
    "suites": suites,
    "candidates": candidates,
    "env_metadata": collect_metadata(llama_server_bin, model_path),
}
(results_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

write_summary() {
  python3 - <<'PY' "${MODEL_EVAL_RESULTS_DIR}" "${MODEL_EVAL_SUITES}" "${MODEL_EVAL_CANDIDATE_SPECS}" "${MODEL_EVAL_BASE_PORT}"
from benchmarks.model_eval import build_model_eval_summary, parse_candidate_specs
import json
import sys
from pathlib import Path

results_dir = Path(sys.argv[1])
suites = [item for item in sys.argv[2].split() if item]
candidates = parse_candidate_specs(sys.argv[3], base_port=int(sys.argv[4]))
summary = build_model_eval_summary(results_dir, candidates, suites)
(results_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
PY
}

spec_json() {
  local alias="$1"
  local model="$2"
  local mmproj="$3"
  local context="$4"
  local extra_args="$5"
  local port="$6"
  jq -cn \
    --arg alias "${alias}" \
    --arg model "${model}" \
    --arg mmproj "${mmproj}" \
    --argjson context "${context}" \
    --arg extra_args "${extra_args}" \
    --argjson port "${port}" \
    '{alias:$alias, model:$model, mmproj:$mmproj, context:$context, extra_args:$extra_args, port:$port}'
}

run_agentic_barrage_suite() {
  local alias="$1"
  local model="$2"
  local mmproj="$3"
  local context="$4"
  local extra_args="$5"
  local port="$6"
  local suite_dir="$7"
  local server_log="${suite_dir}/${alias}.server.log"
  mkdir -p "${suite_dir}"

  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  require_benchmark_env

  CURRENT_PID="$(start_temp_server "${port}" "${context}" "${extra_args}" "${alias}" "${server_log}")"
  wait_for_server "${port}" 180
  BARRAGE_MODEL="${alias}" \
  BARRAGE_HOST="${BENCH_HOST}" \
  BARRAGE_PORT="${port}" \
  BARRAGE_SCENARIOS="${MODEL_EVAL_BARRAGE_SCENARIOS}" \
  OUT_DIR="${suite_dir}" \
  bash "${PROJECT_ROOT}/benchmarks/agentic_barrage.sh" | tee "${suite_dir}/results.ndjson" >/dev/null
  stop_temp_server "${CURRENT_PID}"
  CURRENT_PID=""
}

run_suite() {
  local suite="$1"
  local alias="$2"
  local model="$3"
  local mmproj="$4"
  local context="$5"
  local extra_args="$6"
  local port="$7"
  local candidate_dir="${MODEL_EVAL_RESULTS_DIR}/${alias}"
  local suite_dir="${candidate_dir}/${suite}"
  local injected_spec

  mkdir -p "${suite_dir}"
  injected_spec="$(spec_json "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${port}")"

  case "${suite}" in
    transcript_replay)
      QWEN_SPEC="${injected_spec}" \
      REPLAY_LABEL="${MODEL_EVAL_LABEL}-${alias}" \
      REPLAY_RESULTS_DIR="${suite_dir}" \
      REPLAY_FIXTURES="${MODEL_EVAL_REPLAY_FIXTURES}" \
      REPLAY_CANDIDATES="${alias}" \
      REPLAY_RESTORE_PRESET="${MODEL_EVAL_RESTORE_PRESET}" \
      REPLAY_LOAD_RESTORE="${MODEL_EVAL_LOAD_RESTORE}" \
      bash "${PROJECT_ROOT}/benchmarks/transcript_replay/run_compare.sh"
      ;;
    sim_compare)
      QWEN_SPEC="${injected_spec}" \
      SIM_LABEL="${MODEL_EVAL_LABEL}-${alias}" \
      SIM_RESULTS_DIR="${suite_dir}" \
      SIM_SCENARIOS="${MODEL_EVAL_SIM_SCENARIOS}" \
      SIM_CANDIDATES="${alias}" \
      SIM_RESTORE_PRESET="${MODEL_EVAL_RESTORE_PRESET}" \
      SIM_LOAD_RESTORE="${MODEL_EVAL_LOAD_RESTORE}" \
      bash "${PROJECT_ROOT}/benchmarks/sim_compare/run_compare.sh"
      ;;
    opencode_compare)
      QWEN_SPEC="${injected_spec}" \
      COMPARE_LABEL="${MODEL_EVAL_LABEL}-${alias}" \
      COMPARE_RESULTS_DIR="${suite_dir}" \
      COMPARE_SCENARIOS="${MODEL_EVAL_OPENCODE_SCENARIOS}" \
      COMPARE_CANDIDATES="${alias}" \
      COMPARE_RESTORE_PRESET="${MODEL_EVAL_RESTORE_PRESET}" \
      COMPARE_LOAD_RESTORE="${MODEL_EVAL_LOAD_RESTORE}" \
      bash "${PROJECT_ROOT}/benchmarks/opencode_compare/run_compare.sh"
      ;;
    agentic_barrage)
      run_agentic_barrage_suite "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${port}" "${suite_dir}"
      ;;
    coding_compare)
      CANDIDATE_SPECS="$(
        python3 - <<'PY' "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${port}"
from benchmarks.model_eval import coding_compare_spec
import sys

candidate = {
    "alias": sys.argv[1],
    "model": sys.argv[2],
    "mmproj": sys.argv[3],
    "context": int(sys.argv[4]),
    "extra_args": sys.argv[5],
    "port": int(sys.argv[6]),
}
print(coding_compare_spec(candidate))
PY
      )" \
      OUT_DIR="${suite_dir}" \
      PROMPTS="${MODEL_EVAL_CODING_PROMPTS}" \
      bash "${PROJECT_ROOT}/benchmarks/coding_compare.sh" | tee "${suite_dir}/results.ndjson" >/dev/null
      ;;
    *)
      echo "Unknown suite: ${suite}" >&2
      exit 1
      ;;
  esac
}

write_run_manifest
bash "${PROJECT_ROOT}/scripts/unload-main.sh"

for candidate in "${NORMALIZED_CANDIDATES[@]}"; do
  IFS='|' read -r alias model mmproj context extra_args port <<< "${candidate}"
  for suite in ${MODEL_EVAL_SUITES}; do
    run_suite "${suite}" "${alias}" "${model}" "${mmproj}" "${context}" "${extra_args}" "${port}"
  done
done

write_summary
trap - EXIT
printf 'MODEL_EVAL_RESULTS_DIR %s\n' "${MODEL_EVAL_RESULTS_DIR}"