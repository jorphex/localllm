#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"

BARRAGE_V2_CANDIDATES="${BARRAGE_V2_CANDIDATES:-}"
BARRAGE_V2_PROFILE_CLASS="${BARRAGE_V2_PROFILE_CLASS:-fair}"
BARRAGE_V2_PROFILE_ID="${BARRAGE_V2_PROFILE_ID:-}"
BARRAGE_V2_CONTEXT="${BARRAGE_V2_CONTEXT:-}"
BARRAGE_V2_EXTRA_ARGS="${BARRAGE_V2_EXTRA_ARGS:-}"
BARRAGE_V2_REPEATS="${BARRAGE_V2_REPEATS:-}"
BARRAGE_V2_QUALITY_REPEATS="${BARRAGE_V2_QUALITY_REPEATS:-}"
BARRAGE_V2_INCLUDE_HOLDOUT="${BARRAGE_V2_INCLUDE_HOLDOUT:-false}"
BARRAGE_V2_SUITES="${BARRAGE_V2_SUITES:-performance,tool_contract,sandbox}"
BARRAGE_V2_ORDER_SEED="${BARRAGE_V2_ORDER_SEED:-$(date -u +%s)}"
BARRAGE_V2_CACHE_PROMPT="${BARRAGE_V2_CACHE_PROMPT:-}"
BARRAGE_V2_CACHE_RAM="${BARRAGE_V2_CACHE_RAM:-}"
BARRAGE_V2_CACHE_REUSE="${BARRAGE_V2_CACHE_REUSE:-}"
BARRAGE_V2_SLOT_PROMPT_SIMILARITY="${BARRAGE_V2_SLOT_PROMPT_SIMILARITY:-}"
BARRAGE_V2_COOLDOWN_SECONDS="${BARRAGE_V2_COOLDOWN_SECONDS:-}"
BARRAGE_V2_MAX_BASELINE_VRAM_MIB="${BARRAGE_V2_MAX_BASELINE_VRAM_MIB:-}"
BARRAGE_V2_SCHEDULE="sequential-shuffled-cooldown"
BARRAGE_V2_PRODUCTION_DRIVER="${BARRAGE_V2_PRODUCTION_DRIVER:-}"
BARRAGE_V2_PRODUCTION_HARNESS="${BARRAGE_V2_PRODUCTION_HARNESS:-}"
BARRAGE_V2_PRODUCTION_TASKS="${BARRAGE_V2_PRODUCTION_TASKS:-}"
BARRAGE_V2_PRODUCTION_BASE_URL="${BARRAGE_V2_PRODUCTION_BASE_URL:-external://production-driver}"
BARRAGE_V2_DRY_RUN="${BARRAGE_V2_DRY_RUN:-false}"
BARRAGE_V2_RESULTS_DIR="${BARRAGE_V2_RESULTS_DIR:-${PROJECT_ROOT}/benchmarks/barrage-v2-results/$(date -u +%Y%m%dT%H%M%SZ)}"
BARRAGE_V2_STOP_STACK="${BARRAGE_V2_STOP_STACK:-true}"
BARRAGE_V2_START_STACK_AFTER="${BARRAGE_V2_START_STACK_AFTER:-${BARRAGE_V2_STOP_STACK}}"

if [[ -z "${BARRAGE_V2_CANDIDATES}" ]]; then
  echo "Set BARRAGE_V2_CANDIDATES to alias|model|mmproj[|port] entries separated by semicolons." >&2
  exit 1
fi
if [[ "${BARRAGE_V2_PROFILE_CLASS}" != "fair" && "${BARRAGE_V2_PROFILE_CLASS}" != "production" ]]; then
  echo "BARRAGE_V2_PROFILE_CLASS must be fair or production." >&2
  exit 1
fi
if [[ "${BARRAGE_V2_SUITES}" == *"production"* && "${BARRAGE_V2_SUITES}" != "production" ]]; then
  echo "Production must run as an isolated suite." >&2
  exit 1
