# Active

[Current stack] outcome — Vulkan `Vulkan0` runs Qwen 3.6 27B MTP Unsloth Q6 at 131072 context on `8091`; Qwen3 Embedding 4B runs on CPU at `np8/t12/tb12/b1024/ub1024` with 2048 context per slot on `8092`; Qwen3 Reranker 4B is GPU-resident at `np1/t8/tb4/b512/ub512/fa-on` on `8093`; and OmniVoice TTS is CPU on `8094`. All four services are healthy. Impact: treat this as the live default unless the user requests a model or placement change.

[Current main shape] outcome — main uses `np 1`, `b 2048`, `ub 1024`, Q8 KV, flash attention, 8192 image tokens, MTP draft max 2, four context checkpoints, prompt reuse enabled, and a strict 2048 MiB host prompt-cache limit. Impact: preserve these knobs when reloading the current preset unless a measured tuning pass replaces them.

[Retained Qwen presets] outcome — four valid Qwen 3.6 presets remain: 27B Unsloth 128k, 27B Huihui 128k, 35B Unsloth 160k, and 35B Huihui 256k. Impact: these are the supported model-switching inventory; fair benchmark profiles remain separate from model-specific production presets.

[Validated preset policy] outcome — Runtime Tuning V1 is reflected in the retained presets: 27B Unsloth stays `n2/t10/tb8`, 27B Huihui uses `n4`, 35B Unsloth uses no speculation, and 35B Huihui uses `n3`; all retain Q8 KV, bounded 2048 MiB prompt cache, and an 8192-token image budget. The 35B presets declare exclusive GPU residency, and the guarded loader stops the reranker for them, restores it for 27B, rolls back ordinary failures, and stops both GPU services on a kernel safety fault. Impact: use `load-main-preset.sh` so production switches reproduce the validated residency and safety policy.

[llama.cpp runtime] outcome — the sole installed runtime build is canonical Vulkan `1566/e3546c794` at `~/.local/src/llama.cpp/build-vulkan-r9700`; obsolete Vulkan `1306/db52540f7` and HIP `1086/94a220cd6` build trees were removed after confirming no service used them. Impact: all managed services and the PATH symlink resolve to one validated Qwen/Vulkan runtime with strict cache enforcement.

# Benchmark Durables

[Retrieval Runtime Tuning V1] outcome — Qwen3 Embedding 4B is promoted on CPU to `np8/t12/tb12/b1024/ub1024` with 16384 total context so every slot retains 2048 tokens; repeated eight-item latency improved from about 14.5s to 0.163s and 32-item backfill from 61.8s to 25.0s with 6/6 semantic cases passing. Qwen3 Reranker 4B stays on GPU at `np1/t8/tb4/b512/ub512/fa-on`; alternate batch/thread shapes tied in validation, and `np2/np4` were rejected after quality fell from 4/6 to 1/6 and 0/6. Impact: use the promoted embedding unit, keep reranker concurrency at one, and publish `benchmarks/summaries/retrieval_v1/qwen3-retrieval-runtime-20260714/` as a serving study rather than a model leaderboard.

[Barrage V2 contract] outcome — schema `barrage-v2.1` is the default standardized evaluation path. Fair runs lock context, batch/cache profile, candidate order, cooldown, full GPU layer placement, server/runtime identity, model digest, and raw trial evidence. Impact: do not compare historical or production-profile numbers as if they were locked fair results.

[Barrage suite boundaries] outcome — performance, tool contracts, sandbox coding, concurrency, vision, and OpenWendy production remain independent outcomes; no composite score is authoritative. Impact: model/runtime capability and harness behavior cannot masquerade as one another.

[Release policy] outcome — release evidence requires five performance repeats, three quality repeats, holdouts, every required suite, and every required trial passing. Smoke runs are diagnostic only. Impact: `completed_with_errors` or a failed release gate can represent validly measured model failures rather than a crashed benchmark.

