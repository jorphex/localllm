#!/usr/bin/env bash
set -euo pipefail

REPLAY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd -- "${REPLAY_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd -- "${REPLAY_DIR}/../.." && pwd)"
source "${BENCHMARK_DIR}/common.sh"
source "${BENCHMARK_DIR}/config.sh"

REPLAY_LABEL="${REPLAY_LABEL:-transcript-replay-qwen36-35b-unsloth}"
REPLAY_RESULTS_DIR="${REPLAY_RESULTS_DIR:-${REPLAY_DIR}/results/$(date -u +%Y%m%dT%H%M%SZ)-${REPLAY_LABEL}}"
REPLAY_FIXTURES="${REPLAY_FIXTURES:-$(benchmark_suite_items transcript_replay | tr '\n' ' ')}"
REPLAY_CANDIDATES="${REPLAY_CANDIDATES:-qwen36-35b-unsloth}"
REPLAY_RESTORE_PRESET="${REPLAY_RESTORE_PRESET:-qwen-3.6-35b-a3b-unsloth-q6}"
REPLAY_LOAD_RESTORE="${REPLAY_LOAD_RESTORE:-true}"

DEFAULT_EXTRA_ARGS="${DEFAULT_EXTRA_ARGS:-$(benchmark_server_extra_args)}"
DEFAULT_CONTEXT="${DEFAULT_CONTEXT:-$(benchmark_default_context)}"

mkdir -p "${REPLAY_RESULTS_DIR}"
export_llama_runtime_env
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

CURRENT_PID=""
RESTORE_DONE=0

candidate_json() {
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
    '{
      alias:$alias,
      model:$model,
      mmproj:$mmproj,
      context:$context,
      extra_args:$extra_args,
      port:$port
    }'
}

QWEN_SPEC="${QWEN_SPEC:-$(candidate_json "qwen36-35b-unsloth" "qwen-3.6/Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf" "qwen-3.6/Qwen3.6-35B-A3B-mmproj-F16-unsloth.gguf" "${DEFAULT_CONTEXT}" "${DEFAULT_EXTRA_ARGS}" 9531)}"
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
  local specs_json metadata_json model_path
  specs_json="$(available_specs_json)"
  model_path="${MODEL_DIR}/$(jq -r '.[0].model' <<< "${specs_json}")"
  metadata_json="$(benchmark_env_metadata_json "${LLAMA_SERVER_BIN}" "${model_path}")"
  jq -cn \
    --arg results_dir "${REPLAY_RESULTS_DIR}" \
    --arg label "${REPLAY_LABEL}" \
    --arg restore_preset "${REPLAY_RESTORE_PRESET}" \
    --arg fixtures "${REPLAY_FIXTURES}" \
    --arg candidates "${REPLAY_CANDIDATES}" \
    --arg llama_server_bin "${LLAMA_SERVER_BIN}" \
    --arg model_dir "${MODEL_DIR}" \
    --argjson specs "${specs_json}" \
    --argjson env_metadata "${metadata_json}" \
    '{
      family:"general_agentic",
      suite:"transcript_replay",
      results_dir:$results_dir,
      label:$label,
      restore_preset:$restore_preset,
      requested_fixtures:($fixtures | split(" ") | map(select(length > 0))),
      requested_candidates:($candidates | split(" ") | map(select(length > 0))),
      llama_server_bin:$llama_server_bin,
      model_dir:$model_dir,
      candidates:$specs,
      env_metadata:$env_metadata
    }' > "${REPLAY_RESULTS_DIR}/run_manifest.json"
}

write_summary() {
  python3 - <<'PY' "${REPLAY_RESULTS_DIR}" "${REPLAY_CANDIDATES}" "${REPLAY_FIXTURES}"
import json
import sys
from pathlib import Path

from benchmarks.result_summaries import replay_run_summary

results_dir = Path(sys.argv[1])
candidates = [item for item in sys.argv[2].split() if item]
fixtures = [item for item in sys.argv[3].split() if item]
summary = replay_run_summary(results_dir, candidates, fixtures)
(results_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
PY
}

restore_main() {
  if [[ "${RESTORE_DONE}" -eq 1 ]]; then
    return
  fi
  if truthy "${REPLAY_LOAD_RESTORE}" && [[ -n "${REPLAY_RESTORE_PRESET}" ]]; then
    bash "${PROJECT_ROOT}/scripts/load-main-preset.sh" "${REPLAY_RESTORE_PRESET}" >/dev/null
  fi
  RESTORE_DONE=1
}

cleanup_replay_compare() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  restore_main
}

run_candidate() {
  local spec="$1"
  local alias model mmproj context extra_args port log_path candidate_dir pid fixture
  alias="$(jq -r '.alias' <<< "${spec}")"
  model="$(jq -r '.model' <<< "${spec}")"
  mmproj="$(jq -r '.mmproj' <<< "${spec}")"
  context="$(jq -r '.context' <<< "${spec}")"
  extra_args="$(jq -r '.extra_args' <<< "${spec}")"
  port="$(jq -r '.port' <<< "${spec}")"
  log_path="${REPLAY_RESULTS_DIR}/${alias}.server.log"
  candidate_dir="${REPLAY_RESULTS_DIR}/${alias}"
  mkdir -p "${candidate_dir}"

  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  require_benchmark_env

  pid="$(start_temp_server "${port}" "${context}" "${extra_args}" "${alias}" "${log_path}")"
  CURRENT_PID="${pid}"
  wait_for_server "${port}" 180

  for fixture in ${REPLAY_FIXTURES}; do
    python3 "${REPLAY_DIR}/run_replay.py" \
      --base-url "http://127.0.0.1:${port}" \
      --model "${alias}" \
      --fixture "${REPLAY_DIR}/fixtures/${fixture}.json" \
      --out-dir "${candidate_dir}/${fixture}"
  done

  stop_temp_server "${pid}"
  CURRENT_PID=""
}

bash "${PROJECT_ROOT}/scripts/unload-main.sh"
pkill -f 'llama-server.*--port 8091' || true
trap cleanup_replay_compare EXIT
write_run_manifest

for candidate in ${REPLAY_CANDIDATES}; do
  if ! spec="$(find_candidate_spec "${candidate}")"; then
    echo "Unknown candidate: ${candidate}" >&2
    exit 1
  fi
  run_candidate "${spec}"
done

write_summary
PUBLISH_LABEL="${BENCHMARK_PUBLISH_LABEL:-$(basename "${REPLAY_RESULTS_DIR}")}"
python3 "${BENCHMARK_DIR}/publish_summary.py" "${REPLAY_RESULTS_DIR}" transcript_replay "${PUBLISH_LABEL}"
restore_main
trap - EXIT
printf 'REPLAY_RESULTS_DIR %s\n' "${REPLAY_RESULTS_DIR}"