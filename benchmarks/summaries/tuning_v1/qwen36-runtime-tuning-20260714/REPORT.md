# Qwen3.6 Runtime Tuning V1

Generated: 2026-07-14T05:48:28.382543+00:00

## Direct Validation

- Primary tuning: 536/539 attempted trials produced valid measurements.
- Controls: 140/140 measured trials.
- The three primary failures are expected unsupported-MTP startups for 35B Unsloth.

| Model | Context | Shape | Long PP | Deterministic TG | Sampled TG | Tool TG |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `qwen27-unsloth` | 131072 | b2048/u1024, t12/tb12, draft-mtp n4 | 433.89 | 46.99 | 52.08 | 73.85 |
| `qwen27-huihui` | 131072 | b2048/u1024, t10/tb8, draft-mtp n4 | 430.07 | 52.58 | 55.23 | 76.47 |
| `qwen35-unsloth` | 163840 | b4096/u2048, t10/tb8, none n0 | 1336.89 | 97.60 | 103.36 | 105.28 |
| `qwen35-huihui` | 262144 | b1024/u512, t10/tb8, draft-mtp n3 | 868.80 | 75.34 | 78.75 | 98.32 |

## Barrage

| Model | Performance | Tool | Vision |
| --- | ---: | ---: | ---: |
| `qwen27-unsloth` | 50/50 | 15/15 | 3/3 |
| `qwen27-huihui` | 50/50 | 15/15 | 3/3 |
| `qwen35-unsloth` | 50/50 | 15/15 | 3/3 |
| `qwen35-huihui` | 50/50 | 15/15 | 3/3 |

35B Unsloth is shown with the corrected ubatch-aware warm-cache interpretation; its five raw failures are retained and documented in JSON.

## OpenWendy Attribution

| Arm | Task pass | Median elapsed |
| --- | ---: | ---: |
| `current` | 12/21 | 77.03s |
| `finalist` | 12/21 | 97.08s |

Decision: retain `n2/t10/tb8`. The finalist was 26.0% slower by median and did not improve task outcomes.

Common harness finding: Both arms made every expected calculation tool call with correct arguments and output, but OpenWendy completed those tasks with an empty final answer.

## Safety And Scope

- Post-lock runs used pinned AMDGPU runtime PM, a root sleep inhibitor, continuous kernel monitoring, and 30-second unload/load stabilization.
- All guarded completion and kernel artifacts are clean, and the production env was restored byte-for-byte.
- Wrong-filename and lock-interrupted 35B directories are explicitly excluded.
- Raw prompts, responses, transcripts, and generated media are not published here.
