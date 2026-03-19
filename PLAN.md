# Goal
- Validate the newly added replay and sandbox coverage across both active coding baselines, then clean up temporary capture artifacts and record only the current benchmark facts.

# Success Criteria
- The real OpenCode-derived transcript corpus is replayed against both `qwen-3.5-abl` and `omnicoder-9b`.
- The `soak_real` fixture is included in that replay pass and produces usable comparative output.
- The `command_denial_recovery` sandbox scenario is executed successfully on both `qwen-3.5-abl` and `omnicoder-9b`.
- Temporary capture trash is removed from the tree.
- `NOTES.md` records the real-corpus replay result, the long-session soak result, and the command-denial comparison result with no stale contradictions.

# Constraints
- Keep `qwen-3.5-abl` restored on `8091` at the end.
- Keep requests uncapped.
- Do not modify the generic harnesses in ways that regress the existing Qwen/OmniCoder baseline comparisons.

# Implementation Items
- [x] 1. Remove temporary transcript-capture artifacts and inspect the newly added replay files for anything that should not be retained.
- [x] 2. Run `ruff check --fix` and `ruff check` on the modified Python benchmark files.
- [x] 3. Run the real OpenCode-derived transcript corpus through `benchmarks/transcript_replay/run_compare.sh` for both `qwen-3.5-abl` and `omnicoder-9b`, including `soak_real`.
- [x] 4. Run the `command_denial_recovery` sandbox scenario through `benchmarks/sim_compare/run_compare.sh` for both `qwen-3.5-abl` and `omnicoder-9b`.
- [x] 5. Review the generated results, update `NOTES.md`, and confirm the tree state for the next commit.
