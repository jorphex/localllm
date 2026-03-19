from __future__ import annotations

import argparse
import json
from pathlib import Path

CONTINUE_PROMPT = (
    "Continue the same task. Take the next concrete action only. "
    "Use tools if needed and keep scope narrow."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--name")
    return parser.parse_args()


def opencode_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file from the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"filePath": {"type": "string"}},
                    "required": ["filePath"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "glob",
                "description": "Find files in the workspace matching a glob pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit",
                "description": "Edit a file in the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                        "oldString": {"type": "string"},
                        "newString": {"type": "string"},
                        "replaceAll": {"type": "boolean"},
                    },
                    "required": ["filePath"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "Run a shell command in the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        },
    ]


def text_parts(message: dict) -> list[str]:
    return [part["text"] for part in message["parts"] if part["type"] == "text"]


def tool_parts(message: dict) -> list[dict]:
    return [part for part in message["parts"] if part["type"] == "tool"]


def assistant_message_from_export(message: dict) -> list[dict]:
    content_parts = text_parts(message)
    tool_calls = []
    tool_results = []
    for part in tool_parts(message):
        tool_calls.append(
            {
                "id": part["callID"],
                "type": "function",
                "function": {
                    "name": part["tool"],
                    "arguments": json.dumps(part["state"].get("input", {}), separators=(",", ":")),
                },
            }
        )
        tool_results.append(
            {
                "role": "tool",
                "tool_call_id": part["callID"],
                "content": part["state"].get("output", ""),
            }
        )

    messages = []
    if tool_calls:
        messages.append({"role": "assistant", "tool_calls": tool_calls})
        messages.extend(tool_results)
    if content_parts and not tool_calls:
        messages.append({"role": "assistant", "content": "\n".join(content_parts).strip()})
    return messages


def history_before(messages: list[dict], assistant_index: int) -> list[dict]:
    history: list[dict] = []
    for message in messages[:assistant_index]:
        role = message["info"]["role"]
        if role == "user":
            content = "\n".join(text_parts(message)).strip()
            if content:
                history.append({"role": "user", "content": content})
        elif role == "assistant":
            history.extend(assistant_message_from_export(message))
    return history


def expectation_for(message: dict) -> dict:
    finish = message["info"].get("finish", "").replace("-", "_")
    expectation = {"finish_reason": finish}
    tool_names = [part["tool"] for part in tool_parts(message)]
    if tool_names:
        expectation["tool_names"] = tool_names
    return expectation


def needs_continuation_prompt(history: list[dict]) -> bool:
    return bool(history) and history[-1]["role"] != "user"


def convert(export_path: Path, fixture_name: str) -> dict:
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    turns = []
    messages = exported["messages"]
    for index, message in enumerate(messages):
        if message["info"]["role"] != "assistant":
            continue
        turn_messages = history_before(messages, index)
        if needs_continuation_prompt(turn_messages):
            turn_messages = [
                *turn_messages,
                {"role": "user", "content": CONTINUE_PROMPT},
            ]
        turn = {
            "name": f"turn{len(turns) + 1}",
            "messages": turn_messages,
            "expect": expectation_for(message),
        }
        if turn["expect"].get("tool_names"):
            turn["tool_choice"] = "auto"
            turn["tools"] = opencode_tools()
        turns.append(turn)
    return {
        "name": fixture_name,
        "defaults": {
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 20,
            "repeat_penalty": 1.05,
            "chat_template_kwargs": {"enable_thinking": True},
            "stream": False,
        },
        "turns": turns,
        "source_session_id": exported["info"]["id"],
        "source_title": exported["info"]["title"],
    }


def main() -> None:
    args = parse_args()
    export_path = Path(args.export).resolve()
    fixture_name = args.name or export_path.stem.replace(".export", "")
    fixture = convert(export_path, fixture_name)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, indent=2), encoding="utf-8")
    print(json.dumps({"fixture": fixture_name, "turns": len(fixture["turns"]), "out": str(out_path)}))


if __name__ == "__main__":
    main()
