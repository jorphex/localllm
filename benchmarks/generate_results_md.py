#!/usr/bin/env python3
"""Regenerate BENCHMARK_RESULTS.md from committed benchmark summaries."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SUMMARIES_DIR = ROOT / "benchmarks" / "summaries"
OUTPUT = ROOT / "benchmarks" / "BENCHMARK_RESULTS.md"


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


RUN_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def run_sort_key(path: Path) -> tuple[str, str]:
    matches = RUN_TS_RE.findall(path.name)
    return (matches[-1] if matches else "", path.name)


def suite_summaries(suite_dir: Path) -> list[tuple[Path, dict]]:
    runs = []
    for run_dir in sorted(
        (p for p in suite_dir.iterdir() if p.is_dir() and (p / "summary.json").exists()),
        key=run_sort_key,
        reverse=True,
    ):
        data = load_json(run_dir / "summary.json")
        if data is not None:
            runs.append((run_dir, data))
    return runs


def render_transcript_replay(summary: dict) -> str:
    lines = ["| Candidate | Fixtures passed | Turn match | Partial score |",
             "| --- | --- | --- | --- |"]
    for cand in summary.get("candidates", []):
        lines.append(
            f"| {cand['candidate']} | {cand['passed_fixtures']}/{cand['fixture_count']} | "
            f"{cand['matched_turns']}/{cand['turn_count']} | {cand.get('partial_score_avg', 0.0)} |"
        )
    return "\n".join(lines)


def render_sim_compare(summary: dict) -> str:
    lines = ["| Candidate | Pass | Scope clean | Scope score | Tool clean | Agent score |",
             "| --- | --- | --- | --- | --- | --- |"]
    for cand in summary.get("candidates", []):
        lines.append(
            f"| {cand['candidate']} | {cand['pass_count']}/{cand['scenario_count']} | "
            f"{cand['scope_clean_count']}/{cand['scenario_count']} | "
            f"{cand.get('scope_score_avg', 0.0)} | "
            f"{cand['tool_error_free_count']}/{cand['scenario_count']} | "
            f"{cand.get('agent_score_avg', 0.0)} |"
        )
    return "\n".join(lines)


def render_scalar_score(summary: dict) -> str:
    avg = summary.get("average_score", 0.0)
    return f"Average score: **{avg}**"


def render_coding_compare(summary: dict) -> str:
    lines = ["| Candidate | Average score | Task scores |", "| --- | --- | --- |"]
    candidates = summary.get("candidates", {})
    for candidate, tasks in sorted(candidates.items()):
        scores = [
            float(result.get("uncapped", {}).get("score", 0.0))
            for result in tasks.values()
            if isinstance(result, dict)
        ]
        avg = round(sum(scores) / len(scores), 4) if scores else 0.0
        task_scores = ", ".join(
            f"{task}: {float(result.get('uncapped', {}).get('score', 0.0)):g}"
            for task, result in sorted(tasks.items())
            if isinstance(result, dict)
        )
        lines.append(f"| {candidate} | {avg} | {task_scores} |")
    return "\n".join(lines)


def render_opencode_compare(summary: dict) -> str:
    lines = ["| Candidate | Average score |", "| --- | --- |"]
    candidates = summary.get("candidates", [])
    for candidate in candidates:
        lines.append(f"| {candidate.get('candidate')} | {candidate.get('average_score', 0.0)} |")
    return "\n".join(lines)


def render_suite(suite: str, run_dir: Path, summary: dict) -> str:
    renderer = {
        "transcript_replay": render_transcript_replay,
        "sim_compare": render_sim_compare,
        "agentic_barrage": render_scalar_score,
        "opencode_compare": render_opencode_compare,
        "coding_compare": render_coding_compare,
    }.get(suite, render_scalar_score)

    return (
        f"## {suite}\n\n"
        f"Run: `{run_dir.name}`\n\n"
        f"{renderer(summary)}\n"
    )


MARKER = "<!-- BENCHMARK-AUTO-GENERATED -->"


def main() -> None:
    generated_sections = ["\n# Committed Summary Rollup\n"]

    if not SUMMARIES_DIR.exists():
        generated_sections.append("No committed summaries yet.\n")
    else:
        for suite_dir in sorted(SUMMARIES_DIR.iterdir()):
            if not suite_dir.is_dir():
                continue
            summaries = suite_summaries(suite_dir)
            if not summaries:
                continue
            for run_dir, summary in summaries:
                generated_sections.append(render_suite(suite_dir.name, run_dir, summary))

    generated_text = "\n".join(generated_sections) + "\n"

    existing = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
    if MARKER in existing:
        head = existing.split(MARKER, 1)[0]
        OUTPUT.write_text(head + MARKER + "\n" + generated_text, encoding="utf-8")
    else:
        OUTPUT.write_text(existing + "\n" + MARKER + "\n" + generated_text, encoding="utf-8")

    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
