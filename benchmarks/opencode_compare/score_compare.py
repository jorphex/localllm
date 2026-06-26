#!/usr/bin/env python3
"""Score opencode_compare outputs and emit summary.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    return parser.parse_args()


def load_response(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def content(response: dict) -> str:
    return response.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


def tool_names(response: dict) -> list[str]:
    tcs = response.get("choices", [{}])[0].get("message", {}).get("tool_calls", []) or []
    return [tc.get("function", {}).get("name", "") for tc in tcs]


def has_terms(text: str, terms: list[str]) -> bool:
    pattern = "|".join(re.escape(term) for term in terms)
    return bool(re.search(pattern, text, re.IGNORECASE))


def bullet_count(text: str) -> int:
    return len(re.findall(r"^\s*[-*•\d+][.)]?\s+", text, re.MULTILINE))


def score_repo_triage(out_dir: Path) -> dict:
    path = out_dir / "repo_triage_turn1.response.json"
    if not path.exists():
        return {"turn1": {"score": 0.0, "missing": "file"}}
    response = load_response(path)
    text = content(response)
    names = tool_names(response)
    checks = {
        "direct": not names,
        "evidence": has_terms(text, ["evidence", "traceback", "log", "logs", "failure", "failing test"]),
        "scope": has_terms(text, ["scope", "scoped", "minimal", "narrow", "out of scope"]),
        "validation": has_terms(text, ["test", "pytest", "validate", "verification", "check"]),
        "stop": has_terms(text, ["stop", "done", "ship", "exit criteria"]),
    }
    return {"turn1": {"score": round(sum(checks.values()) / len(checks), 4), **checks, "bullets": bullet_count(text)}}


def score_revise_after_feedback(out_dir: Path) -> dict:
    scores: dict[str, dict[str, float]] = {}
    for label in ("turn1", "turn2"):
        path = out_dir / f"revise_after_feedback_{label}.response.json"
        if not path.exists():
            scores[label] = {"score": 0.0, "missing": "file"}
            continue
        text = content(load_response(path))
        checks = {
            "scope": has_terms(text, ["scope", "scoped", "minimal", "narrow", "boundary"]),
            "evidence": has_terms(text, ["evidence", "traceback", "log", "logs", "failure", "failing test"]),
            "validation": has_terms(text, ["test", "pytest", "validate", "verification", "check"]),
            "feedback": has_terms(text, ["feedback", "review", "revise"]),
        }
        scores[label] = {"score": round(sum(checks.values()) / len(checks), 4), **checks, "bullets": bullet_count(text)}
    return scores


def score_tool_followthrough(out_dir: Path) -> dict:
    scores: dict[str, dict[str, float]] = {}
    for label in ("turn1", "turn2"):
        path = out_dir / f"tool_followthrough_{label}.response.json"
        if not path.exists():
            scores[label] = {"score": 0.0, "missing": "file"}
            continue
        response = load_response(path)
        names = tool_names(response)
        text = content(response)
        if label == "turn1":
            scores[label] = {
                "score": 1.0 if "read_file" in names else 0.0,
                "read_first": "read_file" in names,
                "tool_calls": names,
            }
        else:
            scores[label] = {
                "score": 1.0 if ("apply_patch" in names or has_terms(text, ["patch", "change", "fix"])) else 0.0,
                "tool_calls": names,
            }
    return scores


SCORERS = {
    "repo_triage": score_repo_triage,
    "revise_after_feedback": score_revise_after_feedback,
    "tool_followthrough": score_tool_followthrough,
}


def main() -> None:
    args = parse_args()
    results_dir = args.results_dir.resolve()

    scenario_scores: dict[str, dict[str, dict[str, float]]] = {}
    for scenario, scorer in SCORERS.items():
        scenario_scores[scenario] = scorer(results_dir)

    all_scores: list[float] = []
    for turns in scenario_scores.values():
        for turn in turns.values():
            if "score" in turn:
                all_scores.append(float(turn["score"]))

    summary = {
        "schema_version": 1,
        "suite": "opencode_compare",
        "family": "coding_agentic",
        "results_dir": str(results_dir),
        "scenarios": scenario_scores,
        "scenario_count": len(scenario_scores),
        "average_score": round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0,
    }

    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
