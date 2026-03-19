# Goal
- Build and prove the four missing benchmark areas: bad-first-patch recovery, tool-error recovery, legitimate two-file fixes, and fixture-driven transcript replay.

# Success Criteria
- The sandbox suite contains explicit scenarios for all three missing sandbox behaviors.
- The harness supports tool-error recovery without crashing.
- A transcript replay harness exists under `benchmarks/` and runs a saved fixture end to end.
- The new scenarios and replay harness are executed on the Qwen baseline as proof.
- `NOTES.md` reflects the new harness coverage and any lessons from the proof runs.

# Constraints
- One GPU-backed chat model at a time.
- Stop both managed and scratch `8091` servers before scratch benchmark runs.
- Keep requests uncapped unless a benchmark explicitly exists to study thinking-budget behavior.

# Implementation Items
- [x] 1. Inspect the current sandbox fixture repo, scenario definitions, and compare harnesses to place the new scenario types and replay harness cleanly.
- [x] 2. Implement the three new sandbox scenario classes: forced failed-first-patch recovery, tool-error recovery, and legitimate two-file fix, including fixture code/tests and any harness trigger support they need.
- [x] 3. Build a transcript replay harness that can run saved OpenCode-style transcript fixtures against a candidate model and validate it on at least one repo fixture transcript.
- [x] 4. Run syntax/lint checks plus dry runs, fix harness defects, then execute the new scenarios and replay harness on the baseline model for proof.
- [x] 5. Update `NOTES.md` and `PLAN.md` with the new harness coverage and any lessons from validation.
