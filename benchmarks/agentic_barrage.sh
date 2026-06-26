#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd -- "${BENCHMARK_DIR}/.." && pwd)"
source "${BENCHMARK_DIR}/config.sh"

OUT_DIR="${OUT_DIR:-/tmp/localllm-agentic-barrage}"
BARRAGE_HOST="${BARRAGE_HOST:-127.0.0.1}"
BARRAGE_PORT="${BARRAGE_PORT:-8091}"
BARRAGE_MODEL="${BARRAGE_MODEL:-}"
BARRAGE_BUDGETS="${BARRAGE_BUDGETS:-uncapped}"
BARRAGE_SCENARIOS="${BARRAGE_SCENARIOS:-$(benchmark_suite_items agentic_barrage | tr '\n' ' ')}"
CURL_TIMEOUT="${CURL_TIMEOUT:-300}"
SYSTEM_PROMPT="${SYSTEM_PROMPT:-You are a coding agent operating inside a local harness. Be concrete, scoped, and evidence-driven. Avoid restarting from scratch when revising.}"

if [[ -z "${BARRAGE_MODEL}" ]]; then
  echo "Set BARRAGE_MODEL to the live model alias or model id." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

health_url="http://${BARRAGE_HOST}:${BARRAGE_PORT}/health"
chat_url="http://${BARRAGE_HOST}:${BARRAGE_PORT}/v1/chat/completions"

