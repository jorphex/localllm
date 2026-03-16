# Goal
- Cut `localllm` over from the current `noctrex` Qwen3-VL-8B `Thinking` package to the `mradermacher` Qwen3-VL-8B `Thinking` package with `mmproj-Q8_0`, retune the live context/flags for the 10 GB RTX 3080, remove obsolete model files, update docs, and commit the result.

# Success Criteria
- Repo defaults and the live main service point at the `mradermacher` `Thinking` model plus `mmproj-Q8_0`.
- A direct host sweep confirms the best live context target for this package on the current GPU.
- Requested obsolete model files are removed from the cache.
- `README.md` documents the new default package and the tuned context.
- `NOTES.md` records the cutover result and the chosen tuning point.
- A git commit captures the change.

# Constraints
- Keep the embedding service unchanged.
- Preserve the existing reasoning-first behavior and notes about `<think>` normalization.
- Prefer the highest context that still leaves practical VRAM headroom and acceptable probe behavior on this host.

# Implementation Items
- [x] 1. Update model defaults to the `mradermacher` `Thinking` package and sweep around the new context ceiling.
- [x] 2. Apply the chosen live tuning, restart the main service, and verify `/health`, `/props`, and a direct reasoning probe.
- [x] 3. Remove the requested obsolete model files from the cache.
- [x] 4. Update `README.md` and `NOTES.md` with the new default package and tuning result.
- [ ] 5. Commit the cutover.
