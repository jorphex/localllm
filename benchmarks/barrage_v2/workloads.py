from __future__ import annotations


PERFORMANCE_WORKLOADS = (
    {"id": "cold_pp_short", "kind": "chat", "repeat": 80, "max_tokens": 1},
    {"id": "cold_pp_long", "kind": "chat", "repeat": 1600, "max_tokens": 1},
    {"id": "direct_tg", "kind": "chat", "repeat": 4, "max_tokens": 128, "ignore_eos": True},
    {"id": "agent_stream", "kind": "stream", "repeat": 32, "max_tokens": 128},
    {"id": "reference_agent_loop", "kind": "agent_loop", "max_tokens": 64},
)

TOOL_CONTRACTS = (
    {
        "id": "tool_restraint",
        "split": "core",
        "messages": [{"role": "user", "content": "Say hello in one sentence. Do not use a tool."}],
        "expect_tool": None,
    },
    {
        "id": "tool_followthrough",
        "split": "core",
        "messages": [
            {
                "role": "user",
                "content": "What stable release does barrage have? Use the release_lookup tool before answering.",
            }
        ],
        "expect_tool": "release_lookup",
        "expect_args": {"package": "barrage", "channel": "stable"},
        "tool_result": "barrage stable release is 2.4.1",
        "expect_final": "2.4.1",
    },
    {
        "id": "tool_restraint_holdout",
        "split": "holdout",
        "messages": [{"role": "user", "content": "Explain why tests should be deterministic in one sentence. Do not use a tool."}],
        "expect_tool": None,
    },
)


def selected_items(items: tuple[dict, ...], include_holdout: bool) -> tuple[dict, ...]:
    return tuple(item for item in items if include_holdout or item.get("split", "core") == "core")


def repeated_prompt(repeat: int) -> str:
    return (
        "Benchmark context: preserve tool schemas, append-only history, and reproducible timing. "
        * repeat
    ) + "Return the requested result directly."


def agent_messages(repeat: int) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "You are a coding agent. Inspect evidence before acting and keep scope narrow.",
        },
        {
            "role": "user",
            "content": repeated_prompt(repeat) + " State the next verification step in one sentence.",
        },
    ]


def release_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "release_lookup",
            "description": "Look up the stable release of a package.",
            "parameters": {
                "type": "object",
                "properties": {
                    "package": {"type": "string"},
                    "channel": {"type": "string", "enum": ["stable", "preview"]},
                },
                "required": ["package", "channel"],
                "additionalProperties": False,
            },
        },
    }
