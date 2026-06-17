#!/usr/bin/env python3
import io
import json
import logging
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

import numpy as np
import soundfile as sf
import torch
from omnivoice import OmniVoice


LOG = logging.getLogger("omnivoice_server")


def parse_optional_positive_int(value: str | None, name: str) -> int | None:
    if value is None or not value.strip():
        return None
    parsed = int(value)
    if parsed < 1:
        raise ValueError(f"{name} must be >= 1")
    return parsed


def parse_dtype(value: str):
    normalized = (value or "float16").strip().lower()
    mapping = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if normalized not in mapping:
        raise ValueError(f"Unsupported TTS_DTYPE: {value}")
    return mapping[normalized]


def read_env():
    host = os.environ.get("TTS_HOST", "127.0.0.1")
    port = int(os.environ.get("TTS_PORT", "8094"))
    model_id = os.environ.get("TTS_MODEL", "k2-fsa/OmniVoice")
    device = os.environ.get("TTS_DEVICE", "cuda")
    dtype = parse_dtype(os.environ.get("TTS_DTYPE", "float16"))
    torch_threads = parse_optional_positive_int(
        os.environ.get("TTS_TORCH_THREADS"),
        "TTS_TORCH_THREADS",
    )
    torch_interop_threads = parse_optional_positive_int(
        os.environ.get("TTS_TORCH_INTEROP_THREADS"),
        "TTS_TORCH_INTEROP_THREADS",
    )
    return {
        "host": host,
        "port": port,
        "model_id": model_id,
        "device": device,
        "dtype": dtype,
        "torch_threads": torch_threads,
        "torch_interop_threads": torch_interop_threads,
    }


class OmniVoiceState:
    def __init__(
        self,
        model_id: str,
        device: str,
        dtype,
        torch_threads: int | None,
        torch_interop_threads: int | None,
    ):
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.torch_threads = torch_threads
        self.torch_interop_threads = torch_interop_threads
        self.lock = Lock()
        if torch_threads is not None:
            torch.set_num_threads(torch_threads)
        if torch_interop_threads is not None:
            torch.set_num_interop_threads(torch_interop_threads)
        LOG.info("Loading OmniVoice model %s on %s", model_id, device)
        self.model = OmniVoice.from_pretrained(
            model_id,
            device_map=device,
            dtype=dtype,
        )
        self.sampling_rate = self.model.sampling_rate

    def generate(self, payload: dict):
        kwargs = {
            "text": payload["text"],
        }
        for key in (
            "language",
            "ref_text",
            "ref_audio",
            "instruct",
            "duration",
            "speed",
        ):
            if payload.get(key) is not None:
                kwargs[key] = payload[key]

        with self.lock:
            audio = self.model.generate(**kwargs)[0]

        if hasattr(audio, "detach"):
            audio = audio.detach().float().cpu().numpy()

        audio = np.asarray(audio).squeeze()
        return audio


def wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, audio, sample_rate, format="WAV")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "OmniVoiceHTTP/0.1"

    @property
    def state(self) -> OmniVoiceState:
        return self.server.state

    def log_message(self, fmt, *args):
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def respond_json(self, status: int, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self.respond_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "model": self.state.model_id,
                    "device": self.state.device,
                    "torch_threads": torch.get_num_threads(),
                    "torch_interop_threads": torch.get_num_interop_threads(),
                    "sampling_rate": self.state.sampling_rate,
                },
            )
            return
        self.respond_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self.path != "/tts":
            self.respond_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return

        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "text_required"})
            return
        payload["text"] = text.strip()

        ref_audio = payload.get("ref_audio")
        ref_text = payload.get("ref_text")
        if ref_audio and not ref_text:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "ref_text_required_for_clone",
                    "detail": (
                        "Clone mode currently requires ref_text on this ROCm stack "
                        "because OmniVoice auto-transcription falls into a broken "
                        "torchcodec path."
                    ),
                },
            )
            return

        try:
            audio = self.state.generate(payload)
            save_path = payload.get("save_path")
            if save_path:
                sf.write(save_path, audio, self.state.sampling_rate)
            data = wav_bytes(audio, self.state.sampling_rate)
        except Exception as exc:
            LOG.exception("TTS generation failed")
            self.respond_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "tts_failed", "detail": str(exc)},
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Sample-Rate", str(self.state.sampling_rate))
        if save_path:
            self.send_header("X-Saved-Path", save_path)
        self.end_headers()
        self.wfile.write(data)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    config = read_env()
    state = OmniVoiceState(
        model_id=config["model_id"],
        device=config["device"],
        dtype=config["dtype"],
        torch_threads=config["torch_threads"],
        torch_interop_threads=config["torch_interop_threads"],
    )
    server = ThreadingHTTPServer((config["host"], config["port"]), Handler)
    server.state = state
    LOG.info(
        "Serving OmniVoice on %s:%s with model %s",
        config["host"],
        config["port"],
        config["model_id"],
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal OmniVoice server error")
        sys.exit(1)
