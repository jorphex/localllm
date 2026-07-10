from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx

from benchmarks.barrage_v2 import SCHEMA_VERSION
from benchmarks.barrage_v2.artifacts import aggregate_trials, environment_metadata, stable_digest, write_json
from benchmarks.barrage_v2.config import load_config
from benchmarks.barrage_v2.production_driver import run_driver
from benchmarks.barrage_v2.sandbox import TASKS, run_task, selected_tasks
from benchmarks.barrage_v2.workloads import PERFORMANCE_WORKLOADS, TOOL_CONTRACTS, agent_messages, release_tool, repeated_prompt, selected_items


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


def run_performance(client: httpx.Client, base_url: str, model: str, repeats: int, timeout: float, order_seed: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    workloads = [*PERFORMANCE_WORKLOADS, {"id": "warm_append", "kind": "warm"}]
    jobs = [(workload, trial) for workload in workloads for trial in range(1, repeats + 1)]
    random.Random(order_seed).shuffle(jobs)
    for execution_order, (workload, trial) in enumerate(jobs, start=1):
        payload: dict[str, Any] | None = None
        initial_response: dict[str, Any] | None = None
        phase = "request"
        try:
            if workload["kind"] == "warm":
                prefix = repeated_prompt(400)
                payload = chat_payload(model, prefix, 1, cache_prompt=True)
                payload["id_slot"] = 0
                phase = "prime"
                response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                response.raise_for_status()
                payload = chat_payload(model, prefix + "\nAppend-only turn: confirm cache reuse.", 1, cache_prompt=True)
                payload["id_slot"] = 0
                phase = "append"
                started = time.perf_counter()
                response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
                elapsed = time.perf_counter() - started
                response.raise_for_status()
                record = timing_record("warm_append", trial, payload, response.json(), elapsed, execution_order=execution_order)
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
                    "tool_choice": {"type": "function", "function": {"name": "release_lookup"}},
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
                if calls[0].get("function", {}).get("arguments") != '{"package":"barrage","channel":"stable"}':
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
                "phase": phase,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "request": payload,
            }
            if initial_response is not None:
                failure["initial_response"] = initial_response
            records.append(failure)
    return records