[Warm-cache policy] outcome — warm trials use workload/trial-specific prefixes and require a reported cache hit that reprocesses no more than one configured ubatch plus eight template-boundary tokens, capped at 20% of the prime prompt; cold requests disable cache explicitly. Impact: unrelated host-cache entries cannot create false success, while expected ubatch alignment is not mislabeled as cache failure.

[Artifact policy] outcome — raw `benchmarks/barrage-v2-results/` artifacts remain local and ignored; compact summaries under `benchmarks/summaries/barrage_v2/` are commit-ready and feed `BENCHMARK_RESULTS.md` plus `site/data/barrage-v2.json`. Impact: publish normalized summaries, never raw prompts, responses, images, or transcripts.

[Four-model Qwen release result] outcome — corrected release evidence `qwen36-four-model-release-20260712T185403Z` recorded performance 50/50, tools 21/21, concurrency 10/10, vision 3/3, and full warm reuse for all four models. Sandbox results were 27B Unsloth 15/24, 27B Huihui 14/24, 35B Unsloth 12/24, and 35B Huihui 11/24; none cleared the strict all-sandbox release gate. Impact: 35B models dominate speed, while 27B Unsloth led this sandbox corpus.

[Four-model speed result] outcome — fair medians at 120k were approximately 413 PP / 24.5 TG for 27B Unsloth, 410 PP / 24.8 TG for 27B Huihui, 1165 PP / 101.7 TG for 35B Unsloth, and 1168 PP / 112.2 TG for 35B Huihui. Impact: the 35B MoE models are much faster under the locked base profile, independent of their weaker sandbox totals.

[R9700 decode roofline] outcome — the 27B Q6 GGUF is 22.884 GB and the R9700 advertises 640 GB/s, giving an unattainable-best-case 27.97 autoregressive tok/s if every model byte is read once at peak bandwidth; measured 24.51 tok/s is 87.6% of that ceiling. Impact: ordinary dense decode kernel/flag work can recover at most roughly 14% before overhead, while accepted-token gains must amortize target reads through speculation.

[MoE roofline] outcome — scaling the 35B Q6 file by its advertised 3B active parameters gives a rough 2.51 GB/token lower-bound working set and 255 tok/s ideal upper bound; measured 102-112 tok/s is about 40-44% of that deliberately optimistic ceiling. Impact: Qwen 35B has materially more software headroom than dense 27B, but expert routing, shared weights, mixed quantization, GDN state, and nonideal bandwidth make this estimate unsuitable as a performance promise.

[OpenWendy attribution] outcome — OpenWendy is an isolated production lane bound to exact source/config/listener identity; grading requires completed tool evidence and final assistant text. The expanded smoke passed workspace status, restraint, cancellation, and workspace roundtrip but exposed final-answer followthrough failures. Impact: report these as OpenWendy stack outcomes, not direct model scores.

[OpenWendy MTP evidence] outcome — six confirmed natural-chat OpenWendy turns from July 5-8 on the retained 27B Q6/MTP preset accepted 1,681 of 2,770 proposed tokens (60.7%), had per-request mean acceptance lengths of 2.13-2.34, and delivered a weighted 22.7 TG; one confirmed deterministic tool-call turn on July 10 accepted 46 of 52 proposals (88.5%), mean acceptance length 2.77, and delivered 46.0 TG. Impact: MTP strongly benefits predictable tool/code/structured output but is not reliably faster for temperature-0.6 open-ended chat; compare against a same-runtime no-spec control before changing the production setting.

[Runtime Tuning V1 result] outcome — all four Qwen3.6 models completed direct full-context validation and guarded Barrage performance/tool/vision validation. Direct evidence is 536/539 valid measurements plus 140/140 controls; the only primary failures are three expected unsupported-MTP startups for 35B Unsloth. Each model has 50/50 derived-valid Barrage performance, 15/15 tool, and 3/3 vision results; 35B Unsloth retains five raw fixed-threshold warm-cache failures with an explicit ubatch-aware correction. Impact: use `benchmarks/summaries/tuning_v1/qwen36-runtime-tuning-20260714/` as the compact publication and keep raw local evidence ignored.

