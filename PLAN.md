# Goal
- Test whether answer-first system instructions can change the current Qwen3-VL-8B thinking-first behavior enough to produce visible answers sooner, without using numeric reasoning budgets.

# Success Criteria
- A small set of answer-first instruction variants is tested on representative prompts.
- Results report visible output presence, reasoning length, and finish reason.
- The outcome is summarized clearly enough to judge whether this style is worth using in the bot.

# Constraints
- Keep the current live service unchanged.
- Do not use numeric reasoning budgets in the requests.
- Focus on answer-first phrasing rather than generic “think less” phrasing.

# Implementation Items
- [x] 1. Define answer-first system-prompt variants.
- [x] 2. Run them against representative prompts and compare visible output versus reasoning-only outcomes.
- [x] 3. Summarize whether answer-first phrasing materially helps.
