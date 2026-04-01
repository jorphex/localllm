#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"

for preset_file in "${PROJECT_ROOT}"/config/presets/main-*.env; do
  [[ -e "${preset_file}" ]] || continue
  preset_name="$(basename "${preset_file}")"
  preset_name="${preset_name#main-}"
  preset_name="${preset_name%.env}"
  alias_line="$(grep '^MAIN_ALIAS=' "${preset_file}" | head -n1 | cut -d= -f2-)"
  model_line="$(grep '^MAIN_MODEL=' "${preset_file}" | head -n1 | cut -d= -f2-)"
  context_line="$(grep '^MAIN_CONTEXT=' "${preset_file}" | head -n1 | cut -d= -f2-)"
  status_line="$(preset_file_status "${preset_file}")"
  printf '%s\tstatus=%s\talias=%s\tcontext=%s\tmodel=%s\n' "${preset_name}" "${status_line}" "${alias_line}" "${context_line}" "${model_line}"
done
