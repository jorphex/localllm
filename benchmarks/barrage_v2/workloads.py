from __future__ import annotations

from typing import Any


PERFORMANCE_WORKLOADS = (
    {"id": "cold_pp_short", "kind": "chat", "repeat": 80, "max_tokens": 1},
    {"id": "context_recall_8k", "kind": "context_recall", "repeat": 500, "max_tokens": 32},
    {"id": "context_recall_32k", "kind": "context_recall", "repeat": 2000, "max_tokens": 32},
    {"id": "context_recall_64k", "kind": "context_recall", "repeat": 4000, "max_tokens": 32},
    {"id": "context_recall_120k", "kind": "context_recall", "repeat": 6600, "max_tokens": 32},
    {"id": "direct_tg", "kind": "chat", "repeat": 4, "max_tokens": 128, "ignore_eos": True},
    {"id": "agent_stream", "kind": "stream", "repeat": 32, "max_tokens": 128},
    {"id": "reference_agent_loop", "kind": "agent_loop", "max_tokens": 64},
    {"id": "warm_append_8k", "kind": "warm", "repeat": 500, "max_tokens": 8},
    {"id": "warm_append_32k", "kind": "warm", "repeat": 2000, "max_tokens": 8},
)

CONCURRENCY_WORKLOADS = (
    {
        "id": "dual_generation",
        "jobs": ({"repeat": 4, "max_tokens": 64}, {"repeat": 5, "max_tokens": 64}),
    },
    {
        "id": "mixed_prefill_generation",
        "jobs": ({"repeat": 500, "max_tokens": 1}, {"repeat": 4, "max_tokens": 64}),
    },
)

VISION_WORKLOAD = {
    "id": "quadrant_1024",
    "width": 1024,
    "height": 1024,
    "expected": {"top_left": "red", "bottom_right": "yellow"},
}


TOOL_CONTRACTS = (
    {
        "id": "tool_restraint",
        "split": "core",
        "messages": [{"role": "user", "content": "Say hello in one sentence. Do not use a tool."}],
        "steps": [],
        "final_nonempty": True,
    },
    {
        "id": "tool_followthrough",
        "split": "core",
        "messages": [
            {
                "role": "user",
                "content": "What stable release does barrage have? Use release_lookup before answering.",
            }
        ],
        "steps": [
            {
                "calls": [
                    {
                        "name": "release_lookup",
                        "arguments": {"package": "barrage", "channel": "stable"},
                        "result": "barrage stable release is 2.4.1",
                    }
                ]
            }
        ],
        "final_contains": ["2.4.1"],
    },
    {
        "id": "dependent_tool_sequence",
        "split": "core",
        "messages": [
            {
                "role": "user",
                "content": "Find barrage's stable release, then check whether plugin_core supports that exact version. Answer with the version and compatibility.",
            }
        ],
        "steps": [
            {
                "calls": [
                    {
                        "name": "release_lookup",
                        "arguments": {"package": "barrage", "channel": "stable"},
                        "result": "barrage stable release is 2.4.1",
                    }
                ]
            },
            {
                "calls": [
                    {
                        "name": "compatibility_lookup",
                        "arguments": {"component": "plugin_core", "version": "2.4.1"},
                        "result": "plugin_core supports barrage 2.4.1",
                    }
                ]
            },
        ],
        "final_contains": ["2.4.1", "support"],
    },
    {
        "id": "parallel_tool_calls",
        "split": "core",
        "messages": [
            {
                "role": "user",
                "content": "Look up the stable releases of barrage and agentkit. Make both independent calls together, then report both versions.",
            }
        ],
        "steps": [
            {
                "order": "any",
                "calls": [
                    {
                        "name": "release_lookup",
                        "arguments": {"package": "barrage", "channel": "stable"},
                        "result": "barrage stable release is 2.4.1",
                    },
                    {
                        "name": "release_lookup",
                        "arguments": {"package": "agentkit", "channel": "stable"},
                        "result": "agentkit stable release is 7.3.0",
                    },
                ],
            }
        ],
        "final_contains": ["2.4.1", "7.3.0"],
    },
    {
        "id": "tool_error_recovery",
        "split": "core",
        "messages": [
            {
                "role": "user",
                "content": "Find barrage's preview release. Try release_lookup first; if that source fails, recover with mirror_lookup and report the preview version.",
            }
        ],
        "steps": [
            {
                "calls": [
                    {
                        "name": "release_lookup",
                        "arguments": {"package": "barrage", "channel": "preview"},
                        "result": "ERROR: primary release index unavailable",
                    }
                ]
            },
            {
                "calls": [
                    {
                        "name": "mirror_lookup",
                        "arguments": {"package": "barrage", "channel": "preview"},
                        "result": "barrage preview release is 2.5.0-rc1",
                    }
                ]
            },
        ],
        "final_contains": ["2.5.0-rc1"],
    },
    {
        "id": "duplicate_call_avoidance",
        "split": "holdout",
        "messages": [
            {
                "role": "user",
                "content": "Use release_lookup exactly once to find agentkit's stable release, then answer without repeating the call.",
            }
        ],
        "steps": [
            {
                "calls": [
                    {
                        "name": "release_lookup",
                        "arguments": {"package": "agentkit", "channel": "stable"},
                        "result": "agentkit stable release is 7.3.0",
                    }
                ]
            }
        ],
        "final_contains": ["7.3.0"],
    },
    {
        "id": "tool_restraint_holdout",
        "split": "holdout",
        "messages": [
            {
                "role": "user",
                "content": "Explain why deterministic tests matter in one sentence. Do not use a tool.",
            }
        ],
        "steps": [],
        "final_nonempty": True,
    },
)


def selected_items(items: tuple[dict, ...], include_holdout: bool) -> tuple[dict, ...]:
    return tuple(item for item in items if include_holdout or item.get("split", "core") == "core")


def repeated_prompt(repeat: int) -> str:
    return (
        "Benchmark context: preserve tool schemas, append-only history, and reproducible timing. "
        * repeat
    ) + "Return the requested result directly."


def context_recall_prompt(repeat: int) -> tuple[str, tuple[str, ...]]:
    markers = ("EMBER-417", "HARBOR-263", "LANTERN-905")
    first = repeat // 3
    second = (repeat * 2) // 3
    chunks: list[str] = []
    for index in range(repeat):
        if index == first:
            chunks.append(f"Important checkpoint code: {markers[0]}. ")
        elif index == second:
            chunks.append(f"Important checkpoint code: {markers[1]}. ")
        else:
            chunks.append(
                "Agent history record: inspect evidence, preserve narrow scope, execute tools, and verify results. "
            )
    chunks.append(f"Final checkpoint code: {markers[2]}. Return only the three checkpoint codes in order.")
    return "".join(chunks), markers


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


def benchmark_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "release_lookup",
                "description": "Look up a package release in the primary index.",
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
        },
        {
            "type": "function",
            "function": {
                "name": "mirror_lookup",
                "description": "Look up a package release in the fallback mirror.",
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
        },
        {
            "type": "function",
            "function": {
                "name": "compatibility_lookup",
                "description": "Check whether a component supports an exact barrage version.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "component": {"type": "string"},
                        "version": {"type": "string"},
                    },
                    "required": ["component", "version"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def release_tool() -> dict[str, Any]:
    return benchmark_tools()[0]
