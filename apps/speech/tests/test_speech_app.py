from __future__ import annotations

import base64
import os
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from errors import SpeechProviderUnavailableError, SpeechValidationError
from service import handle_action


class SpeechAppTests(unittest.TestCase):
    def test_contract_is_backend_only_speech_provider(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertEqual(parsed.app_id, "speech")
        self.assertEqual(parsed.contract.presentation.frontend_role, "none")
        self.assertIsNone(parsed.contract.entrypoints.frontend)
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        provided = {item.interface: item for item in parsed.contract.provides}
        self.assertIn("speech.synthesis", provided)
        self.assertEqual(provided["speech.synthesis"].surfaces, ["backend"])
        self.assertNotIn("speech.transcription", provided)
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/speech/jobs.json"])

    def test_capabilities_report_unavailable_without_local_engine(self) -> None:
        with patch("service.resolve_local_engine", return_value=None):
            status_code, payload = handle_action(Path("data"), Path("generated"), {"action": "capabilities"})

        self.assertEqual(status_code, 200)
        self.assertFalse(payload["interfaces"]["speech.synthesis"]["provider_available"])
        self.assertFalse(payload["interfaces"]["speech.synthesis"]["output"]["workspace_relative_path"])
        self.assertEqual(payload["interfaces"]["speech.synthesis"]["output"]["retention"], "ephemeral")
        self.assertFalse(payload["interfaces"]["speech.transcription"]["provider_available"])

    def test_synthesize_rejects_empty_or_too_long_text(self) -> None:
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "synthesize", "text": ""})
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "synthesize", "text": "x" * 1501})

    def test_synthesize_reports_provider_unavailable_without_engine(self) -> None:
        with patch("service.resolve_local_engine", return_value=None):
            with self.assertRaises(SpeechProviderUnavailableError):
                handle_action(Path("data"), Path("generated"), {"action": "synthesize", "text": "Hello"})

    def test_synthesize_returns_inline_audio_and_job_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine_path = root / "espeak"
            wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\0" * 20
            engine_path.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[sys.argv.index('-w') + 1]).write_bytes(%r)\n" % wav_bytes,
                encoding="utf-8",
            )
            engine_path.chmod(engine_path.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}{os.pathsep}{old_path}"
            try:
                status_code, payload = handle_action(
                    root / "data",
                    root / "generated",
                    {"action": "synthesize", "text": "Hello world"},
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(status_code, 200)
            self.assertEqual(base64.b64decode(payload["audio_base64"]), wav_bytes)
            self.assertEqual(payload["retention"], "ephemeral")
            self.assertNotIn("workspace_relative_path", payload)
            self.assertFalse((root / "generated" / "speech" / f"{payload['job_id']}.wav").exists())
            jobs = (root / "data" / "jobs.json").read_text(encoding="utf-8")
            self.assertIn(payload["job_id"], jobs)
            self.assertIn('"retention": "ephemeral"', jobs)
            self.assertNotIn("workspace_relative_path", jobs)


if __name__ == "__main__":
    unittest.main()
