#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_ENV_FILE="${PROJECT_ROOT}/config/localllm-runtime.env"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/set-runtime-backend.sh <hip|vulkan|cuda>

Writes the persistent local runtime selector used by repo launcher scripts.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
  usage
  exit $([[ $# -eq 1 ]] && echo 0 || echo 1)
fi

case "$1" in
  hip)
    backend="hip"
    device="ROCm0"
    ;;
  vulkan)
    backend="vulkan"
    device="Vulkan0"
    ;;
  cuda)
    backend="cuda"
    device="CUDA0"
    ;;
  *)
    echo "Unknown backend: $1" >&2
    usage >&2
    exit 1
    ;;
esac

cat > "${RUNTIME_ENV_FILE}" <<EOF
LOCALLLM_RUNTIME_BACKEND=${backend}
LOCALLLM_RUNTIME_DEVICE=${device}
EOF

echo "Runtime backend set to ${backend} (${device})"
