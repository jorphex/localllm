from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = 1


def stable_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replay_fixture_metadata(fixture: dict) -> dict:
    turns = fixture.get("turns", [])
    return {
        "schema_version": SCHEMA_VERSION,
        "fixture_name": fixture["name"],
        "fixture_digest": stable_digest(fixture),
        "turn_count": len(turns),
        "expected_tool_call_turns": sum(
            1 for turn in turns if turn.get("expect", {}).get("finish_reason") == "tool_calls"
        ),
        "expected_stop_turns": sum(
            1 for turn in turns if turn.get("expect", {}).get("finish_reason") == "stop"
        ),
    }


def replay_run_summary(results_dir: Path, requested_candidates: list[str], fixtures: list[str]) -> dict:
    candidate_summaries = []
    for candidate in requested_candidates:
        fixture_summaries = []
        matched_turns = 0
        total_turns = 0
        passed_fixtures = 0
        for fixture in fixtures:
            result_path = results_dir / candidate / fixture / "result.json"
            if not result_path.exists():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            total_turns += len(result.get("turns", []))
            matched_turns += sum(
                1
                for turn in result.get("turns", [])
                if turn.get("matches_expectations")
            )
            all_expectations_met = result.get("all_expectations_met", False)
            if all_expectations_met:
                passed_fixtures += 1
            fixture_summaries.append(
                {
                    "fixture": fixture,
                    "all_expectations_met": all_expectations_met,
                    "matched_turns": sum(
                        1
                        for turn in result.get("turns", [])
                        if turn.get("matches_expectations")
                    ),
                    "turn_count": len(result.get("turns", [])),
                    "total_elapsed_seconds": sum(
                        float(turn.get("elapsed_seconds", 0.0)) for turn in result.get("turns", [])
                    ),
                }
            )
        candidate_summaries.append(
            {
                "candidate": candidate,
                "fixtures": fixture_summaries,
                "passed_fixtures": passed_fixtures,
                "fixture_count": len(fixture_summaries),
                "matched_turns": matched_turns,
                "turn_count": total_turns,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "family": "general_agentic",
        "suite": "transcript_replay",
        "results_dir": str(results_dir),
        "candidates": candidate_summaries,
    }


def sim_run_summary(results_dir: Path, requested_candidates: list[str], scenarios: list[str]) -> dict:
    candidate_summaries = []
    for candidate in requested_candidates:
        scenario_summaries = []
        pass_count = 0
        scope_clean_count = 0
        tool_error_free_count = 0
        for scenario in scenarios:
            summary_path = results_dir / candidate / scenario / "summary.json"
            if not summary_path.exists():
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            scorecard = summary.get("scorecard", {})
            if scorecard.get("pass"):
                pass_count += 1
            if scorecard.get("scope_clean"):
                scope_clean_count += 1
            if scorecard.get("tool_error_free"):
                tool_error_free_count += 1
            scenario_summaries.append(
                {
                    "scenario": scenario,
                    "scenario_family": summary.get("scenario_family"),
                    "pass": bool(scorecard.get("pass")),
                    "scope_clean": bool(scorecard.get("scope_clean")),
                    "tool_error_free": bool(scorecard.get("tool_error_free")),
                    "turns": summary.get("turns", 0),
                    "total_elapsed_seconds": float(summary.get("total_elapsed_seconds", 0.0)),
                }
            )
        candidate_summaries.append(
            {
                "candidate": candidate,
                "scenarios": scenario_summaries,
                "scenario_count": len(scenario_summaries),
                "pass_count": pass_count,
                "scope_clean_count": scope_clean_count,
                "tool_error_free_count": tool_error_free_count,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "family": "coding_agentic",
        "suite": "sim_compare",
        "results_dir": str(results_dir),
        "candidates": candidate_summaries,
    }
