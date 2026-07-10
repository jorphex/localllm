# Benchmark Barrage V2 Review Remediation

Goal: remove the grading, provenance, and reporting weaknesses found in the post-implementation review without touching `site/` or unrelated live-stack work.

Criteria:
- OpenWendy grading proves a completed named tool event and final assistant answer, not prompt/tool-output text.
- OpenWendy harness identity changes for committed, modified, staged, or untracked active source and records the selected model profile without exposing command secrets.
- Production applies core/holdout selection and quality repeats, retains pass/fail/split counts, and publishes those outcomes visibly.
- Fair fallback evidence requires a full model-sized GPU residency delta and describes the remaining inference limitation accurately.
- Warm-cache trials retain both prime and append evidence; restraint requires a non-empty answer.
- Regression coverage exercises each previous false-positive path, real fair and production smokes complete, all checks pass, and only benchmark-owned changes are committed.

Out of scope:
- Modifying OpenWendy itself, its configuration, or `site/`.
- Combining fair and production rankings.

- [x] Make OpenWendy task evaluation event-type aware and add adversarial evaluator tests.
- [x] Fingerprint dirty/untracked OpenWendy source, bind the adapter to the requested candidate profile, and record non-secret driver metadata.
- [x] Apply production core/holdout filtering and quality repeats; preserve/publish pass and split outcomes.
- [x] Tighten fair GPU residency validation and retain complete warm-cache/contract evidence.
- [x] Update docs/results rendering and regression coverage for all remediation behavior.
- [x] Run focused and full verification plus real fair and OpenWendy production smokes; inspect artifacts and restore service health.
- [x] Commit only the remediation sources, tests, docs, and compact summaries; leave unrelated worktree changes untouched.