fi

FAIR_PROFILE_JSON="$(
  python3 - <<'PY'
import json
from benchmarks.barrage_v2.config import load_config
print(json.dumps(load_config()['fair_profile']))
PY
)"
FAIR_ID="$(jq -r '.id' <<< "${FAIR_PROFILE_JSON}")"
FAIR_CONTEXT="$(jq -r '.context' <<< "${FAIR_PROFILE_JSON}")"
FAIR_ARGS="$(jq -r '.extra_args' <<< "${FAIR_PROFILE_JSON}")"
if [[ "${BARRAGE_V2_PROFILE_CLASS}" == "fair" ]]; then
  if [[ -n "${BARRAGE_V2_EXTRA_ARGS}" || -n "${BARRAGE_V2_CONTEXT}" || -n "${BARRAGE_V2_CACHE_PROMPT}" || -n "${BARRAGE_V2_CACHE_RAM}" || -n "${BARRAGE_V2_CACHE_REUSE}" || -n "${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}" || -n "${BARRAGE_V2_COOLDOWN_SECONDS}" || -n "${BARRAGE_V2_MAX_BASELINE_VRAM_MIB}" ]]; then
    echo "Fair runs use the configured launch and cache profile; do not override BARRAGE_V2_* profile settings." >&2
    exit 1
  fi
  BARRAGE_V2_PROFILE_ID="${BARRAGE_V2_PROFILE_ID:-${FAIR_ID}}"
  BARRAGE_V2_CONTEXT="${FAIR_CONTEXT}"
  BARRAGE_V2_EXTRA_ARGS="${FAIR_ARGS}"
  BARRAGE_V2_CACHE_PROMPT="$(jq -r '.cache.prompt' <<< "${FAIR_PROFILE_JSON}")"
  BARRAGE_V2_CACHE_RAM="$(jq -r '.cache.ram_mib' <<< "${FAIR_PROFILE_JSON}")"
  BARRAGE_V2_CACHE_REUSE="$(jq -r '.cache.reuse' <<< "${FAIR_PROFILE_JSON}")"
  BARRAGE_V2_SLOT_PROMPT_SIMILARITY="$(jq -r '.cache.slot_prompt_similarity' <<< "${FAIR_PROFILE_JSON}")"
  BARRAGE_V2_COOLDOWN_SECONDS="$(python3 - <<'PY'
from benchmarks.barrage_v2.config import load_config
print(load_config()['execution']['cooldown_seconds'])
PY
)"
  BARRAGE_V2_MAX_BASELINE_VRAM_MIB="$(python3 - <<'PY'
from benchmarks.barrage_v2.config import load_config
print(load_config()['execution']['max_baseline_vram_mib'])
PY
)"
  [[ "${BARRAGE_V2_PROFILE_ID}" == "${FAIR_ID}" ]] || { echo "Fair profile id mismatch." >&2; exit 1; }
else
  [[ -n "${BARRAGE_V2_PROFILE_ID}" && -n "${BARRAGE_V2_CONTEXT}" && -n "${BARRAGE_V2_EXTRA_ARGS}" && -n "${BARRAGE_V2_CACHE_PROMPT}" && -n "${BARRAGE_V2_CACHE_RAM}" && -n "${BARRAGE_V2_CACHE_REUSE}" && -n "${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}" && -n "${BARRAGE_V2_COOLDOWN_SECONDS}" && -n "${BARRAGE_V2_MAX_BASELINE_VRAM_MIB}" ]] || {
    echo "Production runs require BARRAGE_V2_PROFILE_ID plus explicit launch and cache settings." >&2
    exit 1
  }
fi

mkdir -p "${BARRAGE_V2_RESULTS_DIR}"
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export_llama_runtime_env
export BENCH_CACHE_PROMPT="${BARRAGE_V2_CACHE_PROMPT}"
export BENCH_CACHE_RAM="${BARRAGE_V2_CACHE_RAM}"
export BENCH_CACHE_REUSE="${BARRAGE_V2_CACHE_REUSE}"
export BENCH_SLOT_PROMPT_SIMILARITY="${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}"

