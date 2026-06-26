#!/usr/bin/env python3
"""Score coding_compare outputs by executing generated code against hidden tests."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    return parser.parse_args()


def clean_code(text: str) -> str:
    text = re.sub(r"```python\n", "", text)
    text = re.sub(r"```\n?", "", text)
    return text.strip()


def run_test(name: str, candidate_code: str, test_code: str) -> dict:
    full_code = candidate_code + "\n\n" + test_code
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
        tmp.write(full_code)
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "passed": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "returncode": None, "stdout": "", "stderr": "timeout"}
    finally:
        tmp_path.unlink(missing_ok=True)


HIDDEN_TESTS = {
    "simple_edit": """
assert normalize_tags(["  Foo ", "", "BAR"]) == ["foo", "bar"]
assert normalize_tags([]) == []
assert normalize_tags(["a", "  ", "b"]) == ["a", "b"]
print("OK")
""",
    "retry_bug": """
import asyncio

class FakeResponse:
    pass

class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
    async def get(self, url, timeout=5):
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item

async def main():
    client = FakeClient([Exception("fail"), FakeResponse()])
    result = await fetch_with_retry(client, "http://x", retries=3, delay=0.01)
    assert isinstance(result, FakeResponse)
    client2 = FakeClient([Exception("fail")] * 3)
    try:
        await fetch_with_retry(client2, "http://x", retries=3, delay=0.01)
        raise AssertionError("expected final exception")
    except Exception:
        pass

asyncio.run(main())
print("OK")
""",
    "task_runner": """
import asyncio

async def main():
    runner = TaskRunner(max_concurrent=2)
    async def good():
        await asyncio.sleep(0.01)
        return "ok"
    async def bad():
        await asyncio.sleep(0.01)
        raise ValueError("boom")
    runner.submit("g", good())
    runner.submit("b", bad())
    await runner.drain()
    status = runner.status("g")
    assert status in ("completed", "success"), status
    print("OK")

asyncio.run(main())
""",
    "merge_intervals": """
assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
assert merge_intervals([[1,1]]) == [[1,1]]
assert merge_intervals([]) == []
print("OK")
""",
}


def required_symbol(prompt: str) -> str | None:
    return {
        "simple_edit": "normalize_tags",
        "retry_bug": "fetch_with_retry",
        "task_runner": "TaskRunner",
        "merge_intervals": "merge_intervals",
    }.get(prompt)


def score_prompt(out_dir: Path, alias: str, prompt: str, budget_label: str) -> dict:
    txt_path = out_dir / f"{alias}_{prompt}_{budget_label}.txt"
    if not txt_path.exists():
        return {"score": 0.0, "missing": "file"}
    raw = txt_path.read_text(encoding="utf-8")
    code = clean_code(raw)
    symbol = required_symbol(prompt)
    has_symbol = bool(symbol) and symbol in code
    test = HIDDEN_TESTS.get(prompt)
    if not test:
        return {"score": 0.0, "missing": "test"}
    result = run_test(prompt, code, test)
    return {
        "score": 1.0 if result["passed"] else 0.0,
        "syntax_ok": result["returncode"] is not None,
        "has_required_symbol": has_symbol,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"][:500],
    }


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir.resolve()

    # Discover aliases and prompts from file names.
    aliases: set[str] = set()
    prompt_budgets: dict[str, list[tuple[str, str]]] = {}
    for path in out_dir.glob("*.txt"):
        match = re.match(r"^([^_]+)_(simple_edit|retry_bug|task_runner|merge_intervals)_(.+?)\.txt$", path.name)
        if match:
            aliases.add(match.group(1))
            prompt_budgets.setdefault(match.group(2), []).append((match.group(1), match.group(3)))

    candidate_scores: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    all_scores: list[float] = []
    for alias in sorted(aliases):
        candidate_scores[alias] = {}
        for prompt, runs in prompt_budgets.items():
            candidate_scores[alias][prompt] = {}
            for run_alias, budget_label in runs:
                if run_alias != alias:
                    continue
                score = score_prompt(out_dir, alias, prompt, budget_label)
                candidate_scores[alias][prompt][budget_label] = score
                if "score" in score:
                    all_scores.append(float(score["score"]))

    summary = {
        "schema_version": 1,
        "suite": "coding_compare",
        "family": "coding_agentic",
        "out_dir": str(out_dir),
        "candidates": candidate_scores,
        "candidate_count": len(candidate_scores),
        "average_score": round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0,
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
