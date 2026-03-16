# Goal
- Test whether system-prompt instructions about thinking style can materially reduce reasoning-token usage on the current live Qwen3-VL-8B profile without using numeric thinking budgets.

# Success Criteria
- Several non-numeric thinking-style instructions are tested on representative prompts.
- Results report reasoning length, visible answer presence, and finish reason.
- The outcome is summarized clearly enough to decide whether prompt-only steering is worth using in the bot.

# Constraints
- Keep the current live service unchanged.
- Do not use numeric reasoning budgets in the requests.
- Prefer instructions that could realistically live in a bot system prompt.

# Implementation Items
- [x] 1. Define a small set of plausible system-prompt steering variants.
- [x] 2. Run them against representative prompts and compare reasoning length plus visible output.
- [x] 3. Summarize whether prompt-only steering helps enough to matter.
