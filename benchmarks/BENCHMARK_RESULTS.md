# Benchmark Results

This file is the canonical score sheet for the current local model set.

Active focus:

- `qwen27-huihui` — `Qwen3.6-27B-abliterated-MTP-Q6_K-Huihui`, current daily default
- `qwen35-huihui` — `Huihui-Qwen3.6-35B-A3B-abliterated-MTP-Q6_K`, retained 35B Huihui/abliterated option
- `ornith-q5` / `ornith-q6` — archived comparison points; no longer retained on disk

Archived but still useful historical context:

- Gemma 4 31B quant sweep and elimination
- Qwen 3.5 27B finetune and quant eliminations
- `qwen-3.5-abl`
- `qwen-3.5-g`

Rules used here:

- Primary ranking evidence is kept split by family instead of collapsed into one blended score.
- `transcript_replay` reports matched-turn counts.
- `sim_compare` reports verification pass count, scope-clean count, and tool-error-free count where available.
- `agentic_barrage` is supporting evidence only.
- Speed-only tuning notes are fairness setup, not ranking by themselves.

## Current Readout: 2026-06-26 Qwen3.6 And Ornith

This is the current decision layer for the retained Qwen3.6 stack. It uses the committed summaries under `benchmarks/summaries/` and keeps the old Qwen3.5/Gemma sections below as archive.

Runtime constraints for the Qwen3.6 passes:

- GPU: AMD AI Pro R9700 32 GB, Vulkan backend.
- Main-model tests kept multimodal support through mmproj where applicable.
- Qwen3.6 27B Huihui daily shape: `131072` context, q8 KV, `b2048/ub1024`, draft-MTP `n=3`.
- Qwen3.6 35B Huihui retained shape: `262144` context, q8 KV, `b1024/ub512`, draft-MTP `n=2`; no reranker-in-VRAM headroom at the tested full-context shape.
- Ornith Q5/Q6 are archived after user feel testing and disk cleanup.

### Behavior Summary

