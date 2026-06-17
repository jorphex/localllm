# Goal
- Organize the current dirty localllm tree into coherent, verified commits without losing the completed Qwen 3.6 runtime work.

# Plan
- [x] Inspect the dirty tree and identify independent change groups.
- [x] Fix any documentation/config drift found during organization.
- [x] Run focused lint, syntax, unit, and service verification.
- [x] Stage and commit each coherent group with descriptive messages.
- [x] Confirm the final tree is clean and services remain healthy.

# Constraints
- Do not modify `/home/j/projects/openwendy`.
- Do not revert user or prior-session work while organizing.
- Keep commits scoped by behavior area rather than by file type alone.
- Do not stop running healthy production services solely for commit organization.
- For Python changes, run `ruff check --fix`, `ruff check`, and relevant compile/tests.

# Result
- Committed runtime/service changes as `3ccd85b Promote Qwen 3.6 service stack`.
- Committed benchmark tooling as `445c7c6 Add Qwen runtime benchmark tooling`.
- Committed generated social assets as `1494afb Add Qwen stack social assets`.
- Verification passed before commit organization: `ruff check --fix .`, `ruff check .`, shell syntax checks, `uv run python -m py_compile ...`, `pytest -q`, and `systemd-analyze --user verify systemd/*.service systemd/*.timer`.
