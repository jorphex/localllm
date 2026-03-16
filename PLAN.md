# Goal
- Tune the temporary `GLM` test load more rigorously by sweeping launch flags at a safe `-c 32768`, then raising context back up until idle headroom lands around `500 MiB`.

# Success Criteria
- Run a focused flag sweep at `-c 32768` to find a better `GLM` profile than the current scratch defaults if one exists.
- Re-sweep context with the best flag profile.
- Leave `GLM` loaded on `8091` at the tuned profile closest to the requested headroom target.

# Constraints
- Use a reduced context during the flag sweep so VRAM-fit artifacts do not dominate the comparison.
- Keep `GLM` as the active temporary test model after the work is done.
- Favor stable fit and practical responsiveness over marginal gains from risky settings.

# Implementation Items
- [x] 1. Sweep `GLM` launch flags at `-c 32768`.
- [x] 2. Pick the best tested flag profile.
- [x] 3. Re-sweep context on that profile to land near `500 MiB` free VRAM.
- [x] 4. Restart the temporary `GLM` load on `8091` with the tuned profile.