| Model | Replay | Partial replay | Sim pass | Sim scope | Tool-clean | Sim agent score | OpenCode | Coding smoke | Barrage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen27-huihui` | `27/35`, `2/5` fixtures | `0.9143` | `7/8` | `6/8` | `7/8` | `0.8438` | `0.86` | `0.50` | `0.95` |
| `qwen35-huihui` | `16/31`, `1/5` fixtures | `0.7473` | `8/8` | `7/8` | `7/8` | `0.9437` | `0.86` | `0.50` | `0.875` |
| `ornith-q5` | `25/35`, `2/5` fixtures | `0.9048` | `7/8` | `7/8` | `8/8` | `0.9000` | `0.86` | `0.50` | `1.00` |
| `ornith-q6` | `24/35`, `1/5` fixtures | `0.8857` | `7/8` | `6/8` | `7/8` | `0.8438` | `0.66` | `0.25` | `0.85` |

Current conclusion:

- Daily 27B: keep `qwen27-huihui`. It has the best Qwen replay behavior, fits with the reranker in VRAM, and is the current default after Ornith was rejected in prose/editing feel.
- Daily 35B: keep `qwen35-huihui` as the trusted Huihui/abliterated 35B option. It is the strongest coding-sim solver in this set, but replay/tool-shape reliability is worse than the 27B and it does not leave room for the reranker in VRAM at the tested full-context q8-KV shape.
- Ornith Q5 had a strong benchmark balance and very high speed, but was removed because hands-on prose/editing quality did not fit the use case.
- Ornith Q6 was inferior to Q5 on speed, VRAM, and most behavior signals, and was deleted.

### Quick Speed/Fit Snapshots

| Model / shape | VRAM | Short PP | Short TG | Long PP | Long TG | Read |
| --- | --- | --- | --- | --- | --- | --- |
| `qwen27-huihui`, `131072`, q8 KV, `b2048/ub1024`, draft-MTP `n=3` | ~`28.2 GiB` decimal/driver read | ~`790-815 tok/s` | ~`57 tok/s` | ~`680 tok/s` | ~`47 tok/s` | current default; supports reranker in VRAM |
| `qwen35-huihui`, `262144`, q8 KV, `b1024/ub512`, draft-MTP `n=2` | ~`32.0 GiB` decimal/driver read | ~`2090 tok/s` medium PP | ~`151 tok/s` medium TG with newer direct-IO probe | ~`1826 tok/s` | ~`124 tok/s` | fastest 35B Huihui probe, but no reranker VRAM headroom |
| `ornith-q5`, `262144`, q8 KV, `b4096/ub2048` | ~`27.9 GiB` | `3070 tok/s` | `113.6 tok/s` | `2548 tok/s` | `107.3 tok/s` | archived despite strong benchmark/speed |
| `ornith-q6`, `262144`, q8 KV, `b4096/ub2048` | ~`31.4 GiB` | `3043 tok/s` | `107.8 tok/s` | `2450 tok/s` | `98.5 tok/s` | deleted; Q5 was better |

### Prompt Cache / TTFT Notes

- The live 27B preset uses prompt caching with `MAIN_CACHE_RAM=2048` and `--ctx-checkpoints 4`.
- `MAIN_CACHE_RAM` is a soft limit in observed llama.cpp behavior; previous logs showed cache state exceeding the configured MiB cap.
- Cache/checkpoints improve TTFT only when the agent prompt is stable and append-only enough for prefix reuse. If old history/tool blocks are rewritten, full prompt prefill still scales roughly with active context.
- Exact-same prompt replay can miss cache on this Qwen path because llama.cpp may fail the rollback/truncate path; append-only suffix prompts did produce large `cache_n` hits in direct tests.
- The agent-side durable summary boundary and append-only recent transcript are therefore part of the performance strategy, not just prompt hygiene.

## Speed And Tuning Notes

### 2026-04-01 baseline-vs-Gemini Q4 rerun speed pass

| Model | Best practical context | Probe speed / behavior |
| --- | --- | --- |
| `qwen-3.5-abl` | `131072` | about `77.7 tok/s` exact-`OK`, about `75.2 tok/s` short-answer on the standard no-warmup profile; capped probes mostly filled with hidden reasoning |
| `qwen-3.5-g` | `131072` | about `73.8 tok/s` exact-`OK`, about `73.1 tok/s` short-answer on the standard no-warmup profile; capped probes also mostly filled with hidden reasoning |

### Current retained-model tuning read

| Model | Current read |
| --- | --- |
| `qwen-3.5-abl` | reference launch profile is the standard `131072` no-warmup multimodal shape |
| `qwen-3.5-g` | same `131072` no-warmup multimodal profile fits cleanly and remains the fair comparison point |
| `qwen-3.5-unsloth` | no current hardened-stack tuning pass recorded yet |

## Transcript Replay

Matched turns are counted only when both finish reason and expected tool shape matched.

### 2026-03-20 historical Gemini-vs-baseline read

| Model | Total matched turns | Total elapsed |
| --- | --- | --- |
| `qwen-3.5-g` | `29/33` | `88.18s` |
| `qwen-3.5-abl` | `26/33` | `91.56s` |

Fixture breakdown:

| Model | `queue_fix_real` | `retry_fix_real` | `retry_triage_real` | `soak_real` |
| --- | --- | --- | --- | --- |
| `qwen-3.5-g` | `7/7` | `4/5` | `2/2` | `16/19` |
| `qwen-3.5-abl` | `7/7` | `3/5` | `2/2` | `14/19` |

### 2026-04-01 baseline-vs-Gemini rerun

| Model | Total matched turns | Total elapsed |
| --- | --- | --- |
| `qwen-3.5-abl` | `29/35` | `107.03s` |
| `qwen-3.5-g` | `29/35` | `83.99s` |

Fixture breakdown:

| Model | `queue_fix_real` | `retry_fix_real` | `retry_tool_followthrough` | `retry_triage_real` | `soak_real` |
| --- | --- | --- | --- | --- | --- |
| `qwen-3.5-abl` | `7/7` | `4/5` | `2/2` | `2/2` | `14/19` |
| `qwen-3.5-g` | `7/7` | `4/5` | `1/2` | `2/2` | `15/19` |

Replay read:

- `qwen-3.5-g` is the faster replay model and slightly better on long-session soak behavior.
- `qwen-3.5-abl` keeps the cleaner `retry_tool_followthrough` behavior, which still matters for general-agent reliability.
- `qwen-3.5-unsloth` has no current replay result in the retained set.

## Sim Compare

`pass` means verification succeeded. `scope` means only expected files were modified.

### 2026-03-20 historical Gemini-vs-baseline read

| Model | Pass | Scope | Total elapsed |
| --- | --- | --- | --- |
| `qwen-3.5-g` | `7/8` | `7/8` | `145.84s` |
| `qwen-3.5-abl` | `7/8` | `6/8` | `235.59s` |

Key difference:

| Scenario | `qwen-3.5-g` | `qwen-3.5-abl` |
| --- | --- | --- |
| `flush_report_two_file_fix` | pass, scope clean | pass, scope drift |
| `session_store_exploration` | fail, scope drift | fail, scope drift |

### 2026-04-01 baseline-vs-Gemini rerun

| Model | Pass | Scope | Tool-error-free | Total elapsed |
| --- | --- | --- | --- | --- |
| `qwen-3.5-abl` | `7/8` | `6/8` | `7/8` | `280.89s` |
| `qwen-3.5-g` | `7/8` | `6/8` | `8/8` | `159.64s` |

Key differences:

| Scenario | `qwen-3.5-abl` | `qwen-3.5-g` |
| --- | --- | --- |
| `retry_bugfix` | pass, scope clean, one tool-format error | pass, scope clean, tool-clean |
| `flush_report_two_file_fix` | pass, scope drift across 4 files | pass, scope drift across 6 files |
| `session_store_exploration` | fail, scope drift | fail, scope drift |

Sandbox read:

- `qwen-3.5-g` is the stronger coding-side 9B pick in the retained set because it ties the scoreline while finishing much faster and more cleanly on tool usage.
- `qwen-3.5-abl` remains competitive, but its coding-agent edge is now mostly predictability rather than absolute throughput or cleanliness.
- `qwen-3.5-unsloth` has no current sandbox result in the retained set.

## Agentic Barrage

These uncapped snapshots are qualitative only. They are useful for reasoning-volume and tool-followthrough shape, not for primary ranking.

### 2026-04-01 baseline-vs-Gemini rerun

| Model | Result count | Throughput read | Main qualitative read |
| --- | --- | --- | --- |
| `qwen-3.5-abl` | `10` scored requests | roughly `70-74 tok/s` | coherent outward answers, but very large hidden-reasoning blocks on planning and evidence prompts |
| `qwen-3.5-g` | `10` scored requests | roughly `69-74 tok/s` | similar outward quality with materially shorter hidden-reasoning blocks on the same prompts |

Prompt-family note:

- Across `plan_then_revise`, `review_then_retry`, and `evidence_triage`, `qwen-3.5-abl` emitted about `94k` hidden-reasoning characters versus about `39k` for `qwen-3.5-g`.
- Both models stayed tool-shaped on `codex_workflow` turn 1 and `tool_followthrough` turn 1.
- `qwen-3.5-g` completed `codex_workflow` turn 2 as a concise direct answer rather than another tool call.

## Current Readout

- Safest default retained 9B: `qwen-3.5-abl`
- Strongest coding-side retained 9B: `qwen-3.5-g`
- Best retained replay peak: `qwen-3.5-g` at `29/33` on the historical high-water mark
- Latest clean retained replay rerun: tie at `29/35`, with Gemini faster and baseline cleaner on `retry_tool_followthrough`
- Latest clean retained sandbox rerun: tie at `7/8` pass and `6/8` scope, with Gemini much faster and fully tool-clean
- `qwen-3.5-unsloth` remains pending a fresh hardened-stack benchmark pass

# Qwen 3.5 27B Vulkan Fit And Speed

This section is limited to Vulkan tuning-plus-speed checks on the R9700. It is not a behavior ranking.

Rules used here:

- Backend: `Vulkan0`
- Flow: context sweep first, then profile sweep at `131072`
- Contexts tested: `32768`, `65536`, `98304`, `131072`
- Profile comparison: standard no-warmup vs warmup
- No suite or barrage

## 2026-04-08 Vulkan Control Read

The first backend control model was `Huihui-Qwen3.5-27B-abliterated-i1-Q4_K_M-mradermacher.gguf`.

| Model | Context sweep read | Profile read at `131072` |
| --- | --- | --- |
| `huihui-q4` | `31.9 tok/s` at `32768`, `32.0 tok/s` at `65536`, `32.0 tok/s` at `98304`, `31.8 tok/s` at `131072` | `31.4 tok/s` exact-`OK`, `31.2 tok/s` direct probe; warmup gave no meaningful gain |

## 2026-04-08 Remaining 27B Vulkan Sweep

| Model | Quant | `32768` | `65536` | `98304` | `131072` | No-warmup exact-`OK` | No-warmup direct | Warm exact-`OK` | Warm direct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `huihui-q6` | `Q6_K` | `25.36` | `25.38` | `25.38` | `25.47` | `24.91` | `24.73` | `24.89` | `24.71` |
| `huihui-claude-q4` | `Q4_K_M` | `31.74` | `31.77` | `31.94` | `31.78` | `31.27` | `30.99` | `31.25` | `31.00` |
| `huihui-claude-q6` | `Q6_K` | `25.29` | `25.43` | `25.44` | `25.45` | `24.91` | `24.72` | `24.85` | `24.82` |
| `jackrong-claude-q4` | `Q4_K_M` | `31.84` | `32.02` | `32.03` | `32.02` | `31.40` | `31.19` | `31.37` | `31.10` |
| `jackrong-claude-q6` | `Q6_K` | `25.22` | `25.45` | `25.36` | `25.44` | `24.92` | `24.72` | `25.06` | `24.70` |
| `gemini-q4` | `Q4_K_M` | `31.74` | `31.97` | `32.01` | `31.91` | `31.35` | `31.17` | `31.36` | `31.11` |
| `gemini-q6` | `Q6_K` | `25.26` | `25.32` | `25.41` | `25.44` | `24.88` | `24.71` | `24.86` | `24.70` |
| `unsloth-q4` | `Q4_K_M` | `30.75` | `31.66` | `31.71` | `31.47` | `31.04` | `30.84` | `30.93` | `30.80` |
| `unsloth-q6` | `Q6_K` | `25.00` | `25.18` | `25.13` | `25.06` | `24.66` | `24.51` | `24.69` | `24.47` |

Vulkan fit-and-speed read:

- Every tested 27B Q4 and Q6 variant fit cleanly through `131072` on the standard profile.
- The Q4 family clusters tightly around `31-32 tok/s`; the fastest read in this sweep was `jackrong-claude-q4`.
- The Q6 family clusters tightly around `25 tok/s`; the speed penalty versus Q4 is consistent and large enough that Q6 needs a quality win to justify itself.
- Warmup did not produce a meaningful speed gain on any of these 27B Vulkan passes.

## 2026-04-08 Huihui Claude 27B Quant A/B

This section isolates the quant question on one finetune family only:

- `huihui-claude27-q4` = `Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-i1-Q4_K_M`
- `huihui-claude27-q6` = `Huihui-Qwen3.5-27B-Claude-4.6-Opus-abliterated-i1-Q6_K`

Rules used here:

- Backend: `Vulkan0`
- Launch profile: `-np 1 -tb 8 -b 512 -ub 256 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- Context: `131072`
- Suites: `transcript_replay`, `sim_compare`, `opencode_compare`, `coding_compare`, `agentic_barrage`

