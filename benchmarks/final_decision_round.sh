#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-/tmp/localllm-final-decision}"
BARRAGE_HOST="${BARRAGE_HOST:-127.0.0.1}"
BARRAGE_PORT="${BARRAGE_PORT:-8091}"
BARRAGE_MODEL="${BARRAGE_MODEL:-}"
BARRAGE_BUDGETS="${BARRAGE_BUDGETS:-uncapped 500 1000}"
CURL_TIMEOUT="${CURL_TIMEOUT:-240}"

if [[ -z "${BARRAGE_MODEL}" ]]; then
  echo "Set BARRAGE_MODEL to the live model alias or model id." >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
chat_url="http://${BARRAGE_HOST}:${BARRAGE_PORT}/v1/chat/completions"

budget_payload() {
  local budget="$1"
  if [[ "${budget}" == "uncapped" ]]; then
    printf '{}'
  else
    jq -cn --argjson budget "${budget}" '{thinking_budget_tokens:$budget}'
  fi
}

run_request() {
  local label="$1"
  local budget="$2"
  local request_json="$3"
  local output_file="${OUT_DIR}/${label}_${budget}.json"
  printf '%s' "${request_json}" \
  | curl -fsS --max-time "${CURL_TIMEOUT}" "${chat_url}" \
      -H 'Content-Type: application/json' \
      -d @- > "${output_file}"
  jq -c \
    --arg label "${label}" \
    --arg budget "${budget}" \
    '{
      label:$label,
      budget:$budget,
      finish_reason:(.choices[0].finish_reason // ""),
      content_len:((.choices[0].message.content // "")|length),
      reasoning_len:((.choices[0].message.reasoning_content // "")|length),
      tool_calls:((.choices[0].message.tool_calls // [])|length),
      predicted_per_second:(.timings.predicted_per_second // 0),
      content_preview:((.choices[0].message.content // "")[0:240])
    }' \
    "${output_file}"
}

for budget in ${BARRAGE_BUDGETS}; do
  extra_json="$(budget_payload "${budget}")"

  request_json="$(jq -cn \
    --arg model "${BARRAGE_MODEL}" \
    --argjson extra "${extra_json}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:"The conversation is in English. Think in English and answer in English only."},
        {role:"user",content:"Someone in a Telegram chat says: I keep procrastinating on a big refactor. What is one practical first step I can do in 20 minutes? Reply in four sentences, friendly but not cheesy."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $extra')"
  run_request "telegram_direct" "${budget}" "${request_json}"

  request_json="$(jq -cn \
    --arg model "${BARRAGE_MODEL}" \
    --argjson extra "${extra_json}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:"The conversation is in English. Think in English and answer in English only."},
        {role:"user",content:"Say hello in one short sentence. Do not use tools unless absolutely necessary."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      tool_choice:"auto",
      tools:[
        {
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
        }
      ],
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $extra')"
  run_request "telegram_no_tool_with_tools" "${budget}" "${request_json}"

  first_request="$(jq -cn \
    --arg model "${BARRAGE_MODEL}" \
    --argjson extra "${extra_json}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:"The conversation is in English. Think in English and answer in English only."},
        {role:"user",content:"What is 2 + 2? Use the add tool if needed."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      tool_choice:"auto",
      tools:[
        {
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
        }
      ],
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $extra')"
  run_request "tool_flow_turn1" "${budget}" "${first_request}"
  assistant_message="$(jq -c '.choices[0].message' "${OUT_DIR}/tool_flow_turn1_${budget}.json")"
  second_request="$(jq -cn \
    --arg model "${BARRAGE_MODEL}" \
    --argjson assistant_message "${assistant_message}" \
    --argjson extra "${extra_json}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:"The conversation is in English. Think in English and answer in English only."},
        {role:"user",content:"What is 2 + 2? Use the add tool if needed."},
        $assistant_message,
        {role:"tool",tool_call_id:"call_1",content:"4"}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      tools:[
        {
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
        }
      ],
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $extra')"
  run_request "tool_flow_turn2" "${budget}" "${second_request}"

  request_json="$(jq -cn \
    --arg model "${BARRAGE_MODEL}" \
    --argjson extra "${extra_json}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:"The conversation is in English. Think in English and answer in English only."},
        {role:"user",content:"A flaky production bug appears only under load and may involve queue starvation, stale caches, and lock contention interacting together. Give me a practical debugging strategy with prioritized hypotheses, instrumentation, safe experiments, rollback considerations, and criteria for shipping a mitigation."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $extra')"
  run_request "debugging" "${budget}" "${request_json}"

  request_json="$(jq -cn \
    --arg model "${BARRAGE_MODEL}" \
    --argjson extra "${extra_json}" \
    '{
      model:$model,
      messages:[
        {role:"system",content:"The conversation is in English. Think in English and answer in English only."},
        {role:"user",content:"The agent proposed a broad refactor, but CI failed and two tests regressed. I want the next move, not a full restart. Explain how the agent should revise its plan, use existing evidence, limit scope, validate the fix, and decide when to stop iterating."}
      ],
      temperature:0.2,
      top_p:0.95,
      top_k:20,
      repeat_penalty:1.05,
      chat_template_kwargs:{enable_thinking:true},
      stream:false
    } + $extra')"
  run_request "agent_revision" "${budget}" "${request_json}"
done
