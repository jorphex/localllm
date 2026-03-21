# Goal
- Normalize the actual model filenames to a single `model-quant-provider.extension` scheme, update runtime references, reload the Gemini 9B preset, and preserve a concise evaluation summary for the compared Qwen 9B variants.

# Success Criteria
- On-disk model and projector filenames follow the requested convention.
- Presets, launchers, benchmark defaults, and docs point at the normalized names.
- `qwen-3.5-g` reloads successfully on the normalized Gemini file pair.
- The rename outcome and provider naming choice are recorded in `NOTES.md`.

# Constraints
- Do not touch unrelated worktree changes.
- Keep provider naming explicit even when the original file lacked one.

# Out Of Scope
- Re-running the benchmark suites.
- Editing historical benchmark artifacts.

# Implementation Items
- [x] 1. Normalize the on-disk model and projector filenames.
- [x] 2. Patch presets, launchers, benchmark defaults, and docs to the normalized names.
- [x] 3. Reload `qwen-3.5-g` and verify the live path resolves to the renamed Gemini files.
- [x] 4. Record the rename outcome and caveats in `NOTES.md`.
- [x] 5. Prepare a commit containing only the rename-normalization changes.