### Replay

| Model | Matched turns | Passed fixtures |
| --- | --- | --- |
| `huihui-claude27-q4` | `29/35` | `2/5` |
| `huihui-claude27-q6` | `28/35` | `1/5` |

Replay read:

- `Q4_K_M` wins the replay side.
- `Q4_K_M` kept `queue_fix_real` clean where `Q6_K` did not.
- Both quants still drifted in `retry_fix_real` and `retry_tool_followthrough`, but `Q6_K` did not buy a replay-quality improvement.

### Sim Compare

| Model | Pass | Scope | Tool-error-free | Total elapsed |
| --- | --- | --- | --- | --- |
| `huihui-claude27-q4` | `8/8` | `6/8` | `8/8` | `605.44s` |
| `huihui-claude27-q6` | `8/8` | `7/8` | `8/8` | `605.67s` |

Sandbox read:

- Both quants were excellent on the coding harness: `8/8` pass and fully tool-clean.
- `Q6_K` earned one real quality edge by keeping `flush_report_two_file_fix` scope-clean where `Q4_K_M` over-edited into a third file.
- `Q6_K` still drifted on `session_store_exploration`, so the scope edge is real but narrow.
- Total elapsed was effectively a tie on this harness despite the large prompt-only speed difference.

### Supporting Diagnostics

