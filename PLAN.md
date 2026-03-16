# Goal
- Benchmark a small set of `llama.cpp` flag variants around the current `mradermacher` Qwen3-VL-8B `Thinking` live profile to improve response speed without breaking fit, reasoning behavior, or the chosen `69120` context.

# Success Criteria
- A baseline measurement is captured for the current live profile.
- A small set of plausible flag variants is measured on the same host and prompt shape.
- If a variant is clearly better and still stable, the live service is updated to use it.
- `README.md` and `NOTES.md` record the final tuning decision.

# Constraints
- Keep the same model, projector, and `69120` context unless a flag-only change proves insufficient.
- Keep the embedding service unchanged.
- Prefer direct host measurements over theoretical wins.

# Implementation Items
- [x] 1. Capture the current baseline and identify the most plausible speed-sensitive flags to test.
- [x] 2. Benchmark a small flag matrix on temporary launches with the live service stopped.
- [x] 3. Apply the best stable profile if it beats the current baseline.
- [x] 4. Update `README.md`, `NOTES.md`, and this plan with the result.
