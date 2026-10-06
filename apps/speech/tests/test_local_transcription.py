from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from errors import SpeechValidationError
from store import read_settings, write_settings
from transcription import transcribe_audio_payload
from transcription_policy import local_only_requested


class LocalTranscriptionTests(unittest.TestCase):
    def test_local_request_never_uses_remote_default_or_delivered_secret(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(b"\0\0" * 16000)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_settings(root, {**read_settings(root), "transcription_engine": "deepgram"})
            def local_engine(path, *, settings, **kwargs):
                self.assertEqual(settings["transcription_engine"], "auto")
                self.assertNotIn("_app_secrets", settings)
                self.assertNotIn("_provider_config", settings)
                return {"text": "Una prova locale", "engine": "faster-whisper", "language": "it", "duration_seconds": 1, "segments": []}
            with patch("transcription.transcribe_audio_file", side_effect=local_engine), patch("transcription.transcribe_deepgram_flux_audio_chunk", side_effect=AssertionError("remote STT forbidden")):
                result = transcribe_audio_payload(data_root=root, body={"action": "transcribe_audio", "local_only": True,
                    "audio_base64": base64.b64encode(output.getvalue()).decode(), "content_type": "audio/wav",
                    "_app_secrets": {"deepgram-api-key": "must-not-be-used"}, "_provider_config": {"remote": True}})
            self.assertEqual(result["engine"], "faster-whisper")
            self.assertEqual(read_settings(root)["transcription_engine"], "deepgram")
            payload = {"surface": "secret_selector", "data_root": str(root), "body": {"action": "transcribe_audio", "local_only": True}}
            process = subprocess.run([sys.executable, str(ROOT / "backend/app_backend.py")], input=json.dumps(payload), text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(process.stdout), {"requires_secrets": False, "logical_names": []})

    def test_local_request_rejects_streaming_modes_and_non_boolean_flag(self):
        for body in ({"local_only": "true"}, {"local_only": True, "conversation": True}, {"local_only": True, "dictation": True}, {"local_only": True, "session_id": "session"}):
            with self.subTest(body=body), self.assertRaises(SpeechValidationError):
                local_only_requested(body)


if __name__ == "__main__":
    unittest.main()