| Model | Coding compare avg `tok/s` | Coding compare reasoning chars | Barrage avg `tok/s` | Barrage reasoning chars |
| --- | --- | --- | --- | --- |
| `huihui-claude27-q4` | `28.78` | `5780` | `28.85` | `7903` |
| `huihui-claude27-q6` | `23.20` | `4818` | `23.32` | `8505` |

Diagnostic read:

- `Q4_K_M` is much faster on prompt-only diagnostics and barrage.
- `Q6_K` did not buy enough extra discipline there to offset the speed loss.

### Quant Decision

1. Keep `huihui-claude27-q4` as the default quant for this finetune family.
2. Do not carry the full Q6 tier forward by default.
3. Keep `huihui-claude27-q6` only as a possible specialist fallback if later scope-heavy tasks show the same narrow cleanliness edge.

## 2026-04-08 Qwen 27B Q4 Finetune Elimination

This section narrows the active Qwen 27B Q4 field after the Q6 tier was retired.

Candidates in this pass:

- `huihui-claude27-q4`
- `jackrong-claude27-q4`
- `gemini27-q4`

Explicitly out of scope for this pass:

- `huihui-q4` already had recent reference data and was not rerun here
- `unsloth-q4` stays ignored for now as the safe control fallback

Rules used here:

