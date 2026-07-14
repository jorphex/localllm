#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "post" ]]; then
  /usr/local/sbin/amdgpu-runtime-pm-guard --apply
fi
