#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

TTS_VENV="${TTS_VENV:-${HOME}/.venvs/omnivoice-rocm}"
TTS_PYTHON="${TTS_PYTHON:-${TTS_VENV}/bin/python}"

if [[ ! -x "${TTS_PYTHON}" ]]; then
  echo "Missing OmniVoice Python runtime: ${TTS_PYTHON}" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"
exec "${TTS_PYTHON}" "${PROJECT_ROOT}/scripts/omnivoice_server.py"
