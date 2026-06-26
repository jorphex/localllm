from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx

from benchmarks.result_summaries import replay_fixture_metadata, stable_digest


REQUEST_TIMEOUT_SECONDS = float(os.environ.get("LOCALLLM_BENCH_REQUEST_TIMEOUT", "1800"))


def normalize_finish_reason(value: str) -> str:
    return value.replace("-", "_")


def tool_set_jaccard(expected: list[str], observed: list[str]) -> float:
    expected_set = set(expected)
    observed_set = set(observed)
    union = expected_set | observed_set
    if not union:
        return 1.0
    intersection = expected_set & observed_set
    return len(intersection) / len(union)


def partial_credit(summary: dict) -> dict[str, float]:
    expected_tools = summary["expect"].get("tool_names") or []
    observed_tools = summary["tool_names"]
    finish_match = float(summary["matches_finish_reason"])
    jaccard = tool_set_jaccard(expected_tools, observed_tools)
    count_match = 1.0 if len(expected_tools) == len(observed_tools) else 0.0
    return {
        "finish_reason_match": finish_match,
        "tool_set_jaccard": jaccard,
        "tool_count_match": count_match,
        "partial_score": round((finish_match + jaccard + count_match) / 3.0, 4),
    }


def turn_matches_expectations(summary: dict) -> bool:
    return summary["matches_finish_reason"] and summary["matches_tool_names"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def chat_once(client: httpx.Client, base_url: str, payload: dict) -> tuple[dict, float]:
    started = time.perf_counter()
    response = client.post(
        f"{base_url}/v1/chat/completions",
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


def summary_for_turn(turn: dict, payload: dict, response: dict, elapsed: float) -> dict:
    message = response["choices"][0]["message"]
    observed_tool_names = [call["function"]["name"] for call in message.get("tool_calls", [])]
    expected = turn.get("expect", {})
    summary = {
        "turn": turn["name"],
        "elapsed_seconds": elapsed,
        "request_digest": stable_digest(payload),
        "response_digest": stable_digest(response),
        "finish_reason": normalize_finish_reason(response["choices"][0].get("finish_reason", "")),
        "content_len": len(message.get("content", "")),
        "reasoning_len": len(message.get("reasoning_content", "")),
        "predicted_per_second": response.get("timings", {}).get("predicted_per_second", 0),
        "prompt_per_second": response.get("timings", {}).get("prompt_per_second", 0),
        "tool_names": observed_tool_names,
        "expect": expected,
        "matches_finish_reason": (
            expected.get("finish_reason") is None
            or normalize_finish_reason(expected.get("finish_reason", ""))
            == normalize_finish_reason(response["choices"][0].get("finish_reason", ""))
        ),
        "matches_tool_names": (
            not expected.get("tool_names")
            or expected.get("tool_names") == observed_tool_names
        ),
        "request_message_count": len(payload.get("messages", [])),
    }
    summary["matches_expectations"] = turn_matches_expectations(summary)
    summary.update(partial_credit(summary))
    return summary


def failed_summary_for_turn(
    turn: dict,
    payload: dict,
    elapsed: float,
    error_type: str,
    error_message: str,
) -> dict:
    expected = turn.get("expect", {})
    return {
        "turn": turn["name"],
        "elapsed_seconds": elapsed,
        "request_digest": stable_digest(payload),
        "response_digest": "",
        "finish_reason": "error",
        "content_len": 0,
        "reasoning_len": 0,
        "predicted_per_second": 0,
        "prompt_per_second": 0,
        "tool_names": [],
        "expect": expected,
        "matches_finish_reason": False,
        "matches_tool_names": False,
        "request_message_count": len(payload.get("messages", [])),
        "matches_expectations": False,
        "error_type": error_type,
        "error_message": error_message,
    }


def main() -> None:
    args = parse_args()
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "schema_version": replay_fixture_metadata(fixture)["schema_version"],
        "fixture": fixture["name"],
        "fixture_metadata": replay_fixture_metadata(fixture),
        "model": args.model,
        "turns": [],
    }

    client = httpx.Client()
    try:
        defaults = fixture.get("defaults", {})
        for turn in fixture["turns"]:
            payload = {"model": args.model, **defaults}
            payload["messages"] = turn["messages"]
            if "tools" in turn:
                payload["tools"] = turn["tools"]
            if "tool_choice" in turn:
                payload["tool_choice"] = turn["tool_choice"]
            stem = turn["name"]
            (out_dir / f"{stem}.request.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            started = time.perf_counter()
            try:
                response = client.post(
                    f"{args.base_url}/v1/chat/completions",
                    json=payload,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                elapsed = time.perf_counter() - started
                response.raise_for_status()
                response_json = response.json()
            except httpx.HTTPError as exc:
                elapsed = time.perf_counter() - started
                summary = failed_summary_for_turn(
                    turn,
                    payload,
                    elapsed,
                    type(exc).__name__,
                    str(exc),
                )
                results["turns"].append(summary)
                (out_dir / f"{stem}.summary.json").write_text(
                    json.dumps(summary, indent=2), encoding="utf-8"
                )
                print(json.dumps(summary))
                break

            summary = summary_for_turn(turn, payload, response_json, elapsed)
            results["turns"].append(summary)

            (out_dir / f"{stem}.response.json").write_text(
                json.dumps(response_json, indent=2), encoding="utf-8"
            )
            (out_dir / f"{stem}.summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
            print(json.dumps(summary))
    finally:
        client.close()

    results["all_expectations_met"] = all(turn["matches_expectations"] for turn in results["turns"])
    results["matched_turns"] = sum(1 for turn in results["turns"] if turn["matches_expectations"])
    results["turn_count"] = len(results["turns"])
    (out_dir / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"fixture": fixture["name"], "model": args.model, "all_expectations_met": results["all_expectations_met"]}))


if __name__ == "__main__":
    main()