#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import request


DEFAULT_TTS_BASE_URL = "http://127.0.0.1:8094"


def healthcheck(base_url: str = DEFAULT_TTS_BASE_URL, timeout: int = 30) -> dict[str, Any]:
    with request.urlopen(f"{base_url}/health", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def synthesize_tts(
    text: str,
    output_path: str | Path,
    *,
    base_url: str = DEFAULT_TTS_BASE_URL,
    ref_audio: str | None = None,
    ref_text: str | None = None,
    language: str | None = None,
    instruct: str | None = None,
    speed: float | None = None,
    duration: float | None = None,
    timeout: int = 300,
) -> Path:
    if not text or not text.strip():
        raise ValueError("text must be a non-empty string")
    if ref_audio and not ref_text:
        raise ValueError("ref_text is required when ref_audio is provided")

    payload: dict[str, Any] = {"text": text.strip()}
    optional = {
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        "language": language,
        "instruct": instruct,
        "speed": speed,
        "duration": duration,
    }
    for key, value in optional.items():
        if value is not None:
            payload[key] = value

    req = request.Request(
        f"{base_url}/tts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        audio = response.read()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    return out
