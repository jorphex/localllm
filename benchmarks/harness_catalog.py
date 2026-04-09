from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HarnessSuite:
    name: str
    family: str
    driver: str
    confidence: str
    primary_for_decisions: bool
    real_use_case_anchor: str
    role: str


SUITES = (
    HarnessSuite(
        name="transcript_replay",
        family="general_agentic",
        driver="benchmarks/transcript_replay/run_compare.sh",
        confidence="high",
        primary_for_decisions=True,
        real_use_case_anchor="Replays real exported agent transcripts turn by turn.",
        role="Primary general agent benchmark. Best fit for long-turn flow, continuation behavior, and tool-choice drift.",
    ),
    HarnessSuite(
        name="agentic_barrage",
        family="general_agentic",
        driver="benchmarks/agentic_barrage.sh",
        confidence="medium",
        primary_for_decisions=False,
        real_use_case_anchor="Synthetic prompt suite for planning, revision, and tool-restraint behavior.",
        role="Secondary diagnostic only. Useful for surfacing prompt-shape pathologies, not for final model ranking.",
    ),
    HarnessSuite(
        name="sim_compare",
        family="coding_agentic",
        driver="benchmarks/sim_compare/run_compare.sh",
        confidence="high",
        primary_for_decisions=True,
        real_use_case_anchor="Disposable repo with inspect/patch/verify loops and scope checks.",
        role="Primary coding-agent benchmark. Best fit for patch quality, recovery, scope discipline, and verify loops.",
    ),
    HarnessSuite(
        name="opencode_compare",
        family="coding_agentic",
        driver="benchmarks/opencode_compare/run_compare.sh",
        confidence="medium",
        primary_for_decisions=False,
        real_use_case_anchor="OpenCode-shaped prompt and tool-call flow without depending on the external CLI.",
        role="Secondary coding-agent benchmark. Useful for client-shape compatibility and concise tool-followthrough.",
    ),
    HarnessSuite(
        name="coding_compare",
        family="coding_agentic",
        driver="benchmarks/coding_compare.sh",
        confidence="low",
        primary_for_decisions=False,
        real_use_case_anchor="Single-turn coding prompts without repo state or verification loop.",
        role="Tertiary coding diagnostic only. Good for quick smoke checks, weak for real workflow ranking.",
    ),
)


def suites_by_family(family: str) -> list[HarnessSuite]:
    return [suite for suite in SUITES if suite.family == family]


def primary_suites(family: str | None = None) -> list[HarnessSuite]:
    suites = SUITES if family is None else suites_by_family(family)
    return [suite for suite in suites if suite.primary_for_decisions]


def external_cli_policy() -> str:
    return (
        "Use purpose-built local harnesses for scoring. Treat OpenCode or PI CLI runs as transcript "
        "sources, spot checks, or sanity checks rather than the canonical benchmark driver."
    )


def suite_matrix() -> list[dict]:
    return [asdict(suite) for suite in SUITES]
