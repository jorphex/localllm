import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from scripts import omnivoice_client


class MockResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class OmniVoiceClientTests(unittest.TestCase):
    def test_healthcheck_parses_json(self):
        payload = json.dumps({"status": "ok"}).encode("utf-8")
        with patch("scripts.omnivoice_client.request.urlopen", return_value=MockResponse(payload)) as urlopen:
            result = omnivoice_client.healthcheck()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(urlopen.call_count, 1)

    def test_synthesize_tts_writes_audio_file(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output_path = Path(tempdir) / "audio.wav"
            with patch(
                "scripts.omnivoice_client.request.urlopen",
                return_value=MockResponse(b"RIFFfakewav"),
            ) as urlopen:
                result = omnivoice_client.synthesize_tts("hello", output_path)

            self.assertEqual(result, output_path)
            self.assertEqual(output_path.read_bytes(), b"RIFFfakewav")
            self.assertEqual(urlopen.call_count, 1)

    def test_synthesize_tts_rejects_blank_text(self):
        with self.assertRaises(ValueError):
            omnivoice_client.synthesize_tts("   ", "/tmp/out.wav")

    def test_synthesize_tts_requires_ref_text_for_clone(self):
        with self.assertRaises(ValueError):
            omnivoice_client.synthesize_tts(
                "hello",
                "/tmp/out.wav",
                ref_audio="/tmp/ref.wav",
                ref_text=None,
            )
