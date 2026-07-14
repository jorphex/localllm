from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.barrage_v2.runner import launch_argument_int, warm_cache_required_n


SCHEMA_VERSION = "runtime-tuning-campaign-v1.0"
MODEL_ORDER = ("qwen27-unsloth", "qwen27-huihui", "qwen35-unsloth", "qwen35-huihui")
EXPECTED_BARRAGE_PROFILES = {
    "qwen27-unsloth": "tuning-v1-q27-unsloth-n4",
    "qwen27-huihui": "tuning-v1-q27-huihui-n4",
    "qwen35-unsloth": "tuning-v1-q35-unsloth-nospec",
    "qwen35-huihui": "tuning-v1-q35-huihui-n3",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def direct_models(summary: dict[str, Any]) -> list[dict[str, Any]]:
    models = []
    for model_id in MODEL_ORDER:
        matches = [
            row
            for row in summary["candidate_summaries"]
            if row.get("phase") == "validation" and row.get("candidate", {}).get("model_id") == model_id
        ]
        if len(matches) != 1:
            raise ValueError(f"expected one validation profile for {model_id}, found {len(matches)}")
        row = matches[0]
        candidate = row["candidate"]
        workloads = row["workloads"]
        models.append(
            {
                "model_id": model_id,
                "profile": {
                    key: candidate[key]
                    for key in (
                        "model",
                        "mmproj",
                        "context",
                        "batch",
                        "ubatch",
                        "threads",
                        "threads_batch",
                        "checkpoints",
                        "spec_type",
                        "mtp_n",
                    )
                },
                "metrics": {
                    name: {
                        "trials": value["trials"],
                        "passed": value["passed"],
                        "prompt_per_second": value.get("prompt_per_second"),
                        "predicted_per_second": value.get("predicted_per_second"),
                        "cache_n": value.get("cache_n"),
                        "speculation_acceptance": value.get("speculation", {}).get("acceptance"),
                    }
                    for name, value in workloads.items()
                },
            }
        )
    return models


def barrage_summary(path: Path, model_id: str) -> dict[str, Any]:
    run = load_json(path)
    performance = run["suites"]["performance"]["trials"]
    workloads = sorted({str(row["workload"]) for row in performance})
    raw_passed = sum(bool(row.get("passed")) for row in performance)
    tool_suite = run["suites"]["tool_contract"]
    vision_suite = run["suites"]["vision"]
    if (
        run.get("status") != "completed"
        or run.get("manifest", {}).get("profile", {}).get("id") != EXPECTED_BARRAGE_PROFILES[model_id]
        or len(performance) != 50
        or tool_suite.get("passed") != tool_suite.get("total")
        or tool_suite.get("total") != 15
        or vision_suite.get("passed") != vision_suite.get("total")
        or vision_suite.get("total") != 3
    ):
        raise ValueError(f"Barrage evidence is incomplete or profile-mismatched for {model_id}")
    result: dict[str, Any] = {
        "model_id": model_id,
        "status": run["status"],
        "performance": {"raw_passed": raw_passed, "total": len(performance), "workloads": workloads},
        "tool_contract": {
            "passed": tool_suite["passed"],
            "total": tool_suite["total"],
        },
        "vision": {
            "passed": vision_suite["passed"],
            "total": vision_suite["total"],
        },
    }
    if model_id == "qwen35-unsloth":
        warm = [row for row in performance if row["workload"] == "warm_append_8k"]
        launch_argv = run["manifest"]["launch"]["argv"]
        ubatch = launch_argument_int(launch_argv, "-ub", "--ubatch")
        corrected = 0
        for row in warm:
            cache_n = int(row.get("cache_n") or 0)
            cache_ratio = float(row.get("cache_ratio") or 0)
            prime_prompt_n = round(cache_n / cache_ratio) if cache_ratio else 0
            corrected += cache_n >= warm_cache_required_n(prime_prompt_n, ubatch)
        non_warm = [row for row in performance if row["workload"] != "warm_append_8k"]
        if (
            len(warm) != 5
            or corrected != 5
            or raw_passed != 45
            or any(row.get("passed") for row in warm)
            or not all(row.get("passed") for row in non_warm)
        ):
            raise ValueError("35B Unsloth warm-cache correction no longer matches retained evidence")
        result["performance"]["derived_passed"] = raw_passed + corrected
        result["performance"]["grading_note"] = (
            "Five raw warm_append_8k failures used the superseded fixed 80% cache gate. "
            "All reused 5,978 of 8,030 prime tokens, within one ubatch plus template-boundary allowance; "
            "raw evidence is unchanged."
        )
    else:
        if raw_passed != 50:
            raise ValueError(f"Barrage performance is not 50/50 for {model_id}")
        result["performance"]["derived_passed"] = raw_passed
    return result


def _calculation_followthrough_failure(result: dict[str, Any]) -> bool:
    if result.get("task_id") == "concurrent_calculations_core":
        cases = result.get("cases", [])
        return bool(cases) and all(
            case.get("terminal_type") == "run_completed"
            and case.get("required_tool_found") is True
            and not str(case.get("answer_text") or "").strip()
            for case in cases
        )
    return (
        result.get("terminal_type") == "run_completed"
        and result.get("required_tool_found") is True
        and not str(result.get("answer_text") or "").strip()
    )


def openwendy_summary(path: Path) -> dict[str, Any]:
    run = load_json(path)
    manifest = load_json(path.parent / "manifest.json")
    safety_path = path.parent / "safety" / "completion.json"
    safety = load_json(safety_path)
    if safety != {
        "completed_at": safety["completed_at"],
        "completed_runs": 6,
        "restored": True,
        "safety_fault": False,
    }:
        raise ValueError("OpenWendy safety completion is not clean")
    nonempty_safety = [
        item.name
        for item in (path.parent / "safety").iterdir()
        if item.is_file() and item.name != "completion.json" and item.stat().st_size
    ]
    if nonempty_safety:
        raise ValueError(f"OpenWendy safety logs are nonempty: {nonempty_safety}")
    expected_failures = {"calculate_core", "calculate_holdout", "concurrent_calculations_core"}
    if (
        run.get("status") != "completed"
        or run.get("original_env_sha256") != run.get("restored_env_sha256")
        or [(row.get("arm"), row.get("repeat")) for row in run.get("runs", [])]
        != [("current", 1), ("finalist", 1), ("finalist", 2), ("current", 2), ("current", 3), ("finalist", 3)]
    ):
        raise ValueError("OpenWendy run order or byte restoration is invalid")
    arms = []
    for arm_name in ("current", "finalist"):
        rows = [row for row in run["runs"] if row["arm"] == arm_name]
        if len(rows) != 3:
            raise ValueError(f"expected three OpenWendy repeats for {arm_name}")
        failures = sorted({result["task_id"] for row in rows for result in row["results"] if not result["passed"]})
        if set(failures) != expected_failures:
            raise ValueError(f"OpenWendy failure set changed for {arm_name}")
        for row in rows:
            argv = row["launch_argv"]
            expected_shape = (10, 8, 2) if arm_name == "current" else (12, 12, 4)
            actual_shape = tuple(
                launch_argument_int(argv, *flags)
                for flags in (("-t", "--threads"), ("-tb", "--threads-batch"), ("--spec-draft-n-max",))
            )
            failed_results = [result for result in row["results"] if not result["passed"]]
            if actual_shape != expected_shape or not all(_calculation_followthrough_failure(result) for result in failed_results):
                raise ValueError(f"OpenWendy shape or failure semantics changed for {arm_name}")
        arms.append(
            {
                "arm": arm_name,
                "repeats": 3,
                "run_passed": sum(bool(row["passed"]) for row in rows),
                "task_passed": sum(bool(result["passed"]) for row in rows for result in row["results"]),
                "task_total": sum(len(row["results"]) for row in rows),
                "median_elapsed_seconds": round(statistics.median(row["elapsed_seconds"] for row in rows), 4),
                "failed_tasks": failures,
            }
        )
    current = next(arm for arm in arms if arm["arm"] == "current")
    finalist = next(arm for arm in arms if arm["arm"] == "finalist")
    return {
        "harness": manifest["harness"],
        "arms": arms,
        "common_finding": (
            "Both arms made every expected calculation tool call with correct arguments and output, "
            "but OpenWendy completed those tasks with an empty final answer."
        ),
        "finalist_elapsed_change_percent": round(
            (finalist["median_elapsed_seconds"] / current["median_elapsed_seconds"] - 1) * 100,
            1,
        ),
        "decision": {
            "selected_arm": "current",
            "selected_shape": "n2/t10/tb8",
            "reason": "No behavior improvement and slower median end-to-end execution for the finalist.",
        },
        "safety": safety,
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Qwen3.6 Runtime Tuning V1",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Direct Validation",
        "",
        f"- Primary tuning: {summary['direct']['passed']}/{summary['direct']['trials']} attempted trials produced valid measurements.",
        f"- Controls: {summary['controls']['passed']}/{summary['controls']['trials']} measured trials.",
        "- The three primary failures are expected unsupported-MTP startups for 35B Unsloth.",
        "",
        "| Model | Context | Shape | Long PP | Deterministic TG | Sampled TG | Tool TG |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for model in summary["models"]:
        profile = model["profile"]
        metrics = model["metrics"]
        shape = (
            f"b{profile['batch']}/u{profile['ubatch']}, t{profile['threads']}/tb{profile['threads_batch']}, "
            f"{profile['spec_type']} n{profile['mtp_n']}"
        )
        lines.append(
            f"| `{model['model_id']}` | {profile['context']} | {shape} | "
            f"{metrics['cold_pp_long']['prompt_per_second']:.2f} | "
            f"{metrics['deterministic_tg']['predicted_per_second']:.2f} | "
            f"{metrics['sampled_agent_tg']['predicted_per_second']:.2f} | "
            f"{metrics['structured_tool_tg']['predicted_per_second']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Barrage",
            "",
            "| Model | Performance | Tool | Vision |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in summary["barrage"]:
        perf = row["performance"]
        lines.append(
            f"| `{row['model_id']}` | {perf['derived_passed']}/{perf['total']} | "
            f"{row['tool_contract']['passed']}/{row['tool_contract']['total']} | "
            f"{row['vision']['passed']}/{row['vision']['total']} |"
        )
    lines.extend(
        [
            "",
            "35B Unsloth is shown with the corrected ubatch-aware warm-cache interpretation; its five raw failures are retained and documented in JSON.",
            "",
            "## OpenWendy Attribution",
            "",
            "| Arm | Task pass | Median elapsed |",
            "| --- | ---: | ---: |",
        ]
    )
    for arm in summary["openwendy"]["arms"]:
        lines.append(f"| `{arm['arm']}` | {arm['task_passed']}/{arm['task_total']} | {arm['median_elapsed_seconds']:.2f}s |")
    lines.extend(
        [
            "",
            f"Decision: retain `{summary['openwendy']['decision']['selected_shape']}`. "
            f"The finalist was {summary['openwendy']['finalist_elapsed_change_percent']:.1f}% slower by median and did not improve task outcomes.",
            "",
            f"Common harness finding: {summary['openwendy']['common_finding']}",
            "",
            "## Safety And Scope",
            "",
            "- Post-lock runs used pinned AMDGPU runtime PM, a root sleep inhibitor, continuous kernel monitoring, and 30-second unload/load stabilization.",
            "- All guarded completion and kernel artifacts are clean, and the production env was restored byte-for-byte.",
            "- Wrong-filename and lock-interrupted 35B directories are explicitly excluded.",
            "- Raw prompts, responses, transcripts, and generated media are not published here.",
            "",
        ]
    )
    return "\n".join(lines)


def publish(
    direct_path: Path,
    controls_path: Path,
    barrage_paths: dict[str, Path],
    openwendy_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    direct = load_json(direct_path)
    controls = load_json(controls_path)
    if direct.get("trial_count") != 539 or controls.get("trial_count") != 140:
        raise ValueError("direct/control trial counts do not match the completed campaign")
    direct_passed = sum(
        int(workload["passed"])
        for row in direct["candidate_summaries"]
        for workload in row["workloads"].values()
    )
    control_passed = sum(
        int(workload["passed"])
        for row in controls["candidate_summaries"]
        for workload in row["workloads"].values()
    )
    if direct_passed != 536 or control_passed != 140:
        raise ValueError("direct/control pass counts do not match retained evidence")
    if set(barrage_paths) != set(MODEL_ORDER):
        raise ValueError("one Barrage result is required for each model")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "label": output_dir.name,
        "direct": {"trials": 539, "passed": direct_passed, "expected_failures": 3},
        "controls": {"trials": 140, "passed": control_passed},
        "models": direct_models(direct),
        "barrage": [barrage_summary(barrage_paths[model_id], model_id) for model_id in MODEL_ORDER],
        "openwendy": openwendy_summary(openwendy_path),
        "excluded": [
            {"path": "tuning-v1-q35-unsloth-nospec-20260713", "reason": "wrong model filename; preflight only"},
            {"path": "tuning-v1-q35-unsloth-nospec-20260713-r2", "reason": "lock-interrupted startup only"},
        ],
        "sources": {
            "direct_sha256": digest(direct_path),
            "controls_sha256": digest(controls_path),
            "openwendy_sha256": digest(openwendy_path),
            "barrage_sha256": {model_id: digest(path) for model_id, path in barrage_paths.items()},
        },
    }
    if output_dir.exists():
        unexpected = {path.name for path in output_dir.iterdir()} - {"summary.json", "REPORT.md"}
        if unexpected:
            raise ValueError(f"refusing to replace output with unexpected files: {sorted(unexpected)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "REPORT.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish compact Runtime Tuning V1 campaign results")
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--openwendy", type=Path, required=True)
    parser.add_argument("--barrage", action="append", required=True, metavar="MODEL=RUN_JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    barrage_paths = {}
    for value in args.barrage:
        model_id, separator, raw_path = value.partition("=")
        if not separator or model_id in barrage_paths:
            raise ValueError(f"invalid Barrage mapping: {value}")
        barrage_paths[model_id] = Path(raw_path)
    summary = publish(args.direct, args.controls, barrage_paths, args.openwendy, args.output)
    print(json.dumps({"output": str(args.output), "decision": summary["openwendy"]["decision"]}, sort_keys=True))


if __name__ == "__main__":
    main()
