#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
model_id="${1:-}"
results_dir="${2:-}"

if [[ -z "${model_id}" || -z "${results_dir}" ]]; then
  echo "Usage: $0 MODEL_ID RESULTS_DIR" >&2
  exit 2
fi

case "${model_id}" in
  qwen35-unsloth)
    candidate='q35-unsloth-nospec|qwen-3.6/Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf|qwen-3.6/Qwen3.6-35B-A3B-mmproj-F16-unsloth.gguf'
    profile_id='tuning-v1-q35-unsloth-nospec'
    context=163840
    threads=10
    extra_args='-v -np 1 -tb 8 -b 4096 -ub 2048 -fa on --threads-http 4 -ctk q8_0 -ctv q8_0 -rea on --metrics --no-warmup --image-max-tokens 8192 --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0.0 --presence-penalty 0.0 --repeat-penalty 1.0 --ctx-checkpoints 8'
    ;;
  qwen35-huihui)
    candidate='q35-huihui-n3|qwen-3.6/Huihui-Qwen3.6-35B-A3B-abliterated-MTP-Q6_K.gguf|qwen-3.6/Huihui-Qwen3.6-35B-A3B-abliterated-MTP-mmproj-f16.gguf'
    profile_id='tuning-v1-q35-huihui-n3'
    context=262144
    threads=10
    extra_args='-v -np 1 -tb 8 -b 1024 -ub 512 -fa on --threads-http 4 -ctk q8_0 -ctv q8_0 -rea on --metrics --no-warmup --image-max-tokens 8192 --temp 0.6 --top-k 20 --top-p 0.95 --min-p 0.0 --presence-penalty 0.0 --repeat-penalty 1.0 --spec-type draft-mtp --spec-draft-n-max 3 --ctx-checkpoints 8'
    ;;
  *)
    echo "Unsupported finalist model: ${model_id}" >&2
    exit 2
    ;;
esac

exec env \
  BARRAGE_V2_CANDIDATES="${candidate}" \
  BARRAGE_V2_PROFILE_CLASS=production \
  BARRAGE_V2_PROFILE_ID="${profile_id}" \
  BARRAGE_V2_CONTEXT="${context}" \
  BARRAGE_V2_EXTRA_ARGS="${extra_args}" \
  BENCH_THREADS="${threads}" \
  BARRAGE_V2_CACHE_PROMPT=true \
  BARRAGE_V2_CACHE_RAM=2048 \
  BARRAGE_V2_CACHE_REUSE=0 \
  BARRAGE_V2_SLOT_PROMPT_SIMILARITY=0.1 \
  BARRAGE_V2_COOLDOWN_SECONDS=30 \
  BARRAGE_V2_MAX_BASELINE_VRAM_MIB=1024 \
  BARRAGE_V2_REPEATS=5 \
  BARRAGE_V2_QUALITY_REPEATS=3 \
  BARRAGE_V2_SUITES=performance,tool_contract,vision \
  BARRAGE_V2_RESULTS_DIR="${results_dir}" \
  uv run bash "${PROJECT_ROOT}/benchmarks/run_barrage_v2.sh"