wait_for_health() {
  local timeout="${1:-60}"
  for _ in $(seq 1 "${timeout}"); do
    if curl -fsS "${health_url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

budget_json() {
  local budget="$1"
  if [[ "${budget}" == "uncapped" ]]; then
    printf '{}'
  else
    jq -c -n --argjson budget "${budget}" '{thinking_budget_tokens:$budget}'
  fi
}

base_request() {
  local budget="$1"
  local extra_json="$2"
  jq -c -n \
    --arg model "${BARRAGE_MODEL}" \
    --arg system_prompt "${SYSTEM_PROMPT}" \
    --argjson extra "${extra_json}" \
    --argjson budget_extra "$(budget_json "${budget}")" \
    '{
      model:$model,
      messages:[{role:"system",content:$system_prompt}],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $budget_extra + $extra'
}

request_summary() {
  local label="$1"
  local scenario="$2"
  local budget="$3"
  local file="$4"
  jq -c \
    --arg label "${label}" \
    --arg scenario "${scenario}" \
    --arg budget "${budget}" \
    '{
      label:$label,
      scenario:$scenario,
      budget:$budget,
      finish_reason:(.choices[0].finish_reason // ""),
      content_len:((.choices[0].message.content // "")|length),
      reasoning_len:((.choices[0].message.reasoning_content // "")|length),
      tool_calls:((.choices[0].message.tool_calls // [])|length),
      predicted_per_second:(.timings.predicted_per_second // 0),
      has_scope_terms:((.choices[0].message.content // "")|test("scope|scoped|minimal|narrow"; "i")),
      has_evidence_terms:((.choices[0].message.content // "")|test("evidence|traceback|log|logs|failure|failing test|regress"; "i")),
      has_validation_terms:((.choices[0].message.content // "")|test("test|pytest|validate|verification|check"; "i")),
      has_stop_terms:((.choices[0].message.content // "")|test("stop|done|ship|exit criteria"; "i")),
      content_preview:((.choices[0].message.content // "")[0:240])
    }' \
    "${file}"
}

chat_once() {
  local scenario="$1"
  local budget="$2"
  local label="$3"
  local messages_json="$4"
  local extra_json="${5:-{}}"
  local output_file="${OUT_DIR}/${scenario}_${budget}_${label}.json"
  local request_json

  request_json="$(jq -c -n \
    --argjson base "$(base_request "${budget}" "${extra_json}")" \
    --argjson messages "${messages_json}" \
    '$base + {messages: ($base.messages + $messages)}')"

  printf '%s' "${request_json}" \
  | curl -fsS --max-time "${CURL_TIMEOUT}" "${chat_url}" \
      -H 'Content-Type: application/json' \
      -d @- > "${output_file}"

  request_summary "${label}" "${scenario}" "${budget}" "${output_file}"
}

chat_request_json() {
  local scenario="$1"
  local budget="$2"
  local label="$3"
  local request_json="$4"
  local output_file="${OUT_DIR}/${scenario}_${budget}_${label}.json"

  printf '%s' "${request_json}" \
  | curl -fsS --max-time "${CURL_TIMEOUT}" "${chat_url}" \
      -H 'Content-Type: application/json' \
      -d @- > "${output_file}"

  request_summary "${label}" "${scenario}" "${budget}" "${output_file}"
}

scenario_plan_then_revise() {
  local budget="$1"
  local messages_json first_file assistant_message second_messages

  messages_json=$(jq -c -n '[
    {
      role:"user",
      content:"You need to fix a flaky queue worker in a Python repo. Give a minimal first-pass plan only. Return exactly 6 bullets total, each short. Cover scope boundaries, evidence to collect before editing, validation, and what would make you stop iterating."
    }
  ]')
  chat_once "plan_then_revise" "${budget}" "turn1" "${messages_json}"
  first_file="${OUT_DIR}/plan_then_revise_${budget}_turn1.json"
  assistant_message=$(jq -c '.choices[0].message' "${first_file}")

  second_messages=$(jq -c -n \
    --argjson assistant "${assistant_message}" \
    '[
      {
        role:"user",
        content:"You need to fix a flaky queue worker in a Python repo. Give a minimal first-pass plan only. Return exactly 6 bullets total, each short. Cover scope boundaries, evidence to collect before editing, validation, and what would make you stop iterating."
      },
      $assistant,
      {
        role:"user",
        content:"The first patch regressed CI. Failing evidence: `test_retry_cancellation` now hangs, `test_queue_drain_order` fails with `AssertionError: expected [a,b,c], got [b,a,c]`, and production logs still show `worker backlog exceeded soft limit`. Do not restart from scratch. Revise the plan using this evidence. Return exactly 6 short bullets covering the next narrow change, what to test next, and when to stop."
      }
    ]')
  chat_once "plan_then_revise" "${budget}" "turn2" "${second_messages}"
}

scenario_evidence_triage() {
  local budget="$1"
  local messages_json
  messages_json=$(jq -c -n '[
    {
      role:"user",
      content:"You are triaging a coding-agent run. Available evidence: `pytest -q` shows `test_cache_eviction_order` failing after a refactor, a reviewer says the patch touched too many files, and a production trace shows lock contention on `SessionStore.flush`. Explain the next move only. Return exactly 5 short bullets: what evidence matters most, what to change next, what not to change yet, and how to verify the narrow fix."
    }
  ]')
  chat_once "evidence_triage" "${budget}" "turn1" "${messages_json}"
}

scenario_review_then_retry() {
  local budget="$1"
  local messages_json first_file assistant_message second_messages

  messages_json=$(jq -c -n '[
    {
      role:"user",
      content:"You are a coding agent fixing a regression in a repo. Propose a first patch approach only. Return exactly 5 short bullets covering the minimal change, what evidence you would consult first, what tests you would run, and what would be out of scope."
    }
  ]')
  chat_once "review_then_retry" "${budget}" "turn1" "${messages_json}"
  first_file="${OUT_DIR}/review_then_retry_${budget}_turn1.json"
  assistant_message=$(jq -c '.choices[0].message' "${first_file}")

  second_messages=$(jq -c -n \
    --argjson assistant "${assistant_message}" \
    '[
      {
        role:"user",
        content:"You are a coding agent fixing a regression in a repo. Propose a first patch approach only. Return exactly 5 short bullets covering the minimal change, what evidence you would consult first, what tests you would run, and what would be out of scope."
      },
      $assistant,
      {
        role:"user",
        content:"Review feedback on the first patch: it touched 7 files, mixed refactoring with behavior changes, and skipped the targeted retry test. Keep the original goal, but revise the next step instead of restarting. Return exactly 5 short bullets covering the narrower patch, the one test to run first, the evidence you would reuse, what stays out of scope, and when to stop."
      }
    ]')
  chat_once "review_then_retry" "${budget}" "turn2" "${second_messages}"
}

scenario_codex_workflow() {
  local budget="$1"
  local request_json first_file assistant_message tool_call_id second_request_json
  request_json=$(jq -c -n \
    --arg model "${BARRAGE_MODEL}" \
    --argjson budget_extra "$(budget_json "${budget}")" \
    '{
      model:$model,
      messages:[
        {
          role:"system",
          content:"You are Codex, a coding agent. Workflow: plan -> implement -> check -> fix -> verify -> review. Keep scope narrow, use evidence before editing, and do not restart from scratch when feedback arrives. If tools are available, use them deliberately."
        },
        {
          role:"user",
          content:"Task: fix a flaky retry helper in `worker/retry.py`. Start with the next concrete move only. If a tool is needed, prefer reading the file first; otherwise explain the exact first step and what evidence you need."
        }
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
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
      ],
      stream:false
    } + $budget_extra')
  chat_request_json "codex_workflow" "${budget}" "turn1" "${request_json}"

  first_file="${OUT_DIR}/codex_workflow_${budget}_turn1.json"
  assistant_message=$(jq -c '.choices[0].message' "${first_file}")
  tool_call_id=$(jq -r '.choices[0].message.tool_calls[0].id // "call_1"' "${first_file}")
  second_request_json=$(jq -c -n \
    --arg model "${BARRAGE_MODEL}" \
    --argjson budget_extra "$(budget_json "${budget}")" \
    --argjson assistant "${assistant_message}" \
    --arg tool_call_id "${tool_call_id}" \
    '{
      model:$model,
      messages:[
        {
          role:"system",
          content:"You are Codex, a coding agent. Workflow: plan -> implement -> check -> fix -> verify -> review. Keep scope narrow, use evidence before editing, and do not restart from scratch when feedback arrives. If tools are available, use them deliberately."
        },
        {
          role:"user",
          content:"Task: fix a flaky retry helper in `worker/retry.py`. Start with the next concrete move only. If a tool is needed, prefer reading the file first; otherwise explain the exact first step and what evidence you need."
        },
        $assistant,
        {
          role:"tool",
          tool_call_id:$tool_call_id,
          content:"File: worker/retry.py\n\nimport asyncio\n\nasync def fetch_with_retry(client, url, retries=3, delay=0.5):\n    for attempt in range(retries):\n        try:\n            return await client.get(url, timeout=5)\n        except Exception:\n            if attempt == retries:\n                raise\n            await asyncio.sleep(delay)\n            delay *= 2\n"
        },
        {
          role:"user",
          content:"Now give the next narrow step only. Do not restart the whole plan. Mention the exact change, the targeted test you would run, and the stop condition."
        }
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
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
      ],
      stream:false
    } + $budget_extra')
  chat_request_json "codex_workflow" "${budget}" "turn2" "${second_request_json}"
}

scenario_tool_restraint() {
  local budget="$1"
  local request_json
  request_json=$(jq -c -n \
    --arg model "${BARRAGE_MODEL}" \
    --arg system_prompt "${SYSTEM_PROMPT}" \
    --argjson budget_extra "$(budget_json "${budget}")" \
    '{
      model:$model,
      messages:[
        {role:"system",content:$system_prompt},
        {role:"user",content:"Reply in one short sentence: what is a sensible first step for a risky refactor? Do not call tools unless they are truly necessary."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      tool_choice:"auto",
      tools:[{
        type:"function",
        function:{
          name:"run_tests",
          description:"Run the repo test suite and return a summary.",
          parameters:{
            type:"object",
            properties:{pattern:{type:"string"}},
            required:["pattern"]
          }
        }
      }],
      stream:false
    } + $budget_extra')
  chat_request_json "tool_restraint" "${budget}" "turn1" "${request_json}"
}

scenario_tool_followthrough() {
  local budget="$1"
  local request_json first_file assistant_message tool_call_id second_request_json

  request_json=$(jq -c -n \
    --arg model "${BARRAGE_MODEL}" \
    --arg system_prompt "${SYSTEM_PROMPT}" \
    --argjson budget_extra "$(budget_json "${budget}")" \
    '{
      model:$model,
      messages:[
        {role:"system",content:$system_prompt},
        {role:"user",content:"What is 2 + 2? Use the add tool if needed."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      tool_choice:"auto",
      tools:[{
        type:"function",
        function:{
          name:"add",
          description:"Add two integers and return the sum.",
          parameters:{
            type:"object",
            properties:{a:{type:"integer"},b:{type:"integer"}},
            required:["a","b"]
          }
        }
      }],
      stream:false
    } + $budget_extra')
  chat_request_json "tool_followthrough" "${budget}" "turn1" "${request_json}"

  first_file="${OUT_DIR}/tool_followthrough_${budget}_turn1.json"
  assistant_message=$(jq -c '.choices[0].message' "${first_file}")
  tool_call_id=$(jq -r '.choices[0].message.tool_calls[0].id // "call_1"' "${first_file}")
  second_request_json=$(jq -c -n \
    --arg model "${BARRAGE_MODEL}" \
    --arg system_prompt "${SYSTEM_PROMPT}" \
    --argjson budget_extra "$(budget_json "${budget}")" \
    --argjson assistant "${assistant_message}" \
    --arg tool_call_id "${tool_call_id}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:$system_prompt},
        {role:"user",content:"What is 2 + 2? Use the add tool if needed."},
        $assistant,
        {role:"tool",tool_call_id:$tool_call_id,content:"4"}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      tools:[{
        type:"function",
        function:{
          name:"add",
          description:"Add two integers and return the sum.",
          parameters:{
            type:"object",
            properties:{a:{type:"integer"},b:{type:"integer"}},
            required:["a","b"]
          }
        }
      }],
      stream:false
    } + $budget_extra')
  chat_request_json "tool_followthrough" "${budget}" "turn2" "${second_request_json}"
}

wait_for_health 60
printf 'MODEL %s URL %s\n' "${BARRAGE_MODEL}" "${chat_url}"

for budget in ${BARRAGE_BUDGETS}; do
  for scenario in ${BARRAGE_SCENARIOS}; do
    "scenario_${scenario}" "${budget}"
  done
done

python3 "${BENCHMARK_DIR}/agentic_barrage_score.py" "${OUT_DIR}"
PUBLISH_LABEL="${BENCHMARK_PUBLISH_LABEL:-$(basename "${OUT_DIR}")}"
python3 "${BENCHMARK_DIR}/publish_summary.py" "${OUT_DIR}" agentic_barrage "${PUBLISH_LABEL}"