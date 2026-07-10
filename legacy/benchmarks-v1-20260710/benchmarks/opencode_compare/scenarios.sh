#!/usr/bin/env bash
set -euo pipefail

opencode_system_prompt() {
  cat <<'TXT'
You are Codex, a coding agent operating inside a local repo harness. Workflow: plan -> implement -> check -> fix -> verify -> review. Stay concrete, evidence-driven, and narrow in scope. Prefer taking the next real action over narrating intentions. If tools are available, use them deliberately instead of describing what you would do.
TXT
}

opencode_scenarios() {
  printf '%s\n' repo_triage revise_after_feedback tool_followthrough
}

opencode_turn_count() {
  local scenario="$1"
  case "${scenario}" in
    repo_triage) printf '1\n' ;;
    revise_after_feedback) printf '2\n' ;;
    tool_followthrough) printf '2\n' ;;
    *) echo "Unknown scenario: ${scenario}" >&2; return 1 ;;
  esac
}

opencode_request_json() {
  local scenario="$1"
  local turn="$2"
  local model_alias="$3"
  local system_prompt
  system_prompt="$(opencode_system_prompt)"

  case "${scenario}:${turn}" in
    repo_triage:1)
      jq -cn \
        --arg model "${model_alias}" \
        --arg system_prompt "${system_prompt}" \
        '{
          model:$model,
          messages:[
            {role:"system", content:$system_prompt},
            {
              role:"user",
              content:"You are dropped into a Python repo after an agent run failed. Available evidence: `pytest -q` now fails `test_cache_eviction_order`, the reviewer says the previous patch touched too many files, and a production trace shows lock contention in `SessionStore.flush`. Give only the next concrete move for an OpenCode-style run. Return exactly 6 short bullets covering: what evidence matters most, the first file or command to inspect, the narrowest change worth attempting, what stays out of scope, and how you would verify the first fix."
            }
          ],
          temperature:0.2,
          top_p:0.95,
          top_k:20,
          repeat_penalty:1.05,
          stream:false,
          chat_template_kwargs:{enable_thinking:true}
        }'
      ;;
    revise_after_feedback:1)
      jq -cn \
        --arg model "${model_alias}" \
        --arg system_prompt "${system_prompt}" \
        '{
          model:$model,
          messages:[
            {role:"system", content:$system_prompt},
            {
              role:"user",
              content:"You need to fix a flaky queue worker in a Python repo. Start with the next narrow move only. Return exactly 6 short bullets that cover scope boundaries, what evidence to collect before editing, what one test to run first, and when to stop iterating."
            }
          ],
          temperature:0.2,
          top_p:0.95,
          top_k:20,
          repeat_penalty:1.05,
          stream:false,
          chat_template_kwargs:{enable_thinking:true}
        }'
      ;;
    revise_after_feedback:2)
      jq -cn \
        --arg model "${model_alias}" \
        --arg system_prompt "${system_prompt}" \
        '{
          model:$model,
          messages:[
            {role:"system", content:$system_prompt},
            {
              role:"user",
              content:"You need to fix a flaky queue worker in a Python repo. Start with the next narrow move only. Return exactly 6 short bullets that cover scope boundaries, what evidence to collect before editing, what one test to run first, and when to stop iterating."
            },
            {
              role:"assistant",
              content:"- Inspect the worker retry path and queue ordering code before editing.\n- Reuse the failing test and logs to identify whether cancellation or ordering regressed.\n- Limit the first patch to the smallest behavior change in the queue worker path.\n- Do not refactor unrelated helpers or retry policy yet.\n- Run the single most relevant flaky worker test first before widening coverage.\n- Stop if the narrow patch fixes the targeted failure without moving other queue semantics."
            },
            {
              role:"user",
              content:"Feedback after the first patch: `test_retry_cancellation` now hangs, `test_queue_drain_order` fails with `AssertionError: expected [a,b,c], got [b,a,c]`, and production logs still show `worker backlog exceeded soft limit`. Do not restart from scratch. Revise the next move only. Return exactly 6 short bullets covering the narrower next change, the evidence you would reuse, the first test to rerun, what remains out of scope, and when to stop."
            }
          ],
          temperature:0.2,
          top_p:0.95,
          top_k:20,
          repeat_penalty:1.05,
          stream:false,
          chat_template_kwargs:{enable_thinking:true}
        }'
      ;;
    tool_followthrough:1)
      jq -cn \
        --arg model "${model_alias}" \
        --arg system_prompt "${system_prompt}" \
        '{
          model:$model,
          messages:[
            {role:"system", content:$system_prompt},
            {
              role:"user",
              content:"Task: fix a regression in `worker/retry.py`. Start with the next real action only. If a tool is needed, prefer reading the file before proposing edits. Do not narrate a long plan."
            }
          ],
          temperature:0.2,
          top_p:0.95,
          top_k:20,
          repeat_penalty:1.05,
          stream:false,
          chat_template_kwargs:{enable_thinking:true},
          tool_choice:"auto",
          tools:[
            {
              type:"function",
              function:{
                name:"read_file",
                description:"Read a file from the repo.",
                parameters:{
                  type:"object",
                  properties:{path:{type:"string"}},
                  required:["path"]
                }
              }
            },
            {
              type:"function",
              function:{
                name:"run_tests",
                description:"Run a targeted test command and return the result.",
                parameters:{
                  type:"object",
                  properties:{command:{type:"string"}},
                  required:["command"]
                }
              }
            },
            {
              type:"function",
              function:{
                name:"apply_patch",
                description:"Apply a focused patch to the repo.",
                parameters:{
                  type:"object",
                  properties:{path:{type:"string"},summary:{type:"string"}},
                  required:["path","summary"]
                }
              }
            }
          ]
        }'
      ;;
    tool_followthrough:2)
      jq -cn \
        --arg model "${model_alias}" \
        --arg system_prompt "${system_prompt}" \
        '{
          model:$model,
          messages:[
            {role:"system", content:$system_prompt},
            {
              role:"user",
              content:"Task: fix a regression in `worker/retry.py`. Start with the next real action only. If a tool is needed, prefer reading the file before proposing edits. Do not narrate a long plan."
            },
            {
              role:"assistant",
              tool_calls:[
                {
                  id:"call_read_file_1",
                  type:"function",
                  function:{
                    name:"read_file",
                    arguments:"{\"path\":\"worker/retry.py\"}"
                  }
                }
              ]
            },
            {
              role:"tool",
              tool_call_id:"call_read_file_1",
              content:"def fetch_with_retry(client, url, retries=3, delay=0.5):\n    for attempt in range(retries):\n        try:\n            return client.get(url, timeout=5)\n        except Exception:\n            if attempt == retries:\n                raise\n            time.sleep(delay)\n            delay *= 2\n"
            },
            {
              role:"user",
              content:"You have the file contents now. Give the next concrete action only. Keep it short and action-oriented."
            }
          ],
          temperature:0.2,
          top_p:0.95,
          top_k:20,
          repeat_penalty:1.05,
          stream:false,
          chat_template_kwargs:{enable_thinking:true},
          tool_choice:"auto",
          tools:[
            {
              type:"function",
              function:{
                name:"read_file",
                description:"Read a file from the repo.",
                parameters:{
                  type:"object",
                  properties:{path:{type:"string"}},
                  required:["path"]
                }
              }
            },
            {
              type:"function",
              function:{
                name:"run_tests",
                description:"Run a targeted test command and return the result.",
                parameters:{
                  type:"object",
                  properties:{command:{type:"string"}},
                  required:["command"]
                }
              }
            },
            {
              type:"function",
              function:{
                name:"apply_patch",
                description:"Apply a focused patch to the repo.",
                parameters:{
                  type:"object",
                  properties:{path:{type:"string"},summary:{type:"string"}},
                  required:["path","summary"]
                }
              }
            }
          ]
        }'
      ;;
    *)
      echo "Unknown scenario request: ${scenario}:${turn}" >&2
      return 1
      ;;
  esac
}
