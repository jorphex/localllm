from __future__ import annotations

import argparse
import base64
import json
import random
import re
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import httpx

from benchmarks.barrage_v2 import SCHEMA_VERSION
from benchmarks.barrage_v2.artifacts import (
    aggregate_trials,
    binary_summary,
    environment_metadata,
    grouped_binary_summary,
    stable_digest,
    write_json,
)
from benchmarks.barrage_v2.config import load_config
from benchmarks.barrage_v2.production_driver import run_driver
from benchmarks.barrage_v2.sandbox import TASKS, run_task, selected_tasks
from benchmarks.barrage_v2.workloads import (
    CONCURRENCY_WORKLOADS,
    PERFORMANCE_WORKLOADS,
    TOOL_CONTRACTS,
    VISION_WORKLOAD,
    agent_messages,
    benchmark_tools,
    context_recall_prompt,
    release_tool,
    repeated_prompt,
    selected_items,
)


def timing_record(
    workload: str,
    trial: int,
    request: dict[str, Any],
    response: dict[str, Any],
    elapsed: float,
    *,
    execution_order: int,
    ttft: float | None = None,
) -> dict[str, Any]:
    timings = response.get("timings", {})
    return {
        "workload": workload,
        "trial": trial,
        "passed": True,
        "execution_order": execution_order,
        "request_digest": stable_digest(request),
        "response_digest": stable_digest(response),
        "request": request,
        "response": response,
        "elapsed_seconds": round(elapsed, 4),
        "ttft_seconds": round(ttft, 4) if ttft is not None else None,
        "prompt_n": timings.get("prompt_n"),
        "cache_n": timings.get("cache_n"),
        "predicted_n": timings.get("predicted_n"),
        "prompt_per_second": timings.get("prompt_per_second"),
        "predicted_per_second": timings.get("predicted_per_second"),
        "finish_reason": response.get("choices", [{}])[0].get("finish_reason"),
    }


def chat_payload(model: str, prompt: str, max_tokens: int, *, cache_prompt: bool, ignore_eos: bool = False) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "seed": 42,
        "max_tokens": max_tokens,
        "ignore_eos": ignore_eos,
        "cache_prompt": cache_prompt,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": False,
    }


def streamed_chat(client: httpx.Client, base_url: str, payload: dict[str, Any], timeout: float) -> tuple[dict[str, list[dict[str, Any]] | dict[str, Any]], float, float]:
    started = time.perf_counter()
    first_event: float | None = None
    final: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    timing_event: dict[str, Any] = {}
    with client.stream("POST", f"{base_url}/v1/chat/completions", json={**payload, "stream": True}, timeout=timeout) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                continue
            event = json.loads(data)
            events.append(event)
            if event.get("timings"):
                timing_event = event
            delta = event.get("choices", [{}])[0].get("delta", {})
            if first_event is None and any(key in delta for key in ("content", "reasoning_content", "tool_calls")):
                first_event = time.perf_counter()
            final = event
    elapsed = time.perf_counter() - started
    return {"final": final, "timing": timing_event, "events": events}, elapsed, (first_event or time.perf_counter()) - started


def streamed_content(events: list[dict[str, Any]]) -> str:
    return "".join(
        str(event.get("choices", [{}])[0].get("delta", {}).get("content") or "")
        for event in events
    )


