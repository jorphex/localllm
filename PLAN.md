# Goal
- Expose the `llama.cpp` metrics endpoint on the live `localllm` main service, verify it, and provide a concise behavioral handoff list for the `openwendy` agent.

# Success Criteria
- The main service is started with metrics enabled.
- The live endpoint responds successfully on the current host.
- Repo docs and notes reflect the metrics endpoint.
- A concise list of behavioral facts is ready for handoff to the `openwendy` agent.

# Constraints
- Keep the current model, context, and speed-tuned flags unchanged aside from enabling metrics.
- Keep the embedding service unchanged.
- Do not mix `localllm` implementation work with `openwendy` code changes.

# Implementation Items
- [x] 1. Update the live main-service flags to enable metrics.
- [x] 2. Restart and verify the live metrics endpoint.
- [x] 3. Update `README.md`, `NOTES.md`, and this plan with the result.
- [x] 4. Prepare concise handoff items for the `openwendy` agent.