[35B plus GPU reranker direct fit] outcome — both 35B models sustained three-repeat short/long direct tests at maximum explicit GPU layers with the original GPU reranker PID unchanged and no kernel safety signal. Huihui delivered median 1810 short PP, 826 long PP, 123.5 short TG, and 749.6/39.4 long-context PP/TG, while Unsloth fell to 357, 327, 50.7, and 305.5/25.1 respectively. Impact: Huihui can be much faster than tuned 27B for direct calls without CPU layer offload, but its 88 MiB measured ending VRAM headroom is insufficient to relax the conservative exclusive-GPU production policy before concurrent rerank and vision qualification.

[Frontend evidence handoff] outcome — the root README defines the stack/benchmark producer and `site/` frontend-consumer boundary. Runtime Tuning V1 is published under schema `runtime-tuning-campaign-v1.0` with separate direct, finalist Barrage, production-harness, and safety evidence. Impact: the frontend agent should add a tuning-specific normalizer and present this as a runtime study without modifying or ingesting raw local artifacts.

[OpenWendy tuning decision] outcome — alternating three-repeat A/B attribution gave both current `n2/t10/tb8` and finalist `n4/t12/tb12` 12/21 task passes; both made correct calculation tool calls but produced no final answer on the same three task families. Median end-to-end time was 77.03s current versus 97.08s finalist, so production remains `n2/t10/tb8`. Impact: direct token-speed gains alone do not justify promoting the finalist through this harness.

# Stack Durables

[Service ownership] outcome — `scripts/start-stack.sh`, `stop-stack.sh`, `status.sh`, presets, and user systemd units are the supported control surface. Scratch benchmarks must stop and later restore the managed stack. Impact: avoid unmanaged competing servers and always verify ports `8091-8094` after disruptive work.

[Prompt-cache safety] outcome — `--cache-prompt` controls slot-prefix reuse while `--cache-ram` controls host state storage; disabling prompt cache also destroys useful append-only reuse. Upstream strict cache enforcement skips entries larger than the limit and evicts before insertion. Impact: keep prompt reuse enabled with a bounded RAM cache rather than using `--no-cache-prompt` as an OOM workaround.

[Long-agent TTFT] outcome — minute-scale TTFT comes from full prompt re-prefill when an agent rewrites or reorders history and loses prefix similarity, not from decode speed. Stable append-only prefixes and user-boundary checkpoints preserve reuse. Impact: diagnose `cache_n`, checkpoint logs, and prefix shape before tuning TG.

[OOM safety] outcome — full GPU weight/KV fit does not guarantee host safety; long context checkpoints and host prompt-cache states can consume multiple GiB. Scratch tuning must stop support services, use sequential candidates, bound cache RAM, and inspect host RAM/swap as well as VRAM. Impact: avoid concurrent fit experiments and unbounded cache/checkpoint combinations.

[Vision safety] outcome — large-image Qwen 27B requests previously caused AMD Vulkan `DeviceLost`; reducing image budget from 12288 to 8192 stabilized the retained preset, and promoted runtime passed repeated vision tests. Impact: keep the lower budget and revalidate repeated mmproj use after runtime, Mesa, batch, or image-token changes.

[Backend policy] outcome — Vulkan is the only installed and validated R9700 runtime. Alternate backends must be built in a temporary isolated path and pass correctness, PP/TG, MTP, long-context, and vision checks before they can replace it. Impact: experimental backends cannot become an accidental durable fallback.

[AMDGPU runtime-PM safety] outcome — the July 13 tuning sequence ended in a hard system lock after repeated scratch-server transitions; the previous boot had AMDGPU runtime-PM churn and a `dc_state_release` refcount underflow/use-after-free warning, but no final panic was flushed, so causality remains strong rather than proven. A dynamic fail-closed helper now pins every bound AMDGPU PCI device to `on/active` at boot, bind, and resume; disruptive runs hold a root sleep inhibitor, monitor the kernel continuously, and enforce 30-second transition stabilization. Three qualification cycles, two 35B Barrage runs, and four OpenWendy model transitions completed with zero matching kernel lines. Impact: the hazardous runtime-suspend path is prevented and monitored, but the underlying driver defect is not claimed fixed; any renewed warning or lock ends GPU work immediately.

