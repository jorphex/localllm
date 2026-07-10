from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.barrage_v2 import SCHEMA_VERSION
from benchmarks.barrage_v2.artifacts import stable_digest, write_json


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUMMARIES_DIR = ROOT / "benchmarks" / "summaries" / "barrage_v2"


def candidate_summary(run: dict[str, Any]) -> dict[str, Any]:
    manifest = run.get("manifest", {})
    suites = run.get("suites", {})
    summary: dict[str, Any] = {
        "model": manifest.get("model"),
        "status": run.get("status"),
        "profile": manifest.get("profile"),
        "evaluation": manifest.get("evaluation"),
        "environment": manifest.get("environment"),
        "failures": run.get("failures", []),
    }
    for name in ("performance", "tool_contract", "sandbox", "production"):
        suite = suites.get(name)
        if not suite:
            continue
        if name == "performance":
            performance = json.loads(json.dumps(suite.get("summary", {})))
            for workload in ("cold_pp_short", "cold_pp_long", "warm_append"):
                performance.get(workload, {}).pop("predicted_per_second", None)
            summary[name] = {"status": suite.get("status"), "summary": performance}
        elif name == "production":
            summary[name] = {
                "status": suite.get("status", "ok"),
                "harness": suite.get("harness"),
                "result_count": len(suite.get("results", [])),
            }
        else:
            summary[name] = {
                "status": suite.get("status"),
                "passed": suite.get("passed"),
                "total": suite.get("total"),
                "splits": suite.get("splits"),
            }
    return summary


def publish(results_dir: Path, label: str, out_dir: Path) -> dict[str, Any]:
    runs = sorted(results_dir.glob("*/run.json"))
    if not runs:
        raise ValueError(f"no V2 run.json files under {results_dir}")
    candidates = []
    for run_path in runs:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"incompatible schema: {run_path}")
        candidates.append(candidate_summary(run))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "label": label,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    payload["digest"] = stable_digest(payload)
    destination = out_dir / label
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "summary.json", payload)
    return {"source": str(results_dir), "destination": str(destination), "summary": payload}


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish compact, commit-ready Benchmark Barrage V2 summaries.")
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("label")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_SUMMARIES_DIR)
    args = parser.parse_args()
    print(json.dumps(publish(args.results_dir.resolve(), args.label, args.out_dir.resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
