#!/usr/bin/env python3
"""Score agentic_barrage outputs and emit a summary.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    return parser.parse_args()


def load_response(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def message_content(response: dict) -> str:
    return response.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


def tool_calls(response: dict) -> list[dict]:
    return response.get("choices", [{}])[0].get("message", {}).get("tool_calls", []) or []


def tool_names(response: dict) -> list[str]:
    return [tc.get("function", {}).get("name", "") for tc in tool_calls(response)]


def has_terms(text: str, terms: list[str]) -> bool:
    pattern = "|".join(re.escape(term) for term in terms)
    return bool(re.search(pattern, text, re.IGNORECASE))


def bullet_count(text: str) -> int:
    return len(re.findall(r"^\s*[-*•\d+][.)]?\s+", text, re.MULTILINE))


def score_plan(content: str) -> dict[str, float]:
    checks = {
        "scope": has_terms(content, ["scope", "scoped", "minimal", "narrow", "boundary"]),
        "evidence": has_terms(content, ["evidence", "traceback", "log", "logs", "failure", "failing test", "regress"]),
        "validation": has_terms(content, ["test", "pytest", "validate", "verification", "check"]),
        "stop": has_terms(content, ["stop", "done", "ship", "exit criteria"]),
    }
    return {k: (1.0 if v else 0.0) for k, v in checks.items()}


def score_revise(content: str) -> dict[str, float]:
    checks = {
        "evidence": has_terms(content, ["evidence", "traceback", "log", "logs", "failure", "failing test"]),
        "narrow": has_terms(content, ["narrow", "smaller", "scoped", "scope", "minimal"]),
        "validation": has_terms(content, ["test", "pytest", "validate", "verification", "check"]),
        "stop": has_terms(content, ["stop", "done", "ship", "exit criteria"]),
    }
    return {k: (1.0 if v else 0.0) for k, v in checks.items()}


def score_evidence(content: str) -> dict[str, float]:
    checks = {
        "prioritizes": has_terms(content, ["matter", "most", "first", "primary", "key"]),
        "evidence": has_terms(content, ["evidence", "traceback", "log", "logs", "failure", "failing test"]),
        "scope": has_terms(content, ["scope", "scoped", "not change", "out of scope"]),
        "validation": has_terms(content, ["test", "pytest", "validate", "verification", "check"]),
    }
    return {k: (1.0 if v else 0.0) for k, v in checks.items()}


def avg(scores: dict[str, float]) -> float:
    if not scores:
        return 0.0
    return round(sum(scores.values()) / len(scores), 4)


def score_plan_then_revise(out_dir: Path) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label in ("turn1", "turn2"):
        path = next(out_dir.glob(f"plan_then_revise_*_{label}.json"), None)
        if path is None:
            scores[label] = {"score": 0.0, "missing": "file"}
            continue
        content = message_content(load_response(path))
        checks = score_plan(content)
        scores[label] = {"score": avg(checks), **checks, "bullets": bullet_count(content)}
    return scores


def score_review_then_retry(out_dir: Path) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label in ("turn1", "turn2"):
        path = next(out_dir.glob(f"review_then_retry_*_{label}.json"), None)
        if path is None:
            scores[label] = {"score": 0.0, "missing": "file"}
            continue
        content = message_content(load_response(path))
        checks = score_revise(content)
        scores[label] = {"score": avg(checks), **checks, "bullets": bullet_count(content)}
    return scores


def score_codex_workflow(out_dir: Path) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label in ("turn1", "turn2"):
        path = next(out_dir.glob(f"codex_workflow_*_{label}.json"), None)
        if path is None:
            scores[label] = {"score": 0.0, "missing": "file"}
            continue
        response = load_response(path)
        names = tool_names(response)
        content = message_content(response)
        if label == "turn1":
            scores[label] = {
                "score": 1.0 if "read_file" in names else 0.0,
                "read_first": "read_file" in names,
                "tool_calls": names,
            }
        else:
            checks = {
                "concrete": has_terms(content, ["change", "fix", "patch", "test", "retry"]),
                "stop": has_terms(content, ["stop", "done", "verify"]),
            }
            scores[label] = {"score": avg(checks), **checks, "tool_calls": names}
    return scores


def score_evidence_triage(out_dir: Path) -> dict[str, dict[str, float]]:
    path = next(out_dir.glob("evidence_triage_*_turn1.json"), None)
    if path is None:
        return {"turn1": {"score": 0.0, "missing": "file"}}
    content = message_content(load_response(path))
    checks = score_evidence(content)
    return {"turn1": {"score": avg(checks), **checks, "bullets": bullet_count(content)}}


def score_tool_restraint(out_dir: Path) -> dict[str, dict[str, float]]:
    path = next(out_dir.glob("tool_restraint_*_turn1.json"), None)
    if path is None:
        return {"turn1": {"score": 0.0, "missing": "file"}}
    names = tool_names(load_response(path))
    return {"turn1": {"score": 1.0 if not names else 0.0, "tool_calls": names}}


def score_tool_followthrough(out_dir: Path) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label in ("turn1", "turn2"):
        path = next(out_dir.glob(f"tool_followthrough_*_{label}.json"), None)
        if path is None:
            scores[label] = {"score": 0.0, "missing": "file"}
            continue
        response = load_response(path)
        names = tool_names(response)
        content = message_content(response)
        if label == "turn1":
            scores[label] = {
                "score": 1.0 if "add" in names else 0.0,
                "called_add": "add" in names,
                "tool_calls": names,
            }
        else:
            scores[label] = {
                "score": 1.0 if "4" in content and not names else 0.0,
                "answered_four": "4" in content,
                "tool_calls": names,
            }
    return scores


SCORERS = {
    "plan_then_revise": score_plan_then_revise,
    "review_then_retry": score_review_then_retry,
    "codex_workflow": score_codex_workflow,
    "evidence_triage": score_evidence_triage,
    "tool_restraint": score_tool_restraint,
    "tool_followthrough": score_tool_followthrough,
}


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir.resolve()

    scenario_scores: dict[str, dict[str, dict[str, float]]] = {}
    for scenario, scorer in SCORERS.items():
        scenario_scores[scenario] = scorer(out_dir)

    all_scores: list[float] = []
    for scenario, turns in scenario_scores.items():
        for turn in turns.values():
            if "score" in turn:
                all_scores.append(float(turn["score"]))

    summary = {
        "schema_version": 1,
        "suite": "agentic_barrage",
        "family": "general_agentic",
        "out_dir": str(out_dir),
        "scenarios": scenario_scores,
        "scenario_count": len(scenario_scores),
        "average_score": round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0,
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
