#!/usr/bin/env bash
set -euo pipefail
"$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/load-main-preset.sh" glm-4.6v
