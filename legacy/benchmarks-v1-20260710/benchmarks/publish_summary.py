#!/usr/bin/env python3
"""Copy a benchmark run's summary and manifest into the committed summaries tree."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from benchmarks.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("suite", type=str)
    parser.add_argument("label", type=str)
    return parser.parse_args()


SUMMARIES_DIR = Path(load_config()["paths"]["summaries_dir"]).resolve()


def main() -> None:
    args = parse_args()
    results_dir = args.results_dir.resolve()
    suite = args.suite
    label = args.label

    dest_dir = SUMMARIES_DIR / suite / f"{label}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    manifest_src = results_dir / "run_manifest.json"
    if manifest_src.exists():
        shutil.copy2(manifest_src, dest_dir / "run_manifest.json")

    summary_candidates = [
        results_dir / "summary.json",
        results_dir / "candidate" / "summary.json",
    ]
    summary_src = next((p for p in summary_candidates if p.exists()), None)
    if summary_src:
        shutil.copy2(summary_src, dest_dir / "summary.json")
    else:
        # Diagnostic suites (coding_compare, agentic_barrage) may store summary at top-level.
        for candidate_summary in results_dir.glob("*/summary.json"):
            candidate_name = candidate_summary.parent.name
            candidate_dest = dest_dir / candidate_name
            candidate_dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate_summary, candidate_dest / "summary.json")

    published = {
        "suite": suite,
        "label": label,
        "source": str(results_dir),
        "destination": str(dest_dir),
    }
    (dest_dir / "published.json").write_text(json.dumps(published, indent=2), encoding="utf-8")
    print(json.dumps(published))


if __name__ == "__main__":
    main()