- Backend: `Vulkan0`
- Launch profile: `-np 1 -tb 8 -b 512 -ub 256 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- Context: `131072`
- Suites: `transcript_replay`, `sim_compare`, `opencode_compare`, `coding_compare`, `agentic_barrage`

### Replay

| Model | Matched turns | Passed fixtures |
| --- | --- | --- |
| `huihui-claude27-q4` | `29/35` | `2/5` |
| `gemini27-q4` | `27/35` | `1/5` |
| `jackrong-claude27-q4` | `23/34` | `1/5` |

Replay read:

- `huihui-claude27-q4` is the clear replay winner in this set.
- `gemini27-q4` holds second place and is materially better than `jackrong-claude27-q4` on matched turns.
- `jackrong-claude27-q4` lost too much general-agent fidelity to stay competitive despite decent prompt-only speed.

### Sim Compare

| Model | Pass | Scope | Tool-error-free | Total elapsed |
| --- | --- | --- | --- | --- |
| `huihui-claude27-q4` | `8/8` | `6/8` | `8/8` | `605.44s` |
| `gemini27-q4` | `7/8` | `7/8` | `8/8` | `472.71s` |
| `jackrong-claude27-q4` | `7/8` | `7/8` | `8/8` | `462.45s` |

Sandbox read:

- `huihui-claude27-q4` is the only candidate here to solve all `8/8` scenarios.
- `gemini27-q4` and `jackrong-claude27-q4` are cleaner on file scope, but both drop one scenario that Huihui Claude completes.
- All three candidates are fully tool-clean on the sim harness.

### Supporting Diagnostics

| Model | Coding compare avg `tok/s` | Coding compare reasoning chars | Barrage avg `tok/s` | Barrage reasoning chars |
| --- | --- | --- | --- | --- |
| `huihui-claude27-q4` | `28.78` | `5780` | `28.85` | `7903` |
| `gemini27-q4` | `28.71` | `34541` | `28.87` | `25740` |
| `jackrong-claude27-q4` | `28.91` | `13071` | `28.94` | `6783` |

Diagnostic read:

- Prompt-only speed is effectively a three-way tie.
- `gemini27-q4` is much heavier on reasoning volume than the other two.
- `jackrong-claude27-q4` is concise and fast in diagnostics, but that does not overcome its replay drop.

### Elimination Result

1. Keep `huihui-claude27-q4` as the leading Qwen 27B Q4 candidate.
2. Keep `gemini27-q4` as the second-place challenger.
3. Eliminate `jackrong-claude27-q4` first.

## 2026-04-08 Huihui Base Q4 Reference

This section fills the missing full-suite reference for the base Huihui Q4 model so it can be compared directly against `huihui-claude27-q4`.

Candidate:

- `huihui-q4` = `Huihui-Qwen3.5-27B-abliterated-i1-Q4_K_M`

Rules used here:

- Backend: `Vulkan0`
- Launch profile: `-np 1 -tb 8 -b 512 -ub 256 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- Context: `131072`
- Suites: `transcript_replay`, `sim_compare`, `opencode_compare`, `coding_compare`, `agentic_barrage`

### Huihui Q4 Result

| Model | Replay | Passed fixtures | Sim pass | Sim scope | Tool-error-free | Sim elapsed |
| --- | --- | --- | --- | --- | --- | --- |
| `huihui-q4` | `28/35` | `1/5` | `7/8` | `7/8` | `8/8` | `589.62s` |

Supporting diagnostics:

| Model | Coding compare avg `tok/s` | Coding compare reasoning chars | Barrage avg `tok/s` | Barrage reasoning chars |
| --- | --- | --- | --- | --- |
| `huihui-q4` | `28.74` | `51346` | `28.86` | `32835` |

Read:

- `huihui-q4` is fast and tool-clean, but it is clearly weaker than `huihui-claude27-q4` on replay and does not solve the full `8/8` sim set.
- The base Huihui model is cleaner on scope than `huihui-claude27-q4`, but it pays for that with one dropped sandbox scenario and one fewer matched replay turn.
- Reasoning volume is dramatically heavier than `huihui-claude27-q4` despite nearly identical prompt-only speed.

### Direct Huihui Comparison

