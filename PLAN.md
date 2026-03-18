# Goal
- Clean up the rejected DeepSeek setup, move durable GGUF assets into a repo-local model store, promote the useful benchmark harnesses, and make model switching easy with stable preset scripts.

# Success Criteria
- Remove the DeepSeek model from disk and ensure it is no longer the active main service.
- Move durable GGUF files from the legacy cache path into `models/` under this repo and update runtime path discovery accordingly.
- Promote the useful `/tmp` harnesses into repo-managed `benchmarks/` or `tests/`.
- Replace hard-coded per-model service env in the main user unit with a repo-managed preset env file plus easy model-loader scripts.
- Restore `qwen-3.5-abl` with the tuned profile and document the current model/tuning findings in `README.md` and `NOTES.md`.

# Constraints
- Keep only the remaining useful presets: `qwen-3.5`, `qwen-3.5-abl`, and `glm-4.6v`.
- Do not leave multiple GPU-backed chat models loaded at the same time.
- Use the existing benchmark findings as the source of truth for tuned launch args.

# Implementation Items
- [x] 1. Stop the current main service, delete DeepSeek, move the remaining GGUF files into `models/`, and update model path discovery.
- [x] 2. Promote the most useful `/tmp` harnesses into repo-managed benchmarks or tests.
- [x] 3. Add preset env files and loader scripts that stop the current main service before switching models.
- [x] 4. Update `README.md`, `NOTES.md`, and the relevant service/launch scripts with the tuned presets and benchmark findings.
- [x] 5. Start `qwen-3.5-abl`, verify health, and report the cleanup plus the remembered `Qwen3-Coder-30B-A3B` result.
