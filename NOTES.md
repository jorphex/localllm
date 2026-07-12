# Active

[Current stack] outcome — Vulkan `Vulkan0` runs Qwen 3.6 27B MTP Unsloth Q6 at 131072 context on `8091`; embedding is CPU on `8092`, Qwen3 Reranker 4B is GPU-resident on `8093`, and OmniVoice TTS is CPU on `8094`. All four services are healthy. Impact: treat this as the live default unless the user requests a model or placement change.

[Current main shape] outcome — main uses `np 1`, `b 2048`, `ub 1024`, Q8 KV, flash attention, 8192 image tokens, MTP draft max 2, four context checkpoints, prompt reuse enabled, and a strict 2048 MiB host prompt-cache limit. Impact: preserve these knobs when reloading the current preset unless a measured tuning pass replaces them.

[Retained Qwen presets] outcome — four valid Qwen 3.6 presets remain: 27B Unsloth 128k, 27B Huihui 128k, 35B Unsloth 160k, and 35B Huihui 256k. Impact: these are the supported model-switching inventory; fair benchmark profiles remain separate from model-specific production presets.

[llama.cpp runtime] outcome — canonical Vulkan build is `1566/e3546c794`; rollback `1306/db52540f7` is retained at `~/.local/src/llama.cpp/build-vulkan-r9700-db52540f7` and must use its own `bin` as `LD_LIBRARY_PATH`. Impact: current runtime has strict cache enforcement and validated Qwen/Vulkan behavior with a direct rollback path.

# Benchmark Durables

[Barrage V2 contract] outcome — schema `barrage-v2.1` is the default standardized evaluation path. Fair runs lock context, batch/cache profile, candidate order, cooldown, full GPU layer placement, server/runtime identity, model digest, and raw trial evidence. Impact: do not compare historical or production-profile numbers as if they were locked fair results.

[Barrage suite boundaries] outcome — performance, tool contracts, sandbox coding, concurrency, vision, and OpenWendy production remain independent outcomes; no composite score is authoritative. Impact: model/runtime capability and harness behavior cannot masquerade as one another.

[Release policy] outcome — release evidence requires five performance repeats, three quality repeats, holdouts, every required suite, and every required trial passing. Smoke runs are diagnostic only. Impact: `completed_with_errors` or a failed release gate can represent validly measured model failures rather than a crashed benchmark.

[Warm-cache policy] outcome — warm trials use workload/trial-specific prefixes and pass only at `cache_ratio >= 0.8`; cold requests disable cache explicitly. Impact: unrelated host-cache entries cannot create false warm-prefix success.

[Artifact policy] outcome — raw `benchmarks/barrage-v2-results/` artifacts remain local and ignored; compact summaries under `benchmarks/summaries/barrage_v2/` are commit-ready and feed `BENCHMARK_RESULTS.md` plus `site/data/barrage-v2.json`. Impact: publish normalized summaries, never raw prompts, responses, images, or transcripts.

[Four-model Qwen release result] outcome — corrected release evidence `qwen36-four-model-release-20260712T185403Z` recorded performance 50/50, tools 21/21, concurrency 10/10, vision 3/3, and full warm reuse for all four models. Sandbox results were 27B Unsloth 15/24, 27B Huihui 14/24, 35B Unsloth 12/24, and 35B Huihui 11/24; none cleared the strict all-sandbox release gate. Impact: 35B models dominate speed, while 27B Unsloth led this sandbox corpus.

[Four-model speed result] outcome — fair medians at 120k were approximately 413 PP / 24.5 TG for 27B Unsloth, 410 PP / 24.8 TG for 27B Huihui, 1165 PP / 101.7 TG for 35B Unsloth, and 1168 PP / 112.2 TG for 35B Huihui. Impact: the 35B MoE models are much faster under the locked base profile, independent of their weaker sandbox totals.

[OpenWendy attribution] outcome — OpenWendy is an isolated production lane bound to exact source/config/listener identity; grading requires completed tool evidence and final assistant text. The expanded smoke passed workspace status, restraint, cancellation, and workspace roundtrip but exposed final-answer followthrough failures. Impact: report these as OpenWendy stack outcomes, not direct model scores.

