# Goal
- Measure first-token latency versus total completion speed on the current live Qwen3-VL-8B profile so bot UX complaints can be tied to prompt processing, reasoning delay, or steady-state decode speed.

# Success Criteria
- The current live profile is measured on a small set of representative prompts.
- Results include time to first streamed token and total wall time.
- Results are summarized clearly enough to explain why the model may still feel slower in bot usage.

# Constraints
- Keep the current live service unchanged.
- Use the current live model, projector, KV-cache profile, and context.
- Prefer direct streaming measurements over inferred latency when possible.

# Implementation Items
- [x] 1. Choose a few representative prompts and capture streaming first-token and total completion timings.
- [x] 2. Compare those timings with the server-reported prompt/decode metrics.
- [x] 3. Summarize what is dominating perceived latency on the current stack.
