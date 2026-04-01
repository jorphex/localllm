#!/usr/bin/env bash
set -euo pipefail
echo "load-qwen-3.5.sh is the Unsloth shortcut; use load-main-preset.sh qwen-3.5-abl or qwen-3.5-g for the other retained 9B presets." >&2
"$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/load-main-preset.sh" qwen-3.5