# Stack Durables

[Service ownership] outcome — `scripts/start-stack.sh`, `stop-stack.sh`, `status.sh`, presets, and user systemd units are the supported control surface. Scratch benchmarks must stop and later restore the managed stack. Impact: avoid unmanaged competing servers and always verify ports `8091-8094` after disruptive work.

[Prompt-cache safety] outcome — `--cache-prompt` controls slot-prefix reuse while `--cache-ram` controls host state storage; disabling prompt cache also destroys useful append-only reuse. Upstream strict cache enforcement skips entries larger than the limit and evicts before insertion. Impact: keep prompt reuse enabled with a bounded RAM cache rather than using `--no-cache-prompt` as an OOM workaround.

[Long-agent TTFT] outcome — minute-scale TTFT comes from full prompt re-prefill when an agent rewrites or reorders history and loses prefix similarity, not from decode speed. Stable append-only prefixes and user-boundary checkpoints preserve reuse. Impact: diagnose `cache_n`, checkpoint logs, and prefix shape before tuning TG.

[OOM safety] outcome — full GPU weight/KV fit does not guarantee host safety; long context checkpoints and host prompt-cache states can consume multiple GiB. Scratch tuning must stop support services, use sequential candidates, bound cache RAM, and inspect host RAM/swap as well as VRAM. Impact: avoid concurrent fit experiments and unbounded cache/checkpoint combinations.

[Vision safety] outcome — large-image Qwen 27B requests previously caused AMD Vulkan `DeviceLost`; reducing image budget from 12288 to 8192 stabilized the retained preset, and promoted runtime passed repeated vision tests. Impact: keep the lower budget and revalidate repeated mmproj use after runtime, Mesa, batch, or image-token changes.

[Backend policy] outcome — Vulkan is the validated R9700 default. HIP remains an explicit comparison path, not an automatic replacement. Impact: backend changes require isolated correctness, PP/TG, MTP, long-context, and vision checks before promotion.

[R9700 topology] outcome — the current X570 board's secondary physical slot is PCIe x4; that is usable for inference after model placement but poor for frequent cross-GPU transfer. Impact: a future multi-GPU platform should provide at least x8/x8 CPU-connected slots and adequate spacing/power.

[Network exposure] outcome — no public Funnel is active; current Tailscale routes are tailnet-only and do not target LLM ports `8091-8094`. Impact: do not expose model services publicly or add hardcoded credentials during stack work.

# Lessons

[Benchmark isolation lesson] outcome — candidates must run sequentially from a measured low-VRAM baseline with deterministic order and cooldown. Impact: background model residency, thermals, or shuffled cache state must not contaminate comparisons.

[Evidence lesson] outcome — retain exact launch argv, effective `/props` and `/slots`, layer placement, raw request/response, trial failures, and model/runtime digests. Impact: aggregate speeds or VRAM deltas alone are insufficient proof of a fair or complete run.

[Review lesson] outcome — repeated review rounds exposed layered contract defects; compare implementation against the original acceptance criteria and inspect live artifacts, not only tests. Impact: a green unit suite is necessary but not sufficient for benchmark correctness.

[Model-failure lesson] outcome — malformed/truncated tool calls, missing final answers, hidden acceptance failures, and release-gate failures are valid capability evidence when transport/runtime artifacts are complete. Impact: do not “fix” the harness to turn model failures into passes.

[Runtime-upgrade lesson] outcome — build new llama.cpp revisions in isolation, test relevant Vulkan operators and real Qwen workloads, preserve rollback, and rebuild under the final canonical path so RPATH is correct. Impact: never promote solely because upstream is newer.

[Repository ownership] outcome — frontend work is owned under `site/`; stack and benchmark work should avoid editing it unless explicitly requested. Existing unrelated dirty configuration must not be reverted or bundled into commits. Impact: keep commits scoped and preserve concurrent agent work.

# Pending

[Pending work] outcome — no benchmark or stack task is currently pending. Impact: derive the next plan from a new user request rather than carrying completed execution checklists forward.
