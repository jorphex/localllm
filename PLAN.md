# Benchmark Barrage V2 Evidence Remediation

Goal: resolve the remaining false-confidence findings in fair GPU validation and live OpenWendy production evidence.

Criteria:
- Fair runs prove every logged tensor layer is GPU-assigned under verbose llama.cpp logging; aggregate VRAM is retained only as supporting evidence.
- OpenWendy production runs identify the listener process, reject services older than the active source tree, and record non-secret live-process identity.
- OpenWendy calculation tasks require a completed named tool event with expected typed arguments and exact tool output, plus final answer text.
- Raw artifacts retain the matching tool evidence; compact summaries remain non-sensitive and visibly graded.
- Regression tests cover CPU-layer rejection, stale-service rejection, exact tool evidence, and all existing V2 checks; fair and production live validation is run when the service freshness gate permits it.

Out of scope:
- Editing OpenWendy source/configuration or `site/`.
- Restarting a potentially active OpenWendy service without explicit user direction.
- Combining fair and production rankings.

- [x] Add verbose fair-server tensor-assignment evidence and reject missing/CPU assignments.
- [x] Add OpenWendy live-process/source-freshness identity validation and metadata.
- [x] Upgrade calculation task contracts and evaluator evidence to arguments/output-aware scoring.
- [x] Expand tests, docs, and result publishing for the stronger evidence contract.
- [x] Run full verification, fair smoke, and a production freshness-gate validation; inspect artifacts and health.
- [x] Commit only benchmark-owned remediation files and leave unrelated worktree changes untouched.
