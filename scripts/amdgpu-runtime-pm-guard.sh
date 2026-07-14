#!/usr/bin/env bash
set -euo pipefail

mode="${1:---apply}"
sysfs_root="${AMDGPU_SYSFS_ROOT:-/sys}"
driver_dir="${sysfs_root}/bus/pci/drivers/amdgpu"

if [[ "${mode}" != "--apply" && "${mode}" != "--check" ]]; then
  echo "Usage: $0 [--apply|--check]" >&2
  exit 2
fi
if [[ ! -d "${driver_dir}" ]]; then
  echo "AMDGPU PCI driver directory is missing: ${driver_dir}" >&2
  exit 1
fi

shopt -s nullglob
devices=("${driver_dir}"/[[:xdigit:]][[:xdigit:]][[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]]:[[:xdigit:]][[:xdigit:]].[[:xdigit:]])
shopt -u nullglob
if (( ${#devices[@]} == 0 )); then
  echo "No PCI devices are bound to the AMDGPU driver under ${driver_dir}" >&2
  exit 1
fi

for device in "${devices[@]}"; do
  control="${device}/power/control"
  runtime_status="${device}/power/runtime_status"
  pci_id="$(basename "${device}")"
  if [[ ! -r "${control}" ]]; then
    echo "AMDGPU ${pci_id} power control is not readable: ${control}" >&2
    exit 1
  fi
  if [[ "${mode}" == "--apply" ]]; then
    if [[ ! -w "${control}" ]]; then
      echo "AMDGPU ${pci_id} power control is not writable: ${control}" >&2
      exit 1
    fi
    printf 'on' > "${control}"
  fi
  if [[ "$(<"${control}")" != "on" ]]; then
    echo "AMDGPU ${pci_id} runtime power control is not pinned to on" >&2
    exit 1
  fi
  if [[ ! -r "${runtime_status}" || "$(<"${runtime_status}")" != "active" ]]; then
    echo "AMDGPU ${pci_id} runtime status is not active" >&2
    exit 1
  fi
  printf 'AMDGPU %s runtime power: on/active\n' "${pci_id}"
done