def run_performance(client: httpx.Client, base_url: str, model: str, repeats: int, timeout: float, order_seed: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    jobs = [(workload, trial) for workload in PERFORMANCE_WORKLOADS for trial in range(1, repeats + 1)]
    random.Random(order_seed).shuffle(jobs)
    for execution_order, (workload, trial) in enumerate(jobs, start=1):
        payload: dict[str, Any] | None = None
        initial_response: dict[str, Any] | None = None
        phase = "request"
        try:
            if workload["kind"] == "warm":
                prefix = repeated_prompt(workload["repeat"])
                payload = chat_payload(model, prefix, 1, cache_prompt=True)
                payload["id_slot"] = 0
                prime_request = payload
                phase = "prime"
                response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                response.raise_for_status()
                prime_response = response.json()
                payload = chat_payload(
                    model,
                    prefix + "\nAppend-only turn: return CACHE_OK.",
                    workload["max_tokens"],
                    cache_prompt=True,
                )
                payload["id_slot"] = 0
                phase = "append"
                started = time.perf_counter()
                response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                elapsed = time.perf_counter() - started
                response.raise_for_status()
                record = timing_record(workload["id"], trial, payload, response.json(), elapsed, execution_order=execution_order)
                record["prime_request"] = prime_request
                record["prime_response"] = prime_response
                record["predicted_per_second"] = None
                record["cache_hit"] = bool(record.get("cache_n"))
                record["passed"] = record["cache_hit"]
                records.append(record)
                continue
            if workload["kind"] == "context_recall":
                prompt, markers = context_recall_prompt(workload["repeat"])
                payload = chat_payload(model, prompt, workload["max_tokens"], cache_prompt=False)
                phase = "stream"
                stream_data, elapsed, ttft = streamed_chat(client, base_url, payload, timeout)
                timing = stream_data["timing"] or stream_data["final"]
                record = timing_record(workload["id"], trial, payload, timing, elapsed, execution_order=execution_order, ttft=ttft)
                content = streamed_content(stream_data["events"])
                record["stream_final_event"] = stream_data["final"]
                record["stream_timing_event"] = stream_data["timing"]
                record["stream_events"] = stream_data["events"]
                record["answer_text"] = content
                record["expected_markers"] = list(markers)
                record["recall_passed"] = all(marker in content for marker in markers)
                record["passed"] = record["recall_passed"]
                record["predicted_per_second"] = None
                records.append(record)
                continue
            if workload["id"] == "agent_stream":
                payload = {
                    "model": model,
                    "messages": agent_messages(workload["repeat"]),
                    "temperature": 0,
                    "seed": 42,
                    "max_tokens": workload["max_tokens"],
                    "cache_prompt": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                phase = "stream"
                stream_data, elapsed, ttft = streamed_chat(client, base_url, payload, timeout)
                timing = stream_data["timing"] or stream_data["final"]
                record = timing_record(workload["id"], trial, payload, timing, elapsed, execution_order=execution_order, ttft=ttft)
                record["stream_final_event"] = stream_data["final"]
                record["stream_timing_event"] = stream_data["timing"]
                record["stream_events"] = stream_data["events"]
                records.append(record)
                continue
            if workload["kind"] == "agent_loop":
                initial = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Use release_lookup to find barrage stable release, then state it."}],
                    "tools": [release_tool()],
                    "tool_choice": "required",
                    "temperature": 0,
                    "seed": 42,
                    "max_tokens": workload["max_tokens"],
                    "cache_prompt": False,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                payload = initial
                phase = "agent_initial"
                started = time.perf_counter()
                response = client.post(f"{base_url}/v1/chat/completions", json=initial, timeout=timeout)
                response.raise_for_status()
                first = response.json()
                initial_response = first
                calls = first.get("choices", [{}])[0].get("message", {}).get("tool_calls") or []
                if len(calls) != 1 or calls[0].get("function", {}).get("name") != "release_lookup":
                    raise ValueError("reference agent loop did not produce release_lookup")
                try:
                    arguments = json.loads(calls[0].get("function", {}).get("arguments", ""))
                except json.JSONDecodeError:
                    arguments = None
                if arguments != {"package": "barrage", "channel": "stable"}:
                    raise ValueError("reference agent loop produced unexpected release_lookup arguments")
                followup = {
                    **initial,
                    "tool_choice": "none",
                    "messages": [
                        *initial["messages"],
                        first["choices"][0]["message"],
                        {"role": "tool", "tool_call_id": calls[0]["id"], "content": "barrage stable release is 2.4.1"},
                    ],
                }
                payload = followup
                phase = "agent_followup"
                response = client.post(f"{base_url}/v1/chat/completions", json=followup, timeout=timeout)
                elapsed = time.perf_counter() - started
                response.raise_for_status()
                final = response.json()
                final_message = final.get("choices", [{}])[0].get("message", {})
                if final_message.get("tool_calls"):
                    raise ValueError("reference agent loop made an unexpected follow-up tool call")
                if "2.4.1" not in str(final_message.get("content", "")):
                    raise ValueError("reference agent loop did not report the tool result")
                timings = [first.get("timings", {}), final.get("timings", {})]
                predicted_n = sum(int(timing.get("predicted_n") or 0) for timing in timings)
                prompt_n = sum(int(timing.get("prompt_n") or 0) for timing in timings)
                records.append(
                    {
                        "workload": workload["id"],
                        "trial": trial,
                        "passed": True,
                        "execution_order": execution_order,
                        "elapsed_seconds": round(elapsed, 4),
                        "agent_request_count": 2,
                        "agent_prompt_n": prompt_n,
                        "agent_predicted_n": predicted_n,
                        "agent_predicted_per_second": round(predicted_n / elapsed, 4) if elapsed else None,
                        "initial_request": initial,
                        "initial_response": first,
                        "followup_request": followup,
                        "followup_response": final,
                    }
                )
                continue
            payload = chat_payload(
                model,
                repeated_prompt(workload["repeat"]),
                workload["max_tokens"],
                cache_prompt=False,
                ignore_eos=bool(workload.get("ignore_eos")),
            )
            started = time.perf_counter()
            response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
            elapsed = time.perf_counter() - started
            response.raise_for_status()
            record = timing_record(workload["id"], trial, payload, response.json(), elapsed, execution_order=execution_order)
            if workload["id"].startswith("cold_pp_"):
                record["predicted_per_second"] = None
            records.append(record)
        except Exception as exc:  # noqa: BLE001
            failure = {
                "workload": workload["id"],
                "trial": trial,
                "execution_order": execution_order,
                "status": "error",
                "passed": False,
                "phase": phase,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "request": payload,
            }
            if initial_response is not None:
                failure["initial_response"] = initial_response
            records.append(failure)
    return records


def _tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for call in response.get("choices", [{}])[0].get("message", {}).get("tool_calls", []) or []:
        function = call.get("function", {})
        try:
            arguments = json.loads(function.get("arguments", ""))
        except (TypeError, json.JSONDecodeError):
            arguments = None
        calls.append({"id": call.get("id"), "name": function.get("name"), "arguments": arguments})
    return calls


def _calls_match(actual: list[dict[str, Any]], expected: list[dict[str, Any]], order: str) -> bool:
    actual_contract = [{"name": call.get("name"), "arguments": call.get("arguments")} for call in actual]
    expected_contract = [{"name": call.get("name"), "arguments": call.get("arguments")} for call in expected]
    if order == "any":
        def sort_key(value: dict[str, Any]) -> str:
            return json.dumps(value, sort_keys=True)

        return sorted(actual_contract, key=sort_key) == sorted(expected_contract, key=sort_key)
    return actual_contract == expected_contract


def run_tool_contracts(
    client: httpx.Client,
    base_url: str,
    model: str,
    timeout: float,
    contracts: list[dict[str, Any]] | None = None,
    *,
    trial: int = 1,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for contract in contracts or TOOL_CONTRACTS:
        record: dict[str, Any] = {"contract": contract["id"], "split": contract.get("split", "core"), "trial": trial}
        try:
            messages = list(contract["messages"])
            turns: list[dict[str, Any]] = []
            step_results: list[dict[str, Any]] = []
            for step_index, step in enumerate(contract.get("steps", []), start=1):
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": benchmark_tools(),
                    "tool_choice": "auto",
                    "temperature": 0,
                    "seed": 42 + trial,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
                if "initial_request" not in record:
                    record["initial_request"] = payload
                else:
                    record["followup_request"] = payload
                response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                response.raise_for_status()
                body = response.json()
                if "initial_response" not in record:
                    record["initial_response"] = body
                else:
                    record["followup_response"] = body
                message = body.get("choices", [{}])[0].get("message", {})
                actual_calls = _tool_calls(body)
                expected_calls = step["calls"]
                matched = _calls_match(actual_calls, expected_calls, str(step.get("order", "exact")))
                turns.append({"step": step_index, "request": payload, "response": body, "calls": actual_calls})
                step_results.append({"step": step_index, "matched": matched, "actual": actual_calls, "expected": expected_calls})
                if not matched:
                    break
                messages.append(message)
                result_calls = expected_calls
                if step.get("order") == "any":
                    result_calls = [
                        next(
                            expected
                            for expected in expected_calls
                            if expected["name"] == actual["name"] and expected["arguments"] == actual["arguments"]
                        )
                        for actual in actual_calls
                    ]
                for actual, expected in zip(actual_calls, result_calls, strict=True):
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": actual.get("id") or f"step-{step_index}",
                            "content": expected["result"],
                        }
                    )
            steps_ok = len(step_results) == len(contract.get("steps", [])) and all(step["matched"] for step in step_results)
            final_payload = {
                "model": model,
                "messages": messages,
                "tools": benchmark_tools(),
                "tool_choice": "auto",
                "temperature": 0,
                "seed": 42 + trial,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            record["followup_request"] = final_payload
            final_response = client.post(f"{base_url}/v1/chat/completions", json=final_payload, timeout=timeout)
            final_response.raise_for_status()
            final_body = final_response.json()
            record["followup_response"] = final_body
            final_message = final_body.get("choices", [{}])[0].get("message", {})
            final_content = str(final_message.get("content") or "")
            final_calls = _tool_calls(final_body)
            final_contains = [str(value).lower() for value in contract.get("final_contains", [])]
            final_ok = (
                not final_calls
                and all(value in final_content.lower() for value in final_contains)
                and (not contract.get("final_nonempty") or bool(final_content.strip()))
            )
            turns.append({"step": "final", "request": final_payload, "response": final_body, "calls": final_calls})
            record.update(
                {
                    "turns": turns,
                    "step_results": step_results,
                    "steps_ok": steps_ok,
                    "final_content": final_content,
                    "final_calls": final_calls,
                    "final_ok": final_ok,
                    "tool_ok": steps_ok and not final_calls,
                    "content_present": bool(final_content.strip()),
                    "passed": steps_ok and final_ok,
                }
            )
            if turns:
                record["initial_request"] = turns[0]["request"]
                record["initial_response"] = turns[0]["response"]
            if len(turns) > 1:
                record["followup_request"] = turns[1]["request"]
                record["followup_response"] = turns[1]["response"]
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            record["passed"] = False
            record["error_type"] = type(exc).__name__
            record["error_message"] = str(exc)
        records.append(record)
    return records


def run_concurrency(
    client: httpx.Client,
    base_url: str,
    model: str,
    repeats: int,
    timeout: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for workload in CONCURRENCY_WORKLOADS:
        for trial in range(1, repeats + 1):
            payloads = [
                chat_payload(
                    model,
                    repeated_prompt(job["repeat"]),
                    job["max_tokens"],
                    cache_prompt=False,
                    ignore_eos=job["max_tokens"] > 1,
                )
                for job in workload["jobs"]
            ]
            start_barrier = Barrier(len(payloads))
            started = time.perf_counter()

            def execute(payload: dict[str, Any]) -> dict[str, Any]:
                start_barrier.wait(timeout=timeout)
                request_started = time.perf_counter()
                try:
                    response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                    response.raise_for_status()
                    return {
                        "passed": True,
                        "elapsed_seconds": round(time.perf_counter() - request_started, 4),
                        "request": payload,
                        "response": response.json(),
                    }
                except Exception as exc:  # noqa: BLE001
                    return {
                        "passed": False,
                        "status": "error",
                        "elapsed_seconds": round(time.perf_counter() - request_started, 4),
                        "request": payload,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }

            with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
                requests = list(executor.map(execute, payloads))
            wall = time.perf_counter() - started
            predicted = sum(
                int(request.get("response", {}).get("timings", {}).get("predicted_n") or 0)
                for request in requests
            )
            records.append(
                {
                    "workload": workload["id"],
                    "trial": trial,
                    "passed": all(request["passed"] for request in requests),
                    "request_count": len(requests),
                    "successful_requests": sum(request["passed"] for request in requests),
                    "wall_seconds": round(wall, 4),
                    "aggregate_predicted_n": predicted,
                    "aggregate_predicted_per_second": round(predicted / wall, 4) if wall else None,
                    "requests": requests,
                }
            )
    return records


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def quadrant_image_data_url(size: int = 1024) -> str:
    colors = ((220, 30, 30), (30, 180, 60), (30, 80, 220), (240, 210, 30))
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            index = (2 if y >= size // 2 else 0) + (1 if x >= size // 2 else 0)
            rows.extend(colors[index])
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def run_vision(
    client: httpx.Client,
    base_url: str,
    model: str,
    repeats: int,
    timeout: float,
    props: dict[str, Any],
) -> dict[str, Any]:
    if not bool(props.get("modalities", {}).get("vision")):
        return {"applicable": False, "reason": "server reports vision=false", "trials": [], **binary_summary([])}
    image_url = quadrant_image_data_url(int(VISION_WORKLOAD["width"]))
    rows: list[dict[str, Any]] = []
    for trial in range(1, repeats + 1):
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Name the colors in the top-left and bottom-right quadrants. Answer only: TOP_LEFT=<color> BOTTOM_RIGHT=<color>."},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0,
            "seed": 42 + trial,
            "max_tokens": 32,
            "cache_prompt": False,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        started = time.perf_counter()
        try:
            response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            content = str(body.get("choices", [{}])[0].get("message", {}).get("content") or "")
            expected = VISION_WORKLOAD["expected"]
            passed = all(str(color).lower() in content.lower() for color in expected.values())
            rows.append(
                {
                    "trial": trial,
                    "passed": passed,
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                    "request": payload,
                    "request_digest": stable_digest(payload),
                    "response": body,
                    "answer_text": content,
                    "expected": expected,
                    "image": {
                        "format": "png",
                        "width": VISION_WORKLOAD["width"],
                        "height": VISION_WORKLOAD["height"],
                        "digest": stable_digest(image_url),
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "trial": trial,
                    "passed": False,
                    "status": "error",
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
    return {"applicable": True, "trials": rows, **binary_summary(rows)}


def validate_run(run: dict[str, Any], suites: set[str]) -> None:
    if run["schema_version"] != SCHEMA_VERSION:
        raise ValueError("schema version mismatch")
    for suite in suites:
        if not run["suites"].get(suite):
            raise ValueError(f"missing suite output: {suite}")


def split_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    return {
        split: binary_summary([row for row in rows if str(row.get("split", "core")) == split])
        for split in sorted({str(row.get("split", "core")) for row in rows})
    }


def selected_production_tasks(tasks: list[dict[str, Any]], include_holdout: bool) -> list[dict[str, Any]]:
    return [task for task in tasks if include_holdout or task.get("split", "core") == "core"]


def build_release_gate(
    run: dict[str, Any],
    manifest: dict[str, Any],
    cfg: dict[str, Any],
    requested: bool,
) -> dict[str, Any]:
    release_cfg = cfg["release"]
    profile_class = manifest["profile"]["class"]
    required_suites = list(
        release_cfg["production_required_suites"]
        if profile_class == "production"
        else release_cfg["fair_required_suites"]
    )
    vision = run.get("suites", {}).get("vision", {})
    if profile_class == "fair" and vision.get("applicable"):
        required_suites.append("vision")
    checks: list[dict[str, Any]] = []

    def add(check: str, passed: bool, evidence: Any) -> None:
        checks.append({"check": check, "passed": passed, "evidence": evidence})

    evaluation = manifest["evaluation"]
    if profile_class == "fair":
        add(
            "performance_repeats",
            int(evaluation["performance_repeats"]) >= int(release_cfg["minimum_performance_repeats"]),
            evaluation["performance_repeats"],
        )
    add(
        "quality_repeats",
        int(evaluation["quality_repeats"]) >= int(release_cfg["minimum_quality_repeats"]),
        evaluation["quality_repeats"],
    )
    if release_cfg.get("require_holdout"):
        add("holdout_enabled", bool(evaluation["include_holdout"]), evaluation["include_holdout"])
    for suite_name in required_suites:
        suite = run.get("suites", {}).get(suite_name)
        add(
            f"suite_{suite_name}_completed",
            isinstance(suite, dict) and suite.get("status") == "ok",
            suite.get("status") if isinstance(suite, dict) else "missing",
        )
        if not isinstance(suite, dict):
            continue
        if suite_name == "performance":
            reliability = {
                workload: metrics.get("reliability", {})
                for workload, metrics in suite.get("summary", {}).items()
            }
            add(
                "performance_reliability",
                bool(reliability)
                and all(item.get("passed") == item.get("total") and item.get("errors") == 0 for item in reliability.values()),
                reliability,
            )
        elif isinstance(suite.get("passed"), int) and isinstance(suite.get("total"), int):
            add(
                f"suite_{suite_name}_all_passed",
                suite["total"] > 0 and suite["passed"] == suite["total"],
                {"passed": suite["passed"], "total": suite["total"]},
            )
    if evaluation["include_holdout"]:
        for suite_name in ("tool_contract", "sandbox", "production"):
            suite = run.get("suites", {}).get(suite_name)
            if not isinstance(suite, dict):
                continue
            holdout = suite.get("splits", {}).get("holdout", {})
            add(
                f"suite_{suite_name}_holdout",
                int(holdout.get("total", 0)) > 0 and holdout.get("passed") == holdout.get("total"),
                holdout,
            )
    eligible = all(check["passed"] for check in checks)
    return {
        "requested": requested,
        "eligible": eligible,
        "passed": eligible if requested else None,
        "required_suites": required_suites,
        "checks": checks,
    }


def validate_fair_runtime(
    cfg: dict[str, Any],
    props: dict[str, Any],
    slots: list[dict[str, Any]],
    startup_log: str,
    *,
    stabilization: dict[str, Any] | None = None,
    launch_argv: list[str] | None = None,
    model_path: Path | None = None,
) -> dict[str, Any]:
    expected_context = int(cfg["fair_profile"]["context"])
    prop_context = props.get("default_generation_settings", {}).get("n_ctx")
    slot_contexts = [slot.get("n_ctx") for slot in slots]
    if prop_context != expected_context or not slot_contexts or any(context != expected_context for context in slot_contexts):
        raise ValueError(
            f"fair runtime context mismatch: expected {expected_context}, props={prop_context}, slots={slot_contexts}"
        )
    matches = re.findall(r"offloaded\s+(\d+)/(\d+)\s+layers to GPU", startup_log)
    if matches:
        offloaded, total = map(int, matches[-1])
        if offloaded != total:
            raise ValueError(f"fair runtime has partial GPU offload: {offloaded}/{total}")
    layer_assignments = re.findall(r"load_tensors:\s+layer\s+\d+\s+assigned to device\s+([^,\n]+)", startup_log)
    offload_evidence: dict[str, Any] | None = None
    if layer_assignments:
        cpu_assignments = [device.strip() for device in layer_assignments if device.strip().lower().startswith("cpu")]
        if cpu_assignments:
            raise ValueError(f"fair runtime assigned model layers to CPU: {cpu_assignments}")
        offload_evidence = {
            "evidence": "verbose_layer_assignment",
            "layer_assignment_count": len(layer_assignments),
            "assigned_devices": sorted(set(device.strip() for device in layer_assignments)),
        }
    argv = launch_argv or []
    if "--gpu-layers" not in argv or "auto" not in argv:
        raise ValueError("fair runtime lacks --gpu-layers auto evidence")
    if "-v" not in argv and "--verbose" not in argv:
        raise ValueError("fair runtime lacks verbose tensor-placement logging")
    if offload_evidence is None:
        raise ValueError("fair runtime did not retain verbose tensor-layer placement evidence")
    baseline = (stabilization or {}).get("gpu_mem", {}).get("used_mib")
    postload = (stabilization or {}).get("postload_gpu", {}).get("used_mib")
    if not isinstance(baseline, int) or not isinstance(postload, int):
        raise ValueError("fair runtime did not retain post-load GPU residency evidence")
    delta = postload - baseline
    model_mib = model_path.stat().st_size / (1024 * 1024) if model_path is not None else None
    expected_delta = (
        max(256, int(model_mib * float(cfg["execution"]["min_model_vram_residency_ratio"])))
        if model_mib is not None
        else None
    )
    return {
        **offload_evidence,
        "baseline_mib": baseline,
        "postload_mib": postload,
        "delta_mib": delta,
        "expected_model_delta_mib": expected_delta,
        "model_residency_supporting_evidence": expected_delta is not None and delta >= expected_delta,
    }


def parse_suites(raw: str) -> set[str]:
    suites = {item.strip() for item in raw.split(",") if item.strip()}
    allowed = {"performance", "tool_contract", "sandbox", "concurrency", "vision", "production"}
    if not suites:
        raise ValueError("at least one suite is required")
    if not suites <= allowed:
        raise ValueError(f"unknown suites: {sorted(suites - allowed)}")
    if "production" in suites and suites != {"production"}:
        raise ValueError("production must run as an isolated suite")
    return suites


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile-class", choices=("fair", "production"), required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--server-bin", type=Path)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--quality-repeats", type=int)
    parser.add_argument("--include-holdout", action="store_true")
    parser.add_argument("--release-run", action="store_true")
    parser.add_argument("--suites", default="performance,tool_contract,sandbox,concurrency,vision")
    parser.add_argument("--order-seed", type=int, required=True)
    parser.add_argument("--candidate-order-index", type=int, required=True)
    parser.add_argument("--candidate-count", type=int, required=True)
    parser.add_argument("--candidate-order", required=True)
    parser.add_argument("--launch-argv", required=True)
    parser.add_argument("--launch-cache-prompt", required=True)
    parser.add_argument("--launch-cache-ram", required=True)
    parser.add_argument("--launch-cache-reuse", required=True)
    parser.add_argument("--launch-slot-similarity", required=True)
    parser.add_argument("--server-props", required=True)
    parser.add_argument("--server-slots", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--cooldown-seconds", type=int, required=True)
    parser.add_argument("--stabilization", required=True)
    parser.add_argument("--server-log-path", type=Path, required=True)
    parser.add_argument("--preflight-error")
    parser.add_argument("--production-driver")
    parser.add_argument("--production-harness")
    parser.add_argument("--production-tasks")
    return parser.parse_args()


def _json_evidence(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def preflight_evidence(args: argparse.Namespace) -> dict[str, Any]:
    startup_log = ""
    if args.server_log_path.exists():
        startup_log = args.server_log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "profile": {"class": args.profile_class, "id": args.profile_id},
        "base_url": args.base_url,
        "server_props": _json_evidence(args.server_props),
        "server_slots": _json_evidence(args.server_slots),
        "stabilization": _json_evidence(args.stabilization),
        "launch_argv": _json_evidence(args.launch_argv),
        "startup_log_path": str(args.server_log_path),
        "startup_log": startup_log,
        "launcher_error": args.preflight_error,
    }


def write_preflight_failure(out_dir: Path, trials_dir: Path, args: argparse.Namespace, exc: Exception) -> None:
    evidence = preflight_evidence(args)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "invalid",
        "model": args.model,
        "profile": evidence["profile"],
        "preflight": evidence,
    }
    failure = {
        "status": "error",
        "phase": "preflight",
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "evidence": evidence,
    }
    write_json(out_dir / "manifest.json", manifest)
    write_json(trials_dir / "preflight-failure.json", failure)
    write_json(
        out_dir / "run.json",
        {"schema_version": SCHEMA_VERSION, "status": "invalid", "manifest": manifest, "suites": {}, "failures": [failure]},
    )


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    trials_dir = out_dir / "trials"
    trials_dir.mkdir(parents=True, exist_ok=False)
    if args.preflight_error:
        write_preflight_failure(out_dir, trials_dir, args, RuntimeError(args.preflight_error))
        return 2
    try:
        cfg = load_config()
        suites = parse_suites(args.suites)
        if args.profile_class == "fair" and args.profile_id != cfg["fair_profile"]["id"]:
            raise ValueError("fair runs must use the configured fair profile id")
        props = json.loads(args.server_props)
        slots = json.loads(args.server_slots)
        if not isinstance(slots, list):
            raise ValueError("server slots response must be a list")
        startup_log = args.server_log_path.read_text(encoding="utf-8", errors="replace") if args.server_log_path.exists() else ""
        stabilization = json.loads(args.stabilization)
        offload: dict[str, Any] | None = None
        if args.profile_class == "fair":
            offload = validate_fair_runtime(
                cfg,
                props,
                slots,
                startup_log,
                stabilization=stabilization,
                launch_argv=json.loads(args.launch_argv),
                model_path=args.model_path,
            )
        repeats = args.repeats or int(cfg["execution"]["repeats"])
        if repeats < 1:
            raise ValueError("repeats must be positive")
        quality_repeats = args.quality_repeats or int(cfg["execution"]["quality_repeats"])
        if quality_repeats < 1:
            raise ValueError("quality repeats must be positive")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "model": args.model,
            "base_url": args.base_url,
            "profile": {"class": args.profile_class, "id": args.profile_id},
            "execution_order": {"seed": args.order_seed, "candidate_index": args.candidate_order_index, "candidate_count": args.candidate_count, "candidate_order": json.loads(args.candidate_order)},
            "schedule": {"kind": args.schedule, "cooldown_seconds": args.cooldown_seconds, "stabilization": stabilization},
            "launch": {"argv": json.loads(args.launch_argv), "cache_prompt": args.launch_cache_prompt.lower() in {"1", "true", "yes", "on"}, "cache_ram_mib": int(args.launch_cache_ram), "cache_reuse": int(args.launch_cache_reuse), "slot_prompt_similarity": float(args.launch_slot_similarity)},
            "evaluation": {
                "performance_repeats": repeats,
                "quality_repeats": quality_repeats,
                "include_holdout": args.include_holdout,
                "release_run": args.release_run,
            },
            "server_runtime": {"props": props, "slots": slots, "offload": offload},
            "config_digest": stable_digest(cfg),
            "workload_digest": stable_digest(
                {
                    "performance": PERFORMANCE_WORKLOADS,
                    "concurrency": CONCURRENCY_WORKLOADS,
                    "vision": VISION_WORKLOAD,
                    "tools": TOOL_CONTRACTS,
                    "tasks": TASKS,
                }
            ),
            "environment": environment_metadata(args.server_bin, args.model_path),
        }
        production_tasks: list[dict[str, Any]] = []
        production_harness: dict[str, Any] | None = None
        if "production" in suites:
            configured_production_tasks = json.loads(args.production_tasks or "")
            if not isinstance(configured_production_tasks, list) or not all(isinstance(task, dict) for task in configured_production_tasks):
                raise ValueError("production tasks must be a JSON list")
            production_tasks = selected_production_tasks(configured_production_tasks, args.include_holdout)
            if not production_tasks:
                raise ValueError("production task selection is empty")
            production_harness = json.loads(args.production_harness or "")
            manifest["production_contract"] = {
                "harness": production_harness,
                "configured_task_count": len(configured_production_tasks),
                "task_count": len(production_tasks),
                "task_ids": [task.get("id") for task in production_tasks],
                "tasks_digest": stable_digest(production_tasks),
                "driver_command_digest": stable_digest(args.production_driver),
            }
    except Exception as exc:  # noqa: BLE001
        write_preflight_failure(out_dir, trials_dir, args, exc)
        return 2
    write_json(out_dir / "manifest.json", manifest)
    run: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "manifest": manifest, "suites": {}}
    failures: list[dict[str, str]] = []
    timeout = float(cfg["execution"]["request_timeout_seconds"])
    with httpx.Client() as client:
        def execute_suite(name: str, action: Any) -> None:
            try:
                result = action()
                error_count = int(result.pop("error_count", 0))
                if error_count:
                    run["suites"][name] = {"status": "completed_with_errors", **result}
                    failures.append({"suite": name, "error_type": "WorkloadError", "error_message": f"{error_count} workload(s) failed"})
                else:
                    run["suites"][name] = {"status": "ok", **result}
            except Exception as exc:  # noqa: BLE001
                failure = {"status": "error", "error_type": type(exc).__name__, "error_message": str(exc)}
                run["suites"][name] = failure
                write_json(trials_dir / f"{name}-failure.json", failure)
                failures.append({"suite": name, **failure})

        if "performance" in suites:
            def performance() -> dict[str, Any]:
                rows = run_performance(client, args.base_url, args.model, repeats, timeout, args.order_seed)
                for row in rows:
                    write_json(trials_dir / f"performance-{row['workload']}-{row['trial']}.json", row)
                return {"trials": rows, "summary": aggregate_trials(rows), "error_count": sum(row.get("status") == "error" for row in rows)}

            execute_suite("performance", performance)
        if "tool_contract" in suites:
            def tool_contract() -> dict[str, Any]:
                rows: list[dict[str, Any]] = []
                for contract in selected_items(TOOL_CONTRACTS, args.include_holdout):
                    for trial in range(1, quality_repeats + 1):
                        try:
                            rows.extend(run_tool_contracts(client, args.base_url, args.model, timeout, [contract], trial=trial))
                        except Exception as exc:  # noqa: BLE001
                            rows.append(
                                {
                                    "contract": contract["id"],
                                    "split": contract.get("split", "core"),
                                    "trial": trial,
                                    "status": "error",
                                    "error_type": type(exc).__name__,
                                    "error_message": str(exc),
                                    "messages": contract["messages"],
                                }
                            )
                for row in rows:
                    write_json(trials_dir / f"tool-{row['contract']}-{row['trial']}.json", row)
                return {
                    "contracts": rows,
                    "passed": sum(bool(row.get("passed")) for row in rows),
                    "total": len(rows),
                    "splits": split_summary(rows),
                    "reliability": grouped_binary_summary(rows, "contract"),
                    "error_count": sum(row.get("status") == "error" for row in rows),
                }

            execute_suite("tool_contract", tool_contract)
        if "sandbox" in suites:
            def sandbox() -> dict[str, Any]:
                rows: list[dict[str, Any]] = []
                for task in selected_tasks(args.include_holdout):
                    for trial in range(1, quality_repeats + 1):
                        try:
                            rows.append(
                                run_task(
                                    client,
                                    args.base_url,
                                    args.model,
                                    task,
                                    int(cfg["execution"]["sandbox_max_turns"]),
                                    timeout,
                                    trial=trial,
                                    max_tokens=int(cfg["execution"]["sandbox_max_tokens"]),
                                )
                            )
                        except Exception as exc:  # noqa: BLE001
                            rows.append(
                                {
                                    "task": task["id"],
                                    "split": task.get("split", "core"),
                                    "trial": trial,
                                    "status": "error",
                                    "error_type": type(exc).__name__,
                                    "error_message": str(exc),
                                }
                            )
                for row in rows:
                    write_json(trials_dir / f"sandbox-{row['task']}-{row['trial']}.json", row)
                return {
                    "tasks": rows,
                    "passed": sum(bool(row.get("passed")) for row in rows),
                    "total": len(rows),
                    "splits": split_summary(rows),
                    "reliability": grouped_binary_summary(rows, "task"),
                    "error_count": sum(row.get("status") == "error" for row in rows),
                }

            execute_suite("sandbox", sandbox)
        if "concurrency" in suites:
            def concurrency() -> dict[str, Any]:
                rows = run_concurrency(client, args.base_url, args.model, repeats, timeout)
                for row in rows:
                    write_json(trials_dir / f"concurrency-{row['workload']}-{row['trial']}.json", row)
                return {
                    "trials": rows,
                    **binary_summary(rows),
                    "reliability": grouped_binary_summary(rows, "workload"),
                    "error_count": sum(row.get("status") == "error" for row in rows),
                }

            execute_suite("concurrency", concurrency)
        if "vision" in suites:
            def vision() -> dict[str, Any]:
                result = run_vision(client, args.base_url, args.model, quality_repeats, timeout, props)
                for row in result["trials"]:
                    write_json(trials_dir / f"vision-quadrants-{row['trial']}.json", row)
                result["error_count"] = sum(row.get("status") == "error" for row in result["trials"])
                return result

            execute_suite("vision", vision)
        if "production" in suites:
            def production() -> dict[str, Any]:
                if args.profile_class != "production" or not args.production_driver or not args.production_harness or args.production_tasks is None:
                    raise ValueError("production suite requires a production profile, driver, harness, and tasks")
                rows: list[dict[str, Any]] = []
                driver_metadata: dict[str, Any] | None = None
                for trial in range(1, quality_repeats + 1):
                    production_request = {
                        "schema_version": SCHEMA_VERSION,
                        "profile": manifest["profile"],
                        "harness": production_harness,
                        "candidate": {"model": args.model, "model_path": str(args.model_path) if args.model_path else None},
                        "tasks": production_tasks,
                        "launch": manifest["launch"],
                    }
                    payload = run_driver(args.production_driver, production_request, timeout=int(timeout))
                    if isinstance(payload.get("driver_metadata"), dict):
                        driver_metadata = payload["driver_metadata"]
                    task_splits = {str(task["id"]): str(task.get("split", "core")) for task in production_tasks}
                    for result in payload["results"]:
                        row = {**result, "trial": trial, "split": task_splits[result["task_id"]]}
                        rows.append(row)
                        write_json(trials_dir / f"production-{result['task_id']}-{trial}.json", row)
                return {
                    "harness": production_harness,
                    "driver_metadata": driver_metadata,
                    "results": rows,
                    "passed": sum(bool(row["passed"]) for row in rows),
                    "total": len(rows),
                    "splits": split_summary(rows),
                    "reliability": grouped_binary_summary(rows, "task_id"),
                }

            execute_suite("production", production)
    validate_run(run, suites)
    release_gate = build_release_gate(run, manifest, cfg, args.release_run)
    run["release_gate"] = release_gate
    if args.release_run and not release_gate["passed"]:
        failures.append(
            {
                "suite": "release_gate",
                "status": "error",
                "error_type": "ReleaseGateFailure",
                "error_message": "one or more release requirements failed",
            }
        )
    run["status"] = "completed_with_errors" if failures else "completed"
    run["failures"] = failures
    write_json(out_dir / "run.json", run)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
