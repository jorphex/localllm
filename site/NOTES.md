# Current

[Site state] evidence bench is the sole production direction — four Qwen 3.6 Q6_K builds are presented across fair-profile readout, performance, tools, sandbox, concurrency, and vision views, with a separate model-specific runtime tuning study and shared method view.

[Verification baseline] current four-model and runtime-tuning data is source-faithful and responsive — Chromium passed all eight views at desktop/mobile sizes without console errors or viewport overflow; runtime table selection updates the shared model selector without layout shift.

# Future

[Fifth model] planned — derive model counts and release copy from data, generate task-matrix columns dynamically, extend chart color/pattern assignment beyond four series, and let the top selector wrap or scroll.

[Seven to eight models] planned if reached — retain all-model display, make wide task matrices deliberately horizontally scrollable, and add chart-series visibility toggles.

[More than eight models] deferred until needed — consider a compact model picker or user-selected comparison subset only after the all-model view becomes demonstrably difficult to use.

[Historical runs] deferred until needed — add run navigation only when multiple past runs remain important enough to browse; Git history is sufficient for now.

[Long model names] planned when encountered — introduce compact display aliases while preserving full model, finetuner, and quantization names in detail/provenance views.

# Durables

[Site purpose] public research archive — prioritize scanability, comparison, provenance, and generosity of detail over promotion, persuasion, or article-style presentation.

[Information architecture] evidence families stay separate — never collapse performance, tools, sandbox, concurrency, vision, or bespoke agent-harness results into a composite score.

[Release semantics] failed qualification is not a crashed run — it means at least one strict release requirement was missed.

[Data boundary] `data/barrage-v2.json` is generated display data — use `summary.json` as the canonical structured source, benchmark results for editorial context, and README definitions for semantics; never ingest raw barrage result artifacts.

[Repository boundary] the repository root produces and validates stack evidence while `site/` owns normalization and presentation — consume compact summaries from `../benchmarks/summaries/`, keep schema adapters inside `site/`, and do not modify stack configs or benchmark source artifacts from frontend work.

[Normalization workflow] future summaries should pass through `node scripts/normalize-benchmark.mjs <source> <destination>` — keep page components decoupled from the nested benchmark schema.

[Runtime tuning study] model-specific retained profiles are a separate evidence lane — generate `data/runtime-tuning-v1.json` with `scripts/normalize-runtime-tuning.mjs`, show direct PP/TG and validation evidence, preserve raw-versus-derived correction context, and never imply sandbox or concurrency were rerun.

[Provenance] show only verified evidence — GPU identity/capacity comes from benchmark results, runtime fields from the canonical summary, and CPU topology plus installed RAM from direct inspection of the benchmark host.

[Public terminology] private project names stay out of the site — describe non-public production testing generically as a bespoke agent harness.

[Visual direction] precision workshop readout — cool instrument-gray surfaces, dense readable data, restrained orange selection state, and color used to explain evidence rather than decorate it.

# Lessons

[Scaling] separate visual capacity from structural capacity — the selector can look acceptable with six or eight models while fixed grid columns, chart palettes, and hard-coded counts already fail at model five.

[Scope discipline] prefer the smallest proven expansion — do not build a model-library product, pinned comparisons, or run archive before actual data volume requires them.

[Evaluation] direct browser tests and synthetic datasets outrank framework-generated design prescriptions — retain concrete failures and discard ceremony that does not improve the site.

[Design tooling] Impeccable critique output is not project state — do not generate or retain its critique artifacts for this site.