| Model | Replay | Passed fixtures | Sim pass | Sim scope | Tool-error-free | Sim elapsed | Coding `tok/s` | Coding reasoning chars | Barrage `tok/s` | Barrage reasoning chars |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `huihui-claude27-q4` | `29/35` | `2/5` | `8/8` | `6/8` | `8/8` | `605.44s` | `28.78` | `5780` | `28.85` | `7903` |
| `huihui-q4` | `28/35` | `1/5` | `7/8` | `7/8` | `8/8` | `589.62s` | `28.74` | `51346` | `28.86` | `32835` |

Direct comparison read:

- `huihui-claude27-q4` is the better overall model.
- `huihui-q4` keeps a slight scope-discipline edge and is a little faster end-to-end in the sim harness, but the difference is small.
- `huihui-claude27-q4` wins where it matters more: replay fidelity, fixture completion, and total sim task completion, while staying far more concise in reasoning.

# Gemma 4 31B Vulkan Fit And Speed

This section is limited to Vulkan tuning-plus-speed checks on the R9700. It is not a behavior ranking.

Rules used here:

- Backend: `Vulkan0`
- Flow: context sweep first, then profile sweep at the best fitted context
- Contexts tested: `32768`, `65536`, `98304`, `131072`
- Profile comparison: standard no-warmup vs warmup
- No suite or barrage

## 2026-04-08 Gemma 31B Vulkan Sweep

Runtime note:

- The first Gemma pass failed because the existing local `llama.cpp` checkout was stale and could not load `general.architecture = gemma4`.
- The local checkout was updated to `b8702` and the Vulkan backend was rebuilt before the sweep below was rerun.

| Model | Quant | Best fit context | `32768` | `65536` | `98304` | `131072` | No-warmup exact-`OK` | No-warmup direct | Warm exact-`OK` | Warm direct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `gemma31-q4km` | `Q4_K_M` | `131072` | `27.96` | `28.61` | `28.62` | `28.43` | `28.07` | `27.73` | `28.29` | `27.70` |
| `gemma31-iq4nl` | `IQ4_NL` | `131072` | `29.60` | `29.95` | `30.06` | `30.05` | `30.22` | `29.19` | `29.61` | `29.12` |
| `gemma31-udq4kxl` | `UD-Q4_K_XL` | `131072` | `25.42` | `27.88` | `27.89` | `27.98` | `27.58` | `27.11` | `27.41` | `27.04` |

Gemma fit-and-speed read:

- All three tested Gemma 4 31B quants fit cleanly through `131072` on Vulkan after the `llama.cpp` refresh.
- `IQ4_NL` is the clear speed winner in this set, landing about `30.1 tok/s` on the context sweep and about `30.2 tok/s` on the no-warmup exact-`OK` probe.
- `Q4_K_M` is the middle ground, roughly `1.5-2 tok/s` behind `IQ4_NL` at the same contexts.
- `UD-Q4_K_XL` is the slowest of the three on this stack despite the stronger quant format, settling around `28 tok/s` once context is above `65536`.
- Warmup did not produce a meaningful speed gain on these Gemma 31B Vulkan passes.

## 2026-04-08 Gemma 31B Vulkan Elimination

Rules used here:

- Backend: `Vulkan0`
- Launch profile: `-np 1 -tb 8 -b 512 -ub 256 -fa on --threads-http 4 -ctk q4_0 -ctv q4_0 -rea on --metrics --no-warmup --image-max-tokens 12288`
- Context: `131072`
- Suites: `transcript_replay`, `sim_compare`, `opencode_compare`, `coding_compare`, `agentic_barrage`
- Higher `-b` / `-ub` checks were tried before the elimination run and did not produce a meaningful win for any Gemma quant, so the base profile remained the fairest choice.

### Replay

| Model | Matched turns | Passed fixtures | Read |
| --- | --- | --- | --- |
| `gemma-4-31b-q4km` | `22/35` | `1/5` | weakest replay result |
| `gemma-4-31b-iq4nl` | `23/35` | `2/5` | best replay result, tied on turns but cleaner fixture count |
| `gemma-4-31b-udq4kxl` | `23/35` | `1/5` | tied on turns, but weaker fixture completion |

Fixture breakdown:

| Model | `retry_triage_real` | `retry_fix_real` | `queue_fix_real` | `retry_tool_followthrough` | `soak_real` |
| --- | --- | --- | --- | --- | --- |
| `gemma-4-31b-q4km` | `2/2` | `1/5` | `5/7` | `1/2` | `13/19` |
| `gemma-4-31b-iq4nl` | `2/2` | `2/5` | `5/7` | `2/2` | `12/19` |
| `gemma-4-31b-udq4kxl` | `2/2` | `1/5` | `5/7` | `1/2` | `14/19` |

