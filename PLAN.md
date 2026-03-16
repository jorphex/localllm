# Goal
- Find the highest practical context and GPU-offload split for `Huihui-Qwen3-VL-8B-Thinking-abliterated` on this RTX 3080 while preserving a small VRAM safety margin and basic response stability, then set the live main service to that result and document it.

# Success Criteria
- A sweep tests multiple context sizes and relevant manual GPU-layer settings.
- The chosen profile leaves roughly `300` to `500 MiB` free on the GPU when idle, or the closest stable result if none hits that band.
- The chosen profile both loads and completes a tiny direct reasoning probe cleanly.
- The live `localllm-main.service` is restored on the selected profile.
- `README.md` and `NOTES.md` reflect the final tuning decision.

# Constraints
- Keep the embedding service unchanged.
- Prefer empirical stability over maximizing context at any cost.
- Do not leave the live service on a profile that only barely loads but fails basic completions.

# Implementation Items
- [x] 1. Sweep context and GPU-layer combinations on a temporary main-server launch while the live main service is stopped.
- [x] 2. Pick the best stable profile based on free VRAM and direct probe behavior.
- [x] 3. Apply the chosen profile to the live defaults and restart the main service.
- [x] 4. Update `README.md` and `NOTES.md` with the verified result.