IFS=';' read -r -a candidates <<< "${BARRAGE_V2_CANDIDATES}"
mapfile -t candidates < <(
  python3 - <<'PY' "${BARRAGE_V2_ORDER_SEED}" "${BARRAGE_V2_CANDIDATES}"
import random
import sys
items = [item for item in sys.argv[2].split(';') if item]
random.Random(int(sys.argv[1])).shuffle(items)
print('\n'.join(items))
PY
)
candidate_order_json="$(printf '%s\n' "${candidates[@]}" | jq -R . | jq -s .)"

record_launcher_preflight_failure() {
  local candidate_dir="$1"
  local alias="$2"
  local model="$3"
  local index="$4"
  local message="$5"
  local base_url="$6"
  local schedule="$7"
  local cooldown_seconds="$8"
  local launch_argv="${9:-[]}"
  local server_props="${10:-\{\}}"
  local server_slots="${11:-[]}"
  local server_log_path="${12:-/dev/null}"
  local stabilization="${13:-\{\}}"
  python3 -m benchmarks.barrage_v2.runner \
    --base-url "${base_url}" --model "${alias}" --out-dir "${candidate_dir}" \
    --profile-class "${BARRAGE_V2_PROFILE_CLASS}" --profile-id "${BARRAGE_V2_PROFILE_ID}" \
    --model-path "${MODEL_DIR}/${model}" --suites "${BARRAGE_V2_SUITES}" \
    --order-seed "${BARRAGE_V2_ORDER_SEED}" --candidate-order-index "${index}" \
    --candidate-count "${#candidates[@]}" --candidate-order "${candidate_order_json}" \
    --launch-argv "${launch_argv}" --launch-cache-prompt "${BARRAGE_V2_CACHE_PROMPT}" \
    --launch-cache-ram "${BARRAGE_V2_CACHE_RAM}" --launch-cache-reuse "${BARRAGE_V2_CACHE_REUSE}" \
    --launch-slot-similarity "${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}" \
    --server-props "${server_props}" --server-slots "${server_slots}" \
    --server-log-path "${server_log_path}" --stabilization "${stabilization}" \
    --schedule "${schedule}" --cooldown-seconds "${cooldown_seconds}" \
    --preflight-error "${message}" >/dev/null 2>&1 || true
}