Replay read:

- All three Gemma quants are materially weaker on replay fidelity than the earlier Qwen family baselines.
- `gemma-4-31b-iq4nl` is still the best replay pick here because it is the only one to pass two fixtures and keep `retry_tool_followthrough` clean.
- `gemma-4-31b-udq4kxl` recovers some ground on `soak_real`, but not enough to overcome its weaker fixture pass count and speed.

### Sim Compare

| Model | Pass | Scope | Tool-error-free | Total elapsed |
| --- | --- | --- | --- | --- |
| `gemma-4-31b-q4km` | `7/8` | `6/8` | `1/8` | `1535.61s` |
| `gemma-4-31b-iq4nl` | `7/8` | `7/8` | `2/8` | `1061.47s` |
| `gemma-4-31b-udq4kxl` | `7/8` | `6/8` | `1/8` | `1538.34s` |

Sandbox read:

- All three Gemma quants solve the same `7/8` scenarios and fail the same `session_store_exploration` scope-heavy task.
- `gemma-4-31b-iq4nl` is the clear coding winner because it is much faster than the other two and is the only one with `7/8` scope-clean.
- `gemma-4-31b-q4km` and `gemma-4-31b-udq4kxl` are effectively tied behind it, with `ud-q4_k_xl` giving up speed without gaining correctness.

### Supporting Diagnostics

| Model | Coding compare avg `tok/s` | Coding compare reasoning chars | Barrage avg `tok/s` | Barrage reasoning chars |
| --- | --- | --- | --- | --- |
| `gemma-4-31b-q4km` | `25.69` | `11675` | `26.22` | `12904` |
| `gemma-4-31b-iq4nl` | `27.04` | `9008` | `27.47` | `10857` |
| `gemma-4-31b-udq4kxl` | `25.15` | `9395` | `25.62` | `14714` |

Diagnostic read:

- `gemma-4-31b-iq4nl` is also the strongest prompt-only/coding-side diagnostic model in this set.
- `gemma-4-31b-udq4kxl` shows the heaviest barrage reasoning load despite being the slowest candidate.

### Elimination Result

1. Keep `gemma-4-31b-iq4nl` as the Gemma winner and default Gemma preset.
2. Eliminate `gemma-4-31b-udq4kxl` first because it is slower than `q4_k_m` and does not buy back that cost in replay or sim.
3. Keep `gemma-4-31b-q4km` only as the simpler fallback/control quant.


<!-- BENCHMARK-AUTO-GENERATED -->

# Committed Summary Rollup

## agentic_barrage

Run: `huihui-qwen-torture-20260626T090539Z-qwen35-huihui-agentic_barrage`

Average score: **0.875**

## agentic_barrage

Run: `huihui-qwen-torture-20260626T090539Z-qwen27-huihui-agentic_barrage`

Average score: **0.95**

## agentic_barrage

Run: `ornith-q6-torture-20260626T035224Z-ornith-q6-agentic_barrage`

Average score: **0.85**

## agentic_barrage

Run: `ornith-q5-agentic-barrage-20260626T035105Z-ornith-q5-agentic_barrage`

Average score: **1.0**

## barrage_v2

Run: `qwen27-unsloth-smoke-20260710T-vram`

| Candidate | Status | Tool core | Sandbox core |
| --- | --- | --- | --- |
| qwen27-unsloth-q6 | completed | 2/2 | 3/3 |

## barrage_v2

Run: `qwen27-unsloth-smoke-20260710T-final`

| Candidate | Status | Tool core | Sandbox core |
| --- | --- | --- | --- |
| qwen27-unsloth-q6 | completed | 2/2 | 3/3 |

## barrage_v2

Run: `qwen27-unsloth-remediation-smoke-20260710T`

| Candidate | Status | Tool core | Sandbox core |
| --- | --- | --- | --- |
| qwen27-unsloth-q6 | completed | 2/2 | 3/3 |

## barrage_v2

Run: `openwendy-production-smoke-20260710T`

| Candidate | Status | Harness | Pass |
| --- | --- | --- | --- |
| local | completed | openwendy-core-api | ungraded (1) |

## barrage_v2

Run: `openwendy-production-remediation-smoke-20260710T`

| Candidate | Status | Harness | Pass |
| --- | --- | --- | --- |
| local | completed | openwendy-core-api | 0/1 |

## coding_compare

Run: `huihui-qwen-torture-20260626T090539Z-qwen35-huihui-coding_compare`

