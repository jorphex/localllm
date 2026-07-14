# Runtime tuning study

## Goal

Publish the 2026-07-14 runtime-tuning campaign as a separate study without changing or blending the existing fair-profile Barrage results.

## Acceptance criteria

- Runtime data is generated from the compact `runtime-tuning-campaign-v1.0` summary through a site-owned normalizer.
- The site clearly distinguishes individually tuned profiles from fair-profile comparisons.
- Retained shapes, direct PP/TG metrics, corrected warm-cache evidence, validation totals, agent-harness A/B findings, and safety scope are visible.
- Private harness names, raw artifact paths, and internal digests are not published.
- Sandbox and concurrency are not implied to have been rerun.
- Desktop/mobile interactions and existing Barrage views continue to work.

## Constraints

- Do not modify benchmark sources, stack configuration, or raw result artifacts.
- Preserve unrelated worktree changes outside `site/`.
- Keep all evidence families separate and calculate no composite score.

## Steps

- [x] Add and verify the runtime-tuning normalization layer.
- [x] Add a distinct Runtime view using the existing evidence-bench visual system.
- [x] Add validation, correction, agent-harness decision, and safety context.
- [x] Update method/provenance and resolve the runtime-ingestion note.
- [x] Verify source fidelity, private-name scrubbing, responsive rendering, and regressions.
- [x] Commit and push only site-owned changes.
