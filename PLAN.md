# Goal
- Stage the new 4B web-dev candidates as CPU-only side models while keeping `qwen-3.5-abl` live on GPU.

# Success Criteria
- The practical `Q4_K_M` artifacts for both web-dev candidates are downloaded into `models/`.
- `qwen-3.5-abl` remains live on `8091`.
- Each candidate has a tuned CPU-only launch profile based on live probes.
- Both candidates are loaded simultaneously on separate ports in CPU-only mode.
- `NOTES.md` records the corrected ports, profiles, and behavioral differences with no stale GPU-side contradiction.

# Constraints
- Keep Qwen on GPU.
- Optimize the side models for concurrent CPU residency instead of isolated single-model peak numbers.

# Implementation Items
- [x] 1. Inspect the two Hugging Face repos and identify the intended `Q4_K_M` artifacts.
- [x] 2. Download both `Q4_K_M` checkpoints into `models/` and verify they landed intact.
- [x] 3. Sweep CPU-only thread, context, and batch settings to find practical side-model profiles.
- [x] 4. Restore Qwen on `8091`, load both tuned CPU-only models on separate ports, and record the final state in `NOTES.md`.