def _tool_names(response: dict[str, Any]) -> list[str]:
    return [call.get("function", {}).get("name", "") for call in response.get("choices", [{}])[0].get("message", {}).get("tool_calls", []) or []]


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
            payload = {"model": model, "messages": contract["messages"], "tools": [release_tool()], "tool_choice": "auto", "temperature": 0, "seed": 42, "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
            record["initial_request"] = payload
            response = client.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
            response.raise_for_status()
            first = response.json()
            record["initial_response"] = first
            names = _tool_names(first)
            record["tool_names"] = names
            record["tool_ok"] = names == ([contract["expect_tool"]] if contract["expect_tool"] else [])
            if contract["expect_tool"] is None:
                record["content_present"] = bool(first.get("choices", [{}])[0].get("message", {}).get("content", "").strip())
                record["passed"] = record["tool_ok"]
                records.append(record)
                continue
            calls = first["choices"][0]["message"].get("tool_calls") or []
            try:
                arguments = json.loads(calls[0]["function"]["arguments"])
            except (IndexError, KeyError, TypeError, json.JSONDecodeError):
                arguments = None
            record["arguments"] = arguments
            record["arguments_ok"] = arguments == contract["expect_args"]
            if not calls:
                record["final_ok"] = False
                record["passed"] = False
                records.append(record)
                continue
            followup = {
                "model": model,
                "messages": [*contract["messages"], first["choices"][0]["message"], {"role": "tool", "tool_call_id": calls[0]["id"], "content": contract["tool_result"]}],
                "tools": [release_tool()],
                "temperature": 0,
                "seed": 42,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            record["followup_request"] = followup
            response = client.post(f"{base_url}/v1/chat/completions", json=followup, timeout=timeout)
            response.raise_for_status()
            followup_response = response.json()
            record["followup_response"] = followup_response
            content = followup_response.get("choices", [{}])[0].get("message", {}).get("content", "").lower()
            record["final_ok"] = contract["expect_final"] in content
            record["passed"] = record["tool_ok"] and record["arguments_ok"] and record["final_ok"]
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            record["error_type"] = type(exc).__name__
            record["error_message"] = str(exc)
        records.append(record)
    return records


def validate_run(run: dict[str, Any], suites: set[str]) -> None:
    if run["schema_version"] != SCHEMA_VERSION:
        raise ValueError("schema version mismatch")
    for suite in suites:
        if not run["suites"].get(suite):
            raise ValueError(f"missing suite output: {suite}")


def split_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summaries: dict[str, dict[str, int]] = {}
    for row in rows:
        split = str(row.get("split", "core"))
        summary = summaries.setdefault(split, {"passed": 0, "total": 0, "errors": 0})
        summary["total"] += 1
        summary["passed"] += int(bool(row.get("passed")))
        summary["errors"] += int(row.get("status") == "error")
    return summaries


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
        return {"evidence": "startup_log", "offloaded_layers": offloaded, "total_layers": total}
    argv = launch_argv or []
    if "--gpu-layers" not in argv or "auto" not in argv:
        raise ValueError("fair runtime lacks --gpu-layers auto evidence")
    baseline = (stabilization or {}).get("gpu_mem", {}).get("used_mib")
    postload = (stabilization or {}).get("postload_gpu", {}).get("used_mib")
    if not isinstance(baseline, int) or not isinstance(postload, int) or model_path is None:
        raise ValueError("fair runtime did not retain post-load GPU residency evidence")
    model_mib = model_path.stat().st_size / (1024 * 1024)
    required_delta = max(256, int(model_mib * float(cfg["execution"]["min_model_vram_residency_ratio"])))
    delta = postload - baseline
    if delta < required_delta:
        raise ValueError(f"fair runtime GPU residency is too small: delta={delta} MiB, required={required_delta} MiB")
    return {"evidence": "auto_layers_vram_residency", "baseline_mib": baseline, "postload_mib": postload, "delta_mib": delta, "required_delta_mib": required_delta}


def parse_suites(raw: str) -> set[str]:
    suites = {item.strip() for item in raw.split(",") if item.strip()}
    allowed = {"performance", "tool_contract", "sandbox", "production"}
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
    parser.add_argument("--suites", default="performance,tool_contract,sandbox")
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
            "model": args.model,
            "base_url": args.base_url,
            "profile": {"class": args.profile_class, "id": args.profile_id},
            "execution_order": {"seed": args.order_seed, "candidate_index": args.candidate_order_index, "candidate_count": args.candidate_count, "candidate_order": json.loads(args.candidate_order)},
            "schedule": {"kind": args.schedule, "cooldown_seconds": args.cooldown_seconds, "stabilization": stabilization},
            "launch": {"argv": json.loads(args.launch_argv), "cache_prompt": args.launch_cache_prompt.lower() in {"1", "true", "yes", "on"}, "cache_ram_mib": int(args.launch_cache_ram), "cache_reuse": int(args.launch_cache_reuse), "slot_prompt_similarity": float(args.launch_slot_similarity)},
            "evaluation": {"performance_repeats": repeats, "quality_repeats": quality_repeats, "include_holdout": args.include_holdout},
            "server_runtime": {"props": props, "slots": slots, "offload": offload},
            "config_digest": stable_digest(cfg),
            "workload_digest": stable_digest({"performance": PERFORMANCE_WORKLOADS, "tools": TOOL_CONTRACTS, "tasks": TASKS}),
            "environment": environment_metadata(args.server_bin, args.model_path),
        }
        if "production" in suites:
            production_tasks = json.loads(args.production_tasks or "")
            if not isinstance(production_tasks, list):
                raise ValueError("production tasks must be a JSON list")
            manifest["production_contract"] = {
                "harness": json.loads(args.production_harness or ""),
                "task_count": len(production_tasks),
                "task_ids": [task.get("id") if isinstance(task, dict) else None for task in production_tasks],
                "tasks_digest": stable_digest(production_tasks),
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
                    "error_count": sum(row.get("status") == "error" for row in rows),
                }

            execute_suite("tool_contract", tool_contract)
        if "sandbox" in suites:
            def sandbox() -> dict[str, Any]:
                rows: list[dict[str, Any]] = []
                for task in selected_tasks(args.include_holdout):
                    for trial in range(1, quality_repeats + 1):
                        try:
                            rows.append(run_task(client, args.base_url, args.model, task, int(cfg["execution"]["sandbox_max_turns"]), timeout, trial=trial))
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
                    "error_count": sum(row.get("status") == "error" for row in rows),
                }

            execute_suite("sandbox", sandbox)
        if "production" in suites:
            def production() -> dict[str, Any]:
                if args.profile_class != "production" or not args.production_driver or not args.production_harness or args.production_tasks is None:
                    raise ValueError("production suite requires a production profile, driver, harness, and tasks")
                production_request = {
                    "schema_version": SCHEMA_VERSION,
                    "profile": manifest["profile"],
                    "harness": json.loads(args.production_harness),
                    "candidate": {"model": args.model, "model_path": str(args.model_path) if args.model_path else None},
                    "tasks": json.loads(args.production_tasks),
                    "launch": manifest["launch"],
                }
                payload = run_driver(args.production_driver, production_request, timeout=int(timeout))
                for result in payload["results"]:
                    write_json(trials_dir / f"production-{result['task_id']}.json", result)
                return payload

            execute_suite("production", production)
    validate_run(run, suites)
    run["status"] = "completed_with_errors" if failures else "completed"
    run["failures"] = failures
    write_json(out_dir / "run.json", run)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
