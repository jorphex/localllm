# Goal
- Harden the preset launcher path and the benchmark default entrypoints so they stay correct after model pruning and are less brittle ahead of the GPU swap.

# Success Criteria
- Loading a preset does not clobber the active config before basic validation.
- The active preset inventory only exposes retained 9B presets by default.
- Benchmark compare/barrage defaults no longer assume deleted models or capped reasoning budgets.
- Verification confirms the retained presets still load correctly.

# Constraints
- Keep changes minimal and structural.
- Do not rerun full benchmarks as part of this hardening pass.

# Out Of Scope
- Rewriting broader docs.
- Re-benchmarking every retained model again.

# Implementation Items
- [completed] 1. Audit launcher and benchmark scripts for stale assumptions.
- [completed] 2. Patch preset loading to validate safely and avoid leaving the service on a broken active preset.
- [completed] 3. Retarget benchmark defaults and compare surfaces to the retained 9B set.
- [completed] 4. Verify syntax, preset listing, and a real retained-preset reload.
