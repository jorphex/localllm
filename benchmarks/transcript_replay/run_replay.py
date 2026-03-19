from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def normalize_finish_reason(value: str) -> str:
    return value.replace("-", "_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def chat_once(client: httpx.Client, base_url: str, payload: dict) -> tuple[dict, float]:
    started = time.perf_counter()
    response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=300.0)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


def summary_for_turn(turn: dict, payload: dict, response: dict, elapsed: float) -> dict:
    message = response["choices"][0]["message"]
    observed_tool_names = [call["function"]["name"] for call in message.get("tool_calls", [])]
    expected = turn.get("expect", {})
    return {
        "turn": turn["name"],
        "elapsed_seconds": elapsed,
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


def main() -> None:
    args = parse_args()
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "fixture": fixture["name"],
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

            response, elapsed = chat_once(client, args.base_url, payload)
            summary = summary_for_turn(turn, payload, response, elapsed)
            results["turns"].append(summary)

            stem = turn["name"]
            (out_dir / f"{stem}.request.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            (out_dir / f"{stem}.response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")
            (out_dir / f"{stem}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(summary))
    finally:
        client.close()

    results["all_expectations_met"] = all(
        turn["matches_finish_reason"] and turn["matches_tool_names"] for turn in results["turns"]
    )
    (out_dir / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"fixture": fixture["name"], "model": args.model, "all_expectations_met": results["all_expectations_met"]}))


if __name__ == "__main__":
    main()
