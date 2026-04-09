# Goal
- Find why repeated long-prompt requests on the current `llama.cpp` server path still report `cache_n=0` and do not benefit from prompt-cache reuse.

# Success Criteria
- The blocking condition is identified in either `llama.cpp` behavior or the benchmark request shape.
- A minimal fix or workaround is applied if feasible.
- A repeated-prompt verification shows either real cache reuse or a clearly documented hard limitation.

# Constraints
- Keep the active model as `qwen-3.5-27b-huihui-claude-q4`.
- Do not guess from theory alone; verify with direct server behavior.
- Restore the managed live service after scratch experiments.

# Implementation Items
- [completed] 1. Inspect local `llama.cpp` cache behavior and server logs around repeated prompts.
- [completed] 2. Check whether our request shape or benchmark harness is preventing reuse.
- [completed] 3. Document the blocking slot-selection/request-state conditions that keep `cache_n=0` on repeated prompts.
