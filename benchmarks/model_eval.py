from __future__ import annotations

import json
from pathlib import Path


def parse_candidate_specs(raw: str, *, base_port: int = 9711) -> list[dict]:
    candidates = []
    for index, item in enumerate(part for part in raw.split(";") if part.strip()):
        parts = item.split("|")
        if len(parts) not in {5, 6}:
            raise ValueError(
                "candidate spec must be alias|model|mmproj|context|extra_args[|port]"
            )
        alias, model, mmproj, context, extra_args = parts[:5]
        port = int(parts[5]) if len(parts) == 6 else base_port + index
        candidates.append(
            {
                "alias": alias,
                "model": model,
                "mmproj": mmproj,
                "context": int(context),
                "extra_args": extra_args,
                "port": port,
            }
        )
    if not candidates:
        raise ValueError("at least one candidate spec is required")
    return candidates


def candidate_spec_json(candidate: dict) -> str:
    return json.dumps(candidate, separators=(",", ":"))


def coding_compare_spec(candidate: dict) -> str:
    return (
        f"{candidate['alias']}|{candidate['model']}|{candidate['mmproj']}|"
        f"{candidate['context']}|{candidate['extra_args']}|0.2|0.95|20|0|1.05|{candidate['port']}"
    )


def build_model_eval_summary(results_dir: Path, candidates: list[dict], suites: list[str]) -> dict:
    candidate_summaries = []
    for candidate in candidates:
        suite_results = {}
        candidate_dir = results_dir / candidate["alias"]
        for suite in suites:
            suite_dir = candidate_dir / suite
            summary_path = suite_dir / "summary.json"
            manifest_path = suite_dir / "run_manifest.json"
            ndjson_path = suite_dir / "results.ndjson"
            entry: dict = {"suite": suite, "path": str(suite_dir)}
            if summary_path.exists():
                entry["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
            if manifest_path.exists():
                entry["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
            if ndjson_path.exists():
                lines = [line for line in ndjson_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                entry["result_count"] = len(lines)
            suite_results[suite] = entry
        candidate_summaries.append(
            {
                "candidate": candidate,
                "suites": suite_results,
            }
        )
    return {
        "results_dir": str(results_dir),
        "suites": suites,
        "candidates": candidate_summaries,
    }
