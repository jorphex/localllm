#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"
source "${PROJECT_ROOT}/scripts/gpu-safety.sh"

RESULTS_DIR="${1:-${PROJECT_ROOT}/benchmarks/tuning-v1-results/gpu-safety-qualification-$(date -u +%Y%m%dT%H%M%SZ)}"
SAFETY_DIR="${RESULTS_DIR}/safety"
CURRENT_PID=""
STACK_STOPPED=0
SAFETY_FAULT=0
SAFETY_CURSOR=""
PORT=9732

mkdir -p "${SAFETY_DIR}"

stop_current() {
  local label="$1"
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_temp_server "${CURRENT_PID}"
    CURRENT_PID=""
  fi
  if ! gpu_safety_stabilize "${SAFETY_CURSOR}" "${SAFETY_DIR}/${label}-post-unload-kernel.log"; then
    SAFETY_FAULT=1
  fi
  if ! gpu_safety_monitor_clean; then
    SAFETY_FAULT=1
  fi
  gpu_safety_stop_monitor
  [[ "${SAFETY_FAULT}" -eq 0 ]]
}

cleanup() {
  if [[ -n "${CURRENT_PID}" ]]; then
    stop_current cleanup || true
  fi
  gpu_safety_stop_monitor
  if [[ "${STACK_STOPPED}" -eq 1 ]]; then
    if [[ "${SAFETY_FAULT}" -eq 0 ]] && gpu_safety_assert_pm && gpu_safety_scan_after_cursor "${SAFETY_CURSOR}" "${SAFETY_DIR}/pre-restore-kernel.log"; then
      if bash "${PROJECT_ROOT}/scripts/start-stack.sh"; then
        sleep "${GPU_SAFETY_STABILIZE_SECONDS}"
        if ! gpu_safety_assert_pm || ! gpu_safety_scan_after_cursor "${SAFETY_CURSOR}" "${SAFETY_DIR}/post-restore-kernel.log"; then
          SAFETY_FAULT=1
        fi
      else
        SAFETY_FAULT=1
      fi
    else
      SAFETY_FAULT=1
      echo "Safety fault: managed GPU services were not restored automatically." >&2
    fi
  fi
  gpu_safety_stop_inhibitor
}
trap cleanup EXIT

gpu_safety_assert_pm
gpu_safety_assert_clean_boot "${SAFETY_DIR}/preflight-kernel.log"
SAFETY_CURSOR="$(gpu_safety_capture_cursor)"
gpu_safety_start_inhibitor

config_hash_before="$(sha256sum "${PROJECT_ROOT}/config/localllm-main.env" | cut -d' ' -f1)"
jq -n \
  --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg kernel "$(uname -r)" \
  --arg cursor "${SAFETY_CURSOR}" \
  --arg config_hash "${config_hash_before}" \
  '{started_at:$started_at,kernel:$kernel,journal_cursor:$cursor,active_config_sha256:$config_hash,cycles:[]}' \
  > "${RESULTS_DIR}/qualification.json"

STACK_STOPPED=1
bash "${PROJECT_ROOT}/scripts/stop-stack.sh"
gpu_safety_stabilize "${SAFETY_CURSOR}" "${SAFETY_DIR}/post-stack-stop-kernel.log"

baseline_gpu="$(gpu_mem_json)"
baseline_used="$(jq -r '.used_mib // -1' <<< "${baseline_gpu}")"
if (( baseline_used < 0 || baseline_used > 1024 )); then
  echo "Qualification VRAM baseline is not clean: ${baseline_gpu}" >&2
  exit 1
fi

BENCH_MODEL='qwen-3.6/Qwen3.6-27B-MTP-Q6_K-unsloth.gguf'
BENCH_MMPROJ='qwen-3.6/Qwen3.6-27B-MTP-mmproj-F16-unsloth.gguf'
BENCH_THREADS=10
BENCH_CACHE_PROMPT=true
BENCH_CACHE_RAM=2048
BENCH_CACHE_REUSE=0
BENCH_SLOT_PROMPT_SIMILARITY=0.1
BENCH_SLOT_SAVE_PATH="${RESULTS_DIR}/slots"
mkdir -p "${BENCH_SLOT_SAVE_PATH}"
extra_args='-v -np 1 -tb 8 -b 2048 -ub 1024 -fa on --threads-http 4 -ctk q8_0 -ctv q8_0 -rea on --metrics --no-warmup --image-max-tokens 8192 --temp 0 --spec-type draft-mtp --spec-draft-n-max 2 --ctx-checkpoints 4'

for cycle in 1 2 3; do
  log_path="${RESULTS_DIR}/cycle-${cycle}.server.log"
  CURRENT_PID="$(start_temp_server "${PORT}" 32768 "${extra_args}" "gpu-safety-qualification" "${log_path}")"
  gpu_safety_start_monitor "${SAFETY_CURSOR}" "${CURRENT_PID}" "${SAFETY_DIR}/cycle-${cycle}"
  if ! wait_for_server "${PORT}" 240; then
    echo "Qualification cycle ${cycle} failed health" >&2
    stop_current "cycle-${cycle}-startup-failure" || true
    exit 1
  fi
  gpu_safety_monitor_clean
  gpu_safety_scan_after_cursor "${SAFETY_CURSOR}" "${SAFETY_DIR}/cycle-${cycle}-post-load-kernel.log"
  response="$(probe_chat "${PORT}" 'Reply with exactly READY.' 8 false '{"temperature":0,"seed":73627}')"
  answer="$(jq -r '.choices[0].message.content // empty' <<< "${response}")"
  if [[ "${answer}" != "READY" && "${answer}" != "READY." ]]; then
    echo "Qualification cycle ${cycle} returned an unexpected answer: ${answer}" >&2
    stop_current "cycle-${cycle}-bad-response" || true
    exit 1
  fi
  postload_gpu="$(gpu_mem_json)"
  stop_current "cycle-${cycle}"
  jq \
    --argjson cycle "${cycle}" \
    --arg answer "${answer}" \
    --argjson postload_gpu "${postload_gpu}" \
    '.cycles += [{cycle:$cycle,answer:$answer,postload_gpu:$postload_gpu,status:"passed"}]' \
    "${RESULTS_DIR}/qualification.json" > "${RESULTS_DIR}/qualification.json.tmp"
  mv "${RESULTS_DIR}/qualification.json.tmp" "${RESULTS_DIR}/qualification.json"
done

cleanup
trap - EXIT
config_hash_after="$(sha256sum "${PROJECT_ROOT}/config/localllm-main.env" | cut -d' ' -f1)"
if [[ "${config_hash_after}" != "${config_hash_before}" ]]; then
  echo "Active config changed during qualification" >&2
  exit 1
fi
if [[ "${SAFETY_FAULT}" -ne 0 ]]; then
  exit 1
fi
jq \
  --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '. + {completed_at:$completed_at,status:"passed"}' \
  "${RESULTS_DIR}/qualification.json" > "${RESULTS_DIR}/qualification.json.tmp"
mv "${RESULTS_DIR}/qualification.json.tmp" "${RESULTS_DIR}/qualification.json"
printf '%s\n' "${RESULTS_DIR}"
