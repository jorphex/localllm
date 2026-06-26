# Ornith Quick Fit Plan

Goal: unload the current model stack, test the two new `models/ornith/` GGUFs for max VRAM-resident fit and quick PP/TG numbers, then restore a clean service state.

- [x] Stop managed model services and verify no resident `llama-server` processes remain.
- [x] Identify the two new Ornith model files and run scratch-only probes one model at a time.
- [x] Confirm q8-KV full-context VRAM fit for Q6 and Q5 without CPU tensor/KV spill.
- [x] Sweep the obvious batch knob at max context where safe.
- [x] Record the durable result in `NOTES.md`.
- [x] Restore the managed stack and verify health.