cooldown_after_candidate() {
  local index="$1"
  if (( index + 1 < ${#candidates[@]} )); then
    sleep "${BARRAGE_V2_COOLDOWN_SECONDS}"
  fi
}

if truthy "${BARRAGE_V2_DRY_RUN}"; then
  jq -cn \
    --arg profile_class "${BARRAGE_V2_PROFILE_CLASS}" \
    --arg profile_id "${BARRAGE_V2_PROFILE_ID}" \
    --argjson context "${BARRAGE_V2_CONTEXT}" \
    --arg extra_args "${BARRAGE_V2_EXTRA_ARGS}" \
    --argjson cache_prompt "$(truthy "${BARRAGE_V2_CACHE_PROMPT}" && echo true || echo false)" \
    --argjson cache_ram_mib "${BARRAGE_V2_CACHE_RAM}" \
    --argjson cache_reuse "${BARRAGE_V2_CACHE_REUSE}" \
    --argjson slot_prompt_similarity "${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}" \
    --argjson order_seed "${BARRAGE_V2_ORDER_SEED}" \
    --argjson cooldown_seconds "${BARRAGE_V2_COOLDOWN_SECONDS}" \
    --argjson max_baseline_vram_mib "${BARRAGE_V2_MAX_BASELINE_VRAM_MIB}" \
    --argjson include_holdout "$(truthy "${BARRAGE_V2_INCLUDE_HOLDOUT}" && echo true || echo false)" \
    --argjson candidates "${candidate_order_json}" \
    '{profile:{class:$profile_class,id:$profile_id},context:$context,extra_args:$extra_args,cache:{prompt:$cache_prompt,ram_mib:$cache_ram_mib,reuse:$cache_reuse,slot_prompt_similarity:$slot_prompt_similarity},order_seed:$order_seed,cooldown_seconds:$cooldown_seconds,max_baseline_vram_mib:$max_baseline_vram_mib,include_holdout:$include_holdout,candidates:$candidates}'
  exit 0
fi

if [[ "${BARRAGE_V2_SUITES}" == "production" ]]; then
  [[ "${BARRAGE_V2_PROFILE_CLASS}" == "production" ]] || { echo "Production suite requires BARRAGE_V2_PROFILE_CLASS=production." >&2; exit 1; }
  [[ -n "${BARRAGE_V2_PRODUCTION_DRIVER}" && -n "${BARRAGE_V2_PRODUCTION_HARNESS}" && -n "${BARRAGE_V2_PRODUCTION_TASKS}" ]] || {
    echo "Production suite requires BARRAGE_V2_PRODUCTION_DRIVER, BARRAGE_V2_PRODUCTION_HARNESS, and BARRAGE_V2_PRODUCTION_TASKS." >&2
    exit 1
  }
  overall_status=0
  for index in "${!candidates[@]}"; do
    IFS='|' read -r alias model _mmproj _port <<< "${candidates[$index]}"
    [[ -n "${alias}" && -n "${model}" ]] || { echo "Invalid candidate spec: ${candidates[$index]}" >&2; exit 1; }
    candidate_dir="${BARRAGE_V2_RESULTS_DIR}/${alias}"
    if [[ ! -f "${MODEL_DIR}/${model}" ]]; then
      record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "candidate model is missing: ${MODEL_DIR}/${model}" "${BARRAGE_V2_PRODUCTION_BASE_URL}" external-driver 0
      overall_status=1
      continue
    fi
    args=(--base-url "${BARRAGE_V2_PRODUCTION_BASE_URL}" --model "${alias}" --out-dir "${candidate_dir}" --profile-class production --profile-id "${BARRAGE_V2_PROFILE_ID}" --model-path "${MODEL_DIR}/${model}" --suites production --order-seed "${BARRAGE_V2_ORDER_SEED}" --candidate-order-index "${index}" --candidate-count "${#candidates[@]}" --candidate-order "${candidate_order_json}" --launch-argv '[]' --launch-cache-prompt "${BARRAGE_V2_CACHE_PROMPT}" --launch-cache-ram "${BARRAGE_V2_CACHE_RAM}" --launch-cache-reuse "${BARRAGE_V2_CACHE_REUSE}" --launch-slot-similarity "${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}" --server-props '{}' --server-slots '[]' --server-log-path /dev/null --stabilization '{"mode":"external-driver","managed_stack_untouched":true}' --schedule external-driver --cooldown-seconds 0 --production-driver "${BARRAGE_V2_PRODUCTION_DRIVER}" --production-harness "${BARRAGE_V2_PRODUCTION_HARNESS}" --production-tasks "${BARRAGE_V2_PRODUCTION_TASKS}")
    [[ -z "${BARRAGE_V2_QUALITY_REPEATS}" ]] || args+=(--quality-repeats "${BARRAGE_V2_QUALITY_REPEATS}")
    truthy "${BARRAGE_V2_INCLUDE_HOLDOUT}" && args+=(--include-holdout)
    if ! python3 -m benchmarks.barrage_v2.runner "${args[@]}"; then
      overall_status=1
    fi
  done
  printf 'BARRAGE_V2_RESULTS_DIR %s\n' "${BARRAGE_V2_RESULTS_DIR}"
  exit "${overall_status}"
fi

STACK_STOPPED=0
CURRENT_PID=""
cleanup() {
  [[ -z "${CURRENT_PID}" ]] || stop_temp_server "${CURRENT_PID}"
  if [[ "${STACK_STOPPED}" -eq 1 ]] && truthy "${BARRAGE_V2_START_STACK_AFTER}"; then
    bash "${PROJECT_ROOT}/scripts/start-stack.sh" || true
  fi
}
trap cleanup EXIT

if truthy "${BARRAGE_V2_STOP_STACK}"; then
  # Once a stop is attempted, cleanup owns restoring the managed stack even if systemctl reports a partial failure.
  STACK_STOPPED=1
  bash "${PROJECT_ROOT}/scripts/stop-stack.sh"
fi

capture_stabilization() {
  local gpu_mem hardware used_mib
  gpu_mem="$(gpu_mem_json)"
  hardware="$(rocm-smi --showtemp --showclocks --showmeminfo vram --json 2>/dev/null || printf '{}')"
  used_mib="$(jq -r '.used_mib // -1' <<< "${gpu_mem}")"
  if [[ "${used_mib}" == "-1" ]]; then
    echo "Fair run could not establish GPU VRAM baseline." >&2
    return 1
  fi
  if (( used_mib > BARRAGE_V2_MAX_BASELINE_VRAM_MIB )); then
    echo "Fair run GPU baseline is ${used_mib} MiB; maximum is ${BARRAGE_V2_MAX_BASELINE_VRAM_MIB} MiB." >&2
    return 1
  fi
  jq -e . >/dev/null <<< "${hardware}" || hardware='{}'
  jq -cn \
    --argjson gpu_mem "${gpu_mem}" \
    --argjson hardware "${hardware}" \
    --argjson max_used_mib "${BARRAGE_V2_MAX_BASELINE_VRAM_MIB}" \
    '{gpu_mem:$gpu_mem,hardware:$hardware,max_used_mib:$max_used_mib}'
}

sleep "${BARRAGE_V2_COOLDOWN_SECONDS}"

overall_status=0
for index in "${!candidates[@]}"; do
  IFS='|' read -r alias model mmproj port <<< "${candidates[$index]}"
  [[ -n "${alias}" && -n "${model}" ]] || { echo "Invalid candidate spec: ${candidates[$index]}" >&2; exit 1; }
  port="${port:-$((9721 + index))}"
  BENCH_MODEL="${model}"
  BENCH_MMPROJ="${mmproj}"
  candidate_dir="${BARRAGE_V2_RESULTS_DIR}/${alias}"
  server_log_path="${candidate_dir}.server.log"
  if [[ ! -f "${LLAMA_SERVER_BIN}" || ! -f "${MODEL_DIR}/${model}" || ( -n "${mmproj}" && ! -f "${MODEL_DIR}/${mmproj}" ) ]]; then
    record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "benchmark runtime or candidate artifact is missing" "http://127.0.0.1:${port}" "${BARRAGE_V2_SCHEDULE}" "${BARRAGE_V2_COOLDOWN_SECONDS}" '[]' '{}' '[]' "${server_log_path}"
    overall_status=1
    cooldown_after_candidate "${index}"
    continue
  fi
  if ! stabilization="$(capture_stabilization)"; then
    record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "GPU baseline stabilization failed" "http://127.0.0.1:${port}" "${BARRAGE_V2_SCHEDULE}" "${BARRAGE_V2_COOLDOWN_SECONDS}" '[]' '{}' '[]' "${server_log_path}"
    overall_status=1
    cooldown_after_candidate "${index}"
    continue
  fi
  CURRENT_PID="$(start_temp_server "${port}" "${BARRAGE_V2_CONTEXT}" "${BARRAGE_V2_EXTRA_ARGS}" "${alias}" "${server_log_path}")"
  if ! wait_for_server "${port}" 180; then
    record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "scratch server did not become healthy" "http://127.0.0.1:${port}" "${BARRAGE_V2_SCHEDULE}" "${BARRAGE_V2_COOLDOWN_SECONDS}" '[]' '{}' '[]' "${server_log_path}" "${stabilization}"
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
    overall_status=1
    cooldown_after_candidate "${index}"
    continue
  fi
  postload_gpu="$(gpu_mem_json)"
  stabilization="$(jq -cn --argjson baseline "${stabilization}" --argjson postload_gpu "${postload_gpu}" '$baseline + {postload_gpu:$postload_gpu}')"
  if ! launch_argv="$(tr '\0' '\n' < "/proc/${CURRENT_PID}/cmdline" | jq -R . | jq -s .)"; then
    record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "could not capture scratch-server argv" "http://127.0.0.1:${port}" "${BARRAGE_V2_SCHEDULE}" "${BARRAGE_V2_COOLDOWN_SECONDS}" '[]' '{}' '[]' "${server_log_path}" "${stabilization}"
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
    overall_status=1
    cooldown_after_candidate "${index}"
    continue
  fi
  if ! server_props="$(curl -fsS "http://${BENCH_HOST}:${port}/props")"; then
    record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "could not fetch scratch-server /props" "http://127.0.0.1:${port}" "${BARRAGE_V2_SCHEDULE}" "${BARRAGE_V2_COOLDOWN_SECONDS}" "${launch_argv}" '{}' '[]' "${server_log_path}" "${stabilization}"
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
    overall_status=1
    cooldown_after_candidate "${index}"
    continue
  fi
  if ! server_slots="$(curl -fsS "http://${BENCH_HOST}:${port}/slots")"; then
    record_launcher_preflight_failure "${candidate_dir}" "${alias}" "${model}" "${index}" "could not fetch scratch-server /slots" "http://127.0.0.1:${port}" "${BARRAGE_V2_SCHEDULE}" "${BARRAGE_V2_COOLDOWN_SECONDS}" "${launch_argv}" "${server_props}" '[]' "${server_log_path}" "${stabilization}"
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
    overall_status=1
    cooldown_after_candidate "${index}"
    continue
  fi
  args=(--base-url "http://127.0.0.1:${port}" --model "${alias}" --out-dir "${candidate_dir}" --profile-class "${BARRAGE_V2_PROFILE_CLASS}" --profile-id "${BARRAGE_V2_PROFILE_ID}" --model-path "${MODEL_DIR}/${model}" --server-bin "${LLAMA_SERVER_BIN}" --suites "${BARRAGE_V2_SUITES}" --order-seed "${BARRAGE_V2_ORDER_SEED}" --candidate-order-index "${index}" --candidate-count "${#candidates[@]}" --candidate-order "${candidate_order_json}" --launch-argv "${launch_argv}" --launch-cache-prompt "${BARRAGE_V2_CACHE_PROMPT}" --launch-cache-ram "${BARRAGE_V2_CACHE_RAM}" --launch-cache-reuse "${BARRAGE_V2_CACHE_REUSE}" --launch-slot-similarity "${BARRAGE_V2_SLOT_PROMPT_SIMILARITY}" --server-props "${server_props}" --server-slots "${server_slots}" --server-log-path "${server_log_path}" --stabilization "${stabilization}" --schedule "${BARRAGE_V2_SCHEDULE}" --cooldown-seconds "${BARRAGE_V2_COOLDOWN_SECONDS}")
  [[ -z "${BARRAGE_V2_REPEATS}" ]] || args+=(--repeats "${BARRAGE_V2_REPEATS}")
  [[ -z "${BARRAGE_V2_QUALITY_REPEATS}" ]] || args+=(--quality-repeats "${BARRAGE_V2_QUALITY_REPEATS}")
  truthy "${BARRAGE_V2_INCLUDE_HOLDOUT}" && args+=(--include-holdout)
  if ! python3 -m benchmarks.barrage_v2.runner "${args[@]}"; then
    overall_status=1
  fi
  stop_temp_server "${CURRENT_PID}"
  CURRENT_PID=""
  cooldown_after_candidate "${index}"
done

cleanup
trap - EXIT
printf 'BARRAGE_V2_RESULTS_DIR %s\n' "${BARRAGE_V2_RESULTS_DIR}"
exit "${overall_status}"
