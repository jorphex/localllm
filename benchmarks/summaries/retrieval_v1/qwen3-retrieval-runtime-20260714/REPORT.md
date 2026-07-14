# Qwen3 Retrieval Runtime Tuning

The embedding service was promoted from one CPU slot at `t8/tb4/b128/ub128` to eight CPU slots at `t12/tb12/b1024/ub1024`. Total server context is 16384, preserving 2048 tokens for each request slot.

For the OpenWendy-shaped eight-item workload, median latency fell from 14.52 seconds to 0.163 seconds, an 89.4x speedup. A 32-item backfill improved from 61.75 seconds to 25.00 seconds. Single-query latency remained effectively flat. All six semantic top-result cases passed, and the minimum vector cosine against the single-slot baseline was 0.9981. An independent exploratory run reproduced the latency result.

The GPU reranker remains unchanged at one slot, `t8/tb4/b512/ub512`, and flash attention on. A nominal `t12/tb12` sweep win disappeared in confirmation: current measured 0.15896 seconds for eight documents versus 0.15924 seconds for the finalist. Flash attention off and alternate batch sizes were slower or tied.

Parallel reranker slots were rejected. Quality fell from 4/6 top results at one slot to 1/6 at two slots and 0/6 at four slots, while VRAM increased and latency did not materially improve. The 4/6 baseline is a model-quality observation from this small synthetic corpus, not a normalized public retrieval score.

All disruptive runs used the AMDGPU runtime-PM guard, sleep inhibitor, live kernel monitor, and 30-second transition stabilization. No fatal kernel pattern was detected, and the normal four-service stack was restored healthy.
