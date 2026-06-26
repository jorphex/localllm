#!/usr/bin/env bash
# shellcheck disable=SC1091
# Shared benchmark configuration loader.
# Source this file after sourcing benchmarks/common.sh (or any script that sets
# PROJECT_ROOT and PYTHONPATH).

BENCHMARK_CONFIG_PY="${BENCHMARK_DIR}/config.py"

require_benchmark_config() {
  if [[ ! -f "${BENCHMARK_CONFIG_PY}" ]]; then
    echo "Missing ${BENCHMARK_CONFIG_PY}" >&2
    exit 1
  fi
}

benchmark_server_extra_args() {
  require_benchmark_config
  python3 - <<'PY'
import sys
sys.path.insert(0, "${PROJECT_ROOT}")
from benchmarks.config import server_extra_args
print(server_extra_args())
PY
}

benchmark_default_context() {
  require_benchmark_config
  python3 - <<'PY'
import sys
sys.path.insert(0, "${PROJECT_ROOT}")
from benchmarks.config import default_context
print(default_context())
PY
}

benchmark_suite_items() {
  local suite="$1"
  require_benchmark_config
  python3 - <<'PY' "${suite}"
import sys
sys.path.insert(0, "${PROJECT_ROOT}")
from benchmarks.config import suite_items
print("\n".join(suite_items(sys.argv[1])))
PY
}