| Candidate | Average score | Task scores |
| --- | --- | --- |
| qwen35-huihui | 0.5 | merge_intervals: 0, retry_bug: 0, simple_edit: 1, task_runner: 1 |

## coding_compare

Run: `huihui-qwen-torture-20260626T090539Z-qwen27-huihui-coding_compare`

| Candidate | Average score | Task scores |
| --- | --- | --- |
| qwen27-huihui | 0.5 | merge_intervals: 1, retry_bug: 0, simple_edit: 1, task_runner: 0 |

## coding_compare

Run: `ornith-q6-torture-20260626T035224Z-ornith-q6-coding_compare`

| Candidate | Average score | Task scores |
| --- | --- | --- |
| ornith-q6 | 0.25 | merge_intervals: 0, retry_bug: 0, simple_edit: 1, task_runner: 0 |

## coding_compare

Run: `ornith-torture-20260626T034246Z-ornith-q5-coding_compare`

| Candidate | Average score | Task scores |
| --- | --- | --- |
| ornith-q5 | 0.5 | merge_intervals: 0, retry_bug: 0, simple_edit: 1, task_runner: 1 |

## opencode_compare

Run: `huihui-qwen-torture-20260626T090539Z-qwen35-huihui-opencode_compare`

| Candidate | Average score |
| --- | --- |
| qwen35-huihui | 0.86 |

## opencode_compare

Run: `huihui-qwen-torture-20260626T090539Z-qwen27-huihui-opencode_compare`

| Candidate | Average score |
| --- | --- |
| qwen27-huihui | 0.86 |

## opencode_compare

Run: `ornith-q6-torture-20260626T035224Z-ornith-q6-opencode_compare`

| Candidate | Average score |
| --- | --- |
| ornith-q6 | 0.66 |

## opencode_compare

Run: `ornith-torture-20260626T034246Z-ornith-q5-opencode_compare`

| Candidate | Average score |
| --- | --- |
| ornith-q5 | 0.86 |

## sim_compare

Run: `huihui-qwen-torture-20260626T090539Z-qwen35-huihui-sim_compare`

| Candidate | Pass | Scope clean | Scope score | Tool clean | Agent score |
| --- | --- | --- | --- | --- | --- |
| qwen35-huihui | 8/8 | 7/8 | 0.9167 | 7/8 | 0.9437 |

## sim_compare

Run: `huihui-qwen-torture-20260626T090539Z-qwen27-huihui-sim_compare`

| Candidate | Pass | Scope clean | Scope score | Tool clean | Agent score |
| --- | --- | --- | --- | --- | --- |
| qwen27-huihui | 7/8 | 6/8 | 0.8333 | 7/8 | 0.8438 |

## sim_compare

Run: `ornith-q6-torture-20260626T035224Z-ornith-q6-sim_compare`

| Candidate | Pass | Scope clean | Scope score | Tool clean | Agent score |
| --- | --- | --- | --- | --- | --- |
| ornith-q6 | 7/8 | 6/8 | 0.8125 | 7/8 | 0.8438 |

## sim_compare

Run: `ornith-torture-20260626T034246Z-ornith-q5-sim_compare`

| Candidate | Pass | Scope clean | Scope score | Tool clean | Agent score |
| --- | --- | --- | --- | --- | --- |
| ornith-q5 | 7/8 | 7/8 | 0.875 | 8/8 | 0.9 |

## transcript_replay

Run: `huihui-qwen-torture-20260626T090539Z-qwen35-huihui-transcript_replay`

| Candidate | Fixtures passed | Turn match | Partial score |
| --- | --- | --- | --- |
| qwen35-huihui | 1/5 | 16/31 | 0.7473 |

## transcript_replay

Run: `huihui-qwen-torture-20260626T090539Z-qwen27-huihui-transcript_replay`

| Candidate | Fixtures passed | Turn match | Partial score |
| --- | --- | --- | --- |
| qwen27-huihui | 2/5 | 27/35 | 0.9143 |

## transcript_replay

Run: `ornith-q6-torture-20260626T035224Z-ornith-q6-transcript_replay`

| Candidate | Fixtures passed | Turn match | Partial score |
| --- | --- | --- | --- |
| ornith-q6 | 1/5 | 24/35 | 0.8857 |

## transcript_replay

Run: `ornith-torture-20260626T034246Z-ornith-q5-transcript_replay`

| Candidate | Fixtures passed | Turn match | Partial score |
| --- | --- | --- | --- |
| ornith-q5 | 2/5 | 25/35 | 0.9048 |

