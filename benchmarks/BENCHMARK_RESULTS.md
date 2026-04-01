# Retained Qwen 3.5 9B Benchmark Results

This file is the canonical score sheet for the retained local Qwen 3.5 9B models:

- `qwen-3.5-abl` = Huihui Q4 baseline
- `qwen-3.5-g` = Gemini-distilled Q4
- `qwen-3.5-unsloth` = staged, not yet rerun on the hardened April stack

Rules used here:

- Primary ranking evidence is kept split by family instead of collapsed into one blended score.
- `transcript_replay` reports matched-turn counts.
- `sim_compare` reports verification pass count, scope-clean count, and tool-error-free count where available.
- `agentic_barrage` is supporting evidence only.
- Speed-only tuning notes are fairness setup, not ranking by themselves.

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
