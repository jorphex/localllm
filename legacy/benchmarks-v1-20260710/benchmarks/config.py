"""Shared benchmark configuration loader and builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def server_extra_args(
    *,
    project_root_override: Path | str | None = None,
    extra_overrides: dict[str, Any] | None = None,
) -> str:
    """Build the default llama-server extra-args string from config.

    Parameters can be overridden for a specific run; for example
    ``extra_overrides={"no_mmap": False}`` omits ``--no-mmap``.
    """
    cfg = load_config()
    server = cfg["server"].copy()
    if extra_overrides:
        server.update(extra_overrides)
    root = Path(project_root_override) if project_root_override else project_root()

    parts: list[str] = [
        f"-np {server['np']}",
        f"-tb {server['tb']}",
        f"-b {server['batch_size']}",
        f"-ub {server['ub']}",
    ]

    if server.get("flash_attention"):
        parts.append("-fa on")

    parts.append(f"--threads-http {server['threads_http']}")
    parts.append(f"-ctk {server['cache_type_k']}")
    parts.append(f"-ctv {server['cache_type_v']}")

    if server.get("reasoning"):
        parts.append("--reasoning on")
    if server.get("metrics"):
        parts.append("--metrics")
    if server.get("no_warmup"):
        parts.append("--no-warmup")
    if server.get("no_mmap"):
        parts.append("--no-mmap")

    parts.append(f"--image-max-tokens {server['image_max_tokens']}")

    if server.get("ctx_checkpoints") is not None:
        parts.append(f"--ctx-checkpoints {server['ctx_checkpoints']}")
    if server.get("swa_full"):
        parts.append("--swa-full")

    sampling = server.get("default_sampling", {})
    parts.append(f"--temp {sampling.get('temperature', 0.6)}")
    parts.append(f"--top-k {sampling.get('top_k', 20)}")
    parts.append(f"--top-p {sampling.get('top_p', 0.95)}")
    parts.append(f"--min-p {sampling.get('min_p', 0.0)}")
    parts.append(f"--presence-penalty {sampling.get('presence_penalty', 0.0)}")
    parts.append(f"--repeat-penalty {sampling.get('repeat_penalty', 1.0)}")

    if sampling.get("spec_default"):
        parts.append("--spec-default")

    slot_path = server.get("slot_save_path")
    if slot_path:
        parts.append(f"--slot-save-path {root / slot_path}")

    return " ".join(parts)


def default_context() -> int:
    return int(load_config()["server"]["default_context"])


def agentic_sampling() -> dict[str, Any]:
    return load_config()["agentic_sampling"].copy()


def default_sampling() -> dict[str, Any]:
    return load_config()["server"]["default_sampling"].copy()


def suite_items(suite: str) -> list[str]:
    suite_cfg = load_config()["suites"][suite]
    for key in ("fixtures", "scenarios", "prompts"):
        if key in suite_cfg:
            return list(suite_cfg[key])
    return []


def scoring_weights(metric: str) -> dict[str, float]:
    return load_config()["scoring"][metric]["weights"].copy()