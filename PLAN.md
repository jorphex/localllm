# Goal
- Remove the failed WEBGEN/UIGEN web-dev trial cleanly so the repo and host state only reflect models that are still in use.

# Success Criteria
- The WEBGEN and UIGEN sidecar servers are no longer running.
- Both WEBGEN/UIGEN GGUF files are deleted.
- `NOTES.md` no longer describes WEBGEN/UIGEN as currently staged.
- `README.md` contains no stale WEBGEN/UIGEN guidance.

# Constraints
- Keep `qwen-3.5-abl` live on `8091`.
- Remove only the WEBGEN/UIGEN trial artifacts and stale notes.

# Implementation Items
- [x] 1. Stop the WEBGEN/UIGEN sidecar servers on `9541` and `9542`.
- [x] 2. Delete both WEBGEN/UIGEN GGUF files from `models/`.
- [x] 3. Remove or replace stale WEBGEN/UIGEN notes so `NOTES.md` matches the current host state.
- [x] 4. Confirm `README.md` has no WEBGEN/UIGEN mentions and leave Qwen running on `8091`.
