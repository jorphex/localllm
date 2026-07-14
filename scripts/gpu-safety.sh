#!/usr/bin/env bash

GPU_SAFETY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GPU_SAFETY_PM_GUARD="${GPU_SAFETY_PM_GUARD:-${GPU_SAFETY_DIR}/amdgpu-runtime-pm-guard.sh}"
GPU_SAFETY_STABILIZE_SECONDS="${GPU_SAFETY_STABILIZE_SECONDS:-30}"
GPU_SAFETY_PATTERN='refcount_t:.*underflow|use-after-free|kernel BUG|BUG:|Oops:|general protection fault|amdgpu.*(ring[^[:space:]]*.*timeout|GPU reset|GPU fault|page fault|runtime (suspend|resume).*(fail|error)|device lost)|DeviceLost|pm_runtime_work hogged|soft lockup|hard LOCKUP|watchdog: BUG|blocked for more than [0-9]+ seconds|hung task'

GPU_SAFETY_INHIBITOR_PID=""
GPU_SAFETY_JOURNAL_PID=""
GPU_SAFETY_READER_PID=""
GPU_SAFETY_FIFO=""
GPU_SAFETY_SENTINEL=""

gpu_safety_assert_pm() {
  "${GPU_SAFETY_PM_GUARD}" --check
}

gpu_safety_capture_cursor() {
  local cursor
  cursor="$(journalctl -b -k -n 1 -o json --no-pager | jq -er '.__CURSOR')" || {
    echo "Could not capture a current-boot kernel journal cursor" >&2
    return 1
  }
  printf '%s\n' "${cursor}"
}

gpu_safety_filter_faults() {
  grep -Eai "${GPU_SAFETY_PATTERN}"
}

gpu_safety_assert_clean_boot() {
  local output_file="${1:-}"
  local faults
  faults="$(journalctl -b -k -o short-iso-precise --no-pager | gpu_safety_filter_faults || true)"
  if [[ -n "${output_file}" ]]; then
    printf '%s' "${faults}" > "${output_file}"
  fi
  if [[ -n "${faults}" ]]; then
    echo "Current boot contains a fatal GPU/kernel safety pattern" >&2
    printf '%s\n' "${faults}" >&2
    return 1
  fi
}

gpu_safety_scan_after_cursor() {
  local cursor="$1"
  local output_file="${2:-}"
  local faults
  faults="$(journalctl -b -k --after-cursor "${cursor}" -o short-iso-precise --no-pager | gpu_safety_filter_faults || true)"
  if [[ -n "${output_file}" ]]; then
    printf '%s' "${faults}" > "${output_file}"
  fi
  if [[ -n "${faults}" ]]; then
    echo "New fatal GPU/kernel safety pattern detected" >&2
    printf '%s\n' "${faults}" >&2
    return 1
  fi
}

gpu_safety_start_inhibitor() {
  local -a inhibit_command=(systemd-inhibit)
  if [[ -n "${GPU_SAFETY_INHIBITOR_PID}" ]]; then
    echo "Sleep inhibitor is already active" >&2
    return 1
  fi
  if sudo -n true >/dev/null 2>&1; then
    inhibit_command=(sudo -n systemd-inhibit)
  fi
  setsid "${inhibit_command[@]}" \
    --what=sleep:idle \
    --mode=block \
    --who=localllm-benchmark \
    --why="Guarded local LLM benchmark" \
    sleep infinity &
  GPU_SAFETY_INHIBITOR_PID=$!
  sleep 1
  if ! kill -0 "${GPU_SAFETY_INHIBITOR_PID}" 2>/dev/null; then
    echo "Could not acquire the benchmark sleep inhibitor" >&2
    GPU_SAFETY_INHIBITOR_PID=""
    return 1
  fi
}

gpu_safety_stop_inhibitor() {
  if [[ -n "${GPU_SAFETY_INHIBITOR_PID}" ]]; then
    kill -TERM -- "-${GPU_SAFETY_INHIBITOR_PID}" 2>/dev/null || true
    wait "${GPU_SAFETY_INHIBITOR_PID}" 2>/dev/null || true
    GPU_SAFETY_INHIBITOR_PID=""
  fi
}

gpu_safety_start_monitor() {
  local cursor="$1"
  local target_pgid="$2"
  local artifact_dir="$3"
  if [[ -n "${GPU_SAFETY_JOURNAL_PID}" || -n "${GPU_SAFETY_READER_PID}" ]]; then
    echo "Kernel journal monitor is already active" >&2
    return 1
  fi
  mkdir -p "${artifact_dir}"
  GPU_SAFETY_FIFO="${artifact_dir}/kernel-monitor.fifo"
  GPU_SAFETY_SENTINEL="${artifact_dir}/kernel-fault.log"
  rm -f "${GPU_SAFETY_FIFO}" "${GPU_SAFETY_SENTINEL}"
  mkfifo "${GPU_SAFETY_FIFO}"
  journalctl -b -k -f --after-cursor "${cursor}" -o short-iso-precise --no-pager > "${GPU_SAFETY_FIFO}" &
  GPU_SAFETY_JOURNAL_PID=$!
  (
    while IFS= read -r line; do
      if grep -Eaiq "${GPU_SAFETY_PATTERN}" <<< "${line}"; then
        printf '%s\n' "${line}" >> "${GPU_SAFETY_SENTINEL}"
        kill -TERM -- "-${target_pgid}" 2>/dev/null || true
        sleep 5
        kill -KILL -- "-${target_pgid}" 2>/dev/null || true
        break
      fi
    done < "${GPU_SAFETY_FIFO}"
  ) &
  GPU_SAFETY_READER_PID=$!
}

gpu_safety_stop_monitor() {
  [[ -z "${GPU_SAFETY_JOURNAL_PID}" ]] || kill "${GPU_SAFETY_JOURNAL_PID}" 2>/dev/null || true
  [[ -z "${GPU_SAFETY_READER_PID}" ]] || kill "${GPU_SAFETY_READER_PID}" 2>/dev/null || true
  [[ -z "${GPU_SAFETY_JOURNAL_PID}" ]] || wait "${GPU_SAFETY_JOURNAL_PID}" 2>/dev/null || true
  [[ -z "${GPU_SAFETY_READER_PID}" ]] || wait "${GPU_SAFETY_READER_PID}" 2>/dev/null || true
  [[ -z "${GPU_SAFETY_FIFO}" ]] || rm -f "${GPU_SAFETY_FIFO}"
  GPU_SAFETY_JOURNAL_PID=""
  GPU_SAFETY_READER_PID=""
  GPU_SAFETY_FIFO=""
}

gpu_safety_monitor_clean() {
  if [[ -n "${GPU_SAFETY_SENTINEL}" && -s "${GPU_SAFETY_SENTINEL}" ]]; then
    echo "Kernel journal monitor detected a fatal safety pattern: ${GPU_SAFETY_SENTINEL}" >&2
    return 1
  fi
}

gpu_safety_stabilize() {
  local cursor="$1"
  local output_file="${2:-}"
  local seconds="${3:-${GPU_SAFETY_STABILIZE_SECONDS}}"
  sleep "${seconds}"
  gpu_safety_assert_pm
  gpu_safety_scan_after_cursor "${cursor}" "${output_file}"
}

gpu_safety_cleanup() {
  gpu_safety_stop_monitor
  gpu_safety_stop_inhibitor
}
