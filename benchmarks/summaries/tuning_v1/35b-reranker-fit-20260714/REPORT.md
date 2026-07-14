# 35B Plus GPU Reranker Fit Study

Run: `35b-reranker-fit-20260714`

## Result

Both retained 35B models loaded at their maximum explicit GPU layer counts while the existing GPU reranker process remained resident and responsive. No CPU model-layer offload was required for the tested direct calls.

| Model | Placement | VRAM free start/end | Short PP | Long PP | Short TG | Long-context PP / TG |
|---|---:|---:|---:|---:|---:|---:|
| Qwen35 Unsloth | 41/41 GPU | 594 / 547 MiB | 356.7 | 326.6 | 50.7 | 305.5 / 25.1 |
| Qwen35 Huihui | 42/42 GPU | 120 / 88 MiB | 1810.4 | 825.6 | 123.5 | 749.6 / 39.4 |

Every workload has three repeats; all 24 direct trials passed. Long PP used 105,606 prompt tokens, and long-context recall used 118,820 prompt tokens.

## Comparison

Against the tuned Qwen27 Huihui direct baseline, co-resident Qwen35 Huihui was 2.52x faster in short PP, 1.92x in long PP, 2.35x in short TG, and 1.86x in long-context PP. Long-context TG was effectively tied at 1.02x.

Qwen35 Unsloth technically fit but lost its practical speed advantage under the same residency pressure.

## Boundary

This does not promote either 35B preset to shared-GPU production. Huihui finished with only 88 MiB of measured free VRAM, and the study did not overlap active main generation with active reranking or exercise vision. The existing exclusive-GPU preset policy remains the reliable default until those headroom cases are qualified.

The raw local evidence includes exact fixed `--gpu-layers` argv with `--fit off`, resource snapshots, reranker PID and latency checks, all trial metrics, server logs, and empty kernel-safety artifacts.