[Serving-engine survey] outcome — llama.cpp remains the best-supported fit for the current Q6 GGUF, Q8 KV, vision, long-context, and single-R9700 workload. vLLM now supports `gfx1201`, and SGLang/AITER have newer speculative, paged-cache, GDN, and fused-MoE machinery, but their fast paths center on BF16/FP8/AWQ and Instinct-class GPUs; vLLM labels GGUF experimental and under-optimized, and AITER does not list RDNA4 among fully supported hardware. Impact: keep these engines on the watchlist for future native quantized Qwen/RDNA4 paths rather than replacing the live stack now.

[Experimental-engine survey] outcome — Lucebox has a real ROCm `gfx1201` path and reports 54.65 tok/s for Qwen3.6 27B DFlash on an R9700, but that result uses a Q4 target, HumanEval, greedy verification, and a specialized fork; its Q8 KV support does not make the published number comparable to this stack's Q6/Q8 sampled agent workload. ZML now contains Qwen3.5 dense/MoE and ROCm compiler work, but exposes an example CLI rather than a complete OpenAI agent server and has no demonstrated GGUF Q6 or quantized-Q8 KV path. Impact: Lucebox is useful comparative evidence and code to watch; ZML is not an operational candidate yet.

[Efficiency quality boundary] outcome — full-prefix reuse and target-verified speculative decoding preserve target weights and Q8 KV, while PFlash/FlowKV/KVFlash selective recall, sliding-away full attention, and low-bit target KV alter the model-visible context or numerical behavior. Impact: exclude approximate context compression from production speed claims unless it is explicitly evaluated as a separate quality/performance mode.

[R9700 topology] outcome — the current X570 board's secondary physical slot is PCIe x4; that is usable for inference after model placement but poor for frequent cross-GPU transfer. Impact: a future multi-GPU platform should provide at least x8/x8 CPU-connected slots and adequate spacing/power.

[Network exposure] outcome — no public Funnel is active; current Tailscale routes are tailnet-only and do not target LLM ports `8091-8094`. Impact: do not expose model services publicly or add hardcoded credentials during stack work.

# Lessons

[Benchmark isolation lesson] outcome — candidates must run sequentially from a measured low-VRAM baseline with deterministic order and cooldown. Impact: background model residency, thermals, or shuffled cache state must not contaminate comparisons.

[Evidence lesson] outcome — retain exact launch argv, effective `/props` and `/slots`, layer placement, raw request/response, trial failures, and model/runtime digests. Impact: aggregate speeds or VRAM deltas alone are insufficient proof of a fair or complete run.

[Review lesson] outcome — repeated review rounds exposed layered contract defects; compare implementation against the original acceptance criteria and inspect live artifacts, not only tests. Impact: a green unit suite is necessary but not sufficient for benchmark correctness.

[Model-failure lesson] outcome — malformed/truncated tool calls, missing final answers, hidden acceptance failures, and release-gate failures are valid capability evidence when transport/runtime artifacts are complete. Impact: do not “fix” the harness to turn model failures into passes.

[Runtime-upgrade lesson] outcome — build new llama.cpp revisions in isolation, test relevant Vulkan operators and real Qwen workloads, preserve rollback, and rebuild under the final canonical path so RPATH is correct. Impact: never promote solely because upstream is newer.

[Repository ownership] outcome — frontend work is owned under `site/`; stack and benchmark work should avoid editing it unless explicitly requested. Existing unrelated dirty configuration must not be reverted or bundled into commits. Impact: keep commits scoped and preserve concurrent agent work.

# Research Boundaries

[Alternative speculation] outcome — no compatible DFlash/EAGLE draft artifact is present in the local model inventory, so the gated alternative-decoding test is not runnable without a deliberate model acquisition. Impact: do not download or mix alternative draft artifacts into the current MTP tuning evidence.
