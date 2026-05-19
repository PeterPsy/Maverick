from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
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
        self.assertIn("speech.transcription", provided)
        self.assertEqual(provided["speech.transcription"].surfaces, ["backend", "cli", "mcp"])
        self.assertEqual(parsed.contract.storage.primary_paths, ["data/speech/jobs.json", "data/speech/settings.json"])
        self.assertEqual(parsed.contract.entrypoints.cli, "cli/app_cli.py")
        self.assertEqual(parsed.contract.entrypoints.mcp, "mcp/server.py")

    def test_capabilities_report_unavailable_without_local_engine(self) -> None:
        with patch("service.resolve_local_engine", return_value=None), patch("service.resolve_transcription_engine", return_value=""):
            status_code, payload = handle_action(Path("data"), Path("generated"), {"action": "capabilities"})

        self.assertEqual(status_code, 200)
        self.assertFalse(payload["interfaces"]["speech.synthesis"]["provider_available"])
        self.assertFalse(payload["interfaces"]["speech.synthesis"]["output"]["workspace_relative_path"])
        self.assertEqual(payload["interfaces"]["speech.synthesis"]["output"]["retention"], "ephemeral")
        self.assertFalse(payload["interfaces"]["speech.transcription"]["provider_available"])
        self.assertFalse(payload["interfaces"]["speech.transcription"]["streaming_supported"])
        self.assertTrue(payload["interfaces"]["speech.transcription"]["inputs"]["audio_base64"])

    def test_synthesize_rejects_empty_or_too_long_text(self) -> None:
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "synthesize", "text": ""})
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "synthesize", "text": "x" * 1501})

    def test_synthesize_reports_provider_unavailable_without_engine(self) -> None:
        with patch("synthesis.resolve_local_engine", return_value=None):
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
            self.assertNotIn("audio_data_url", payload)
            self.assertEqual(payload["retention"], "ephemeral")
            self.assertNotIn("workspace_relative_path", payload)
            self.assertFalse((root / "generated" / "speech" / f"{payload['job_id']}.wav").exists())
            jobs = (root / "data" / "jobs.json").read_text(encoding="utf-8")
            self.assertIn(payload["job_id"], jobs)
            self.assertIn('"retention": "ephemeral"', jobs)
            self.assertNotIn("workspace_relative_path", jobs)

    def test_list_engines_reports_synthesis_and_transcription(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("settings.synthesis_engine_statuses", return_value=[{"engine": "espeak", "kind": "tts", "available": False}]):
                with patch("settings.transcription_engine_statuses", return_value=[{"engine": "faster-whisper", "kind": "stt", "available": True}]):
                    status_code, payload = handle_action(Path(temp_dir), Path("generated"), {"action": "list_engines"})

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["synthesis"][0]["engine"], "espeak")
        self.assertEqual(payload["transcription"][0]["engine"], "faster-whisper")
        self.assertEqual(payload["settings"]["transcription_engine"], "auto")
        self.assertIn("faster_whisper_model_configured", payload["settings"])
        self.assertIn("whisper_cpp_model_configured", payload["settings"])

    def test_set_engine_rejects_host_path_settings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(SpeechValidationError):
                handle_action(
                    root / "data",
                    root / "generated",
                    {
                        "action": "set_engine",
                        "transcription_engine": "whisper.cpp",
                        "whisper_cpp_model_path": "/host/model.bin",
                    },
                )
            status_code, payload = handle_action(root / "data", root / "generated", {"action": "set_engine", "transcription_engine": "whisper.cpp"})

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["settings"]["transcription_engine"], "whisper.cpp")
            settings_json = (root / "data" / "settings.json").read_text(encoding="utf-8")
            self.assertNotIn("whisper_cpp_model_path", settings_json)

    def test_transcribe_audio_returns_text_and_metadata_only_job(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        fake_result = {
            "engine": "faster-whisper",
            "model": "base",
            "language": "en",
            "language_probability": 0.95,
            "duration_seconds": 1.25,
            "segments": [{"start": 0.0, "end": 1.25, "text": " Hello world "}],
            "text": " Hello world ",
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("transcription.transcribe_audio_file", return_value=fake_result):
                status_code, payload = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {
                        "action": "transcribe_audio",
                        "content_type": "audio/wav",
                        "audio_base64": base64.b64encode(audio).decode("ascii"),
                    },
                )

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["text"], "Hello world")
            self.assertEqual(payload["engine"], "faster-whisper")
            self.assertEqual(payload["retention"], "metadata_only")
            jobs = (root / "data" / "jobs.json").read_text(encoding="utf-8")
            self.assertIn('"kind": "stt"', jobs)
            self.assertIn('"transcript_chars": 11', jobs)

    def test_transcribe_audio_rejects_long_audio_before_engine(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("transcription.probe_audio_duration_seconds", return_value=181.0):
                with patch("transcription.transcribe_audio_file") as transcribe_audio_file:
                    with self.assertRaises(SpeechValidationError):
                        handle_action(
                            root / "data",
                            root / "storage" / "generated",
                            {
                                "action": "transcribe_audio",
                                "content_type": "audio/wav",
                                "audio_base64": base64.b64encode(audio).decode("ascii"),
                            },
                        )

            transcribe_audio_file.assert_not_called()

    def test_transcribe_audio_rejects_invalid_payloads(self) -> None:
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "transcribe_audio", "content_type": "text/plain", "audio_base64": "abcd"})
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "transcribe_audio", "content_type": "audio/wav", "audio_base64": "not base64"})

    def test_transcribe_file_resolves_only_workspace_storage_paths(self) -> None:
        fake_result = {
            "engine": "faster-whisper",
            "model": "base",
            "language": "en",
            "language_probability": 0.9,
            "duration_seconds": 0.5,
            "segments": [],
            "text": "File transcript",
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploaded = root / "storage" / "uploaded"
            uploaded.mkdir(parents=True)
            audio_path = uploaded / "sample.wav"
            audio_path.write_bytes(b"RIFF" + b"\0" * 512)
            with patch("transcription.transcribe_audio_file", return_value=fake_result):
                status_code, payload = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {"action": "transcribe_file", "workspace_relative_path": "storage/uploaded/sample.wav"},
                    uploaded,
                )

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["text"], "File transcript")
            with self.assertRaises(SpeechValidationError):
                handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {"action": "transcribe_file", "workspace_relative_path": "../sample.wav"},
                    uploaded,
                )

    def test_whisper_cpp_transcription_redacts_operator_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary_path = root / "whisper-cli"
            model_path = root / "models" / "ggml.bin"
            uploaded = root / "storage" / "uploaded"
            uploaded.mkdir(parents=True)
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"model")
            audio_path = uploaded / "sample.wav"
            audio_path.write_bytes(b"RIFF" + b"\0" * 512)
            binary_path.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[sys.argv.index('-of') + 1] + '.txt').write_text('redacted transcript', encoding='utf-8')\n",
                encoding="utf-8",
            )
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR)
            old_binary = os.environ.get("MAVERICK_SPEECH_WHISPER_CPP_BINARY")
            old_model = os.environ.get("MAVERICK_SPEECH_WHISPER_CPP_MODEL")
            os.environ["MAVERICK_SPEECH_WHISPER_CPP_BINARY"] = str(binary_path)
            os.environ["MAVERICK_SPEECH_WHISPER_CPP_MODEL"] = str(model_path)
            try:
                handle_action(root / "data", root / "storage" / "generated", {"action": "set_engine", "transcription_engine": "whisper.cpp"})
                status_code, payload = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {"action": "transcribe_file", "workspace_relative_path": "storage/uploaded/sample.wav"},
                    uploaded,
                )
            finally:
                if old_binary is None:
                    os.environ.pop("MAVERICK_SPEECH_WHISPER_CPP_BINARY", None)
                else:
                    os.environ["MAVERICK_SPEECH_WHISPER_CPP_BINARY"] = old_binary
                if old_model is None:
                    os.environ.pop("MAVERICK_SPEECH_WHISPER_CPP_MODEL", None)
                else:
                    os.environ["MAVERICK_SPEECH_WHISPER_CPP_MODEL"] = old_model

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["text"], "redacted transcript")
            self.assertEqual(payload["model"], "local-path")
            jobs = (root / "data" / "jobs.json").read_text(encoding="utf-8")
            self.assertNotIn(str(model_path), jobs)


    def test_cli_and_mcp_manifest_entrypoints_are_bounded_to_file_transcription(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_payload = {
                "workspace_id": "default",
                "app_id": "speech",
                "data_root": str(root / "data"),
                "generated_storage_root": str(root / "storage" / "generated"),
                "uploaded_storage_root": str(root / "storage" / "uploaded"),
            }
            cli_result = subprocess.run(
                [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
                input=json.dumps({**base_payload, "arguments": {"action": "operations.manifest"}}),
                text=True,
                capture_output=True,
                check=True,
            )
            mcp_result = subprocess.run(
                [sys.executable, str(APP_ROOT / "mcp" / "server.py")],
                input=json.dumps({**base_payload, "tool_name": "speech_operations_manifest", "arguments": {}}),
                text=True,
                capture_output=True,
                check=True,
            )

        cli_payload = json.loads(cli_result.stdout)
        mcp_payload = json.loads(mcp_result.stdout)
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertIn("transcribe_file", cli_payload["operations"])
        self.assertIn("transcribe_file", mcp_payload["operations"])
        self.assertNotIn("transcribe_audio", cli_payload["operations"])
        self.assertNotIn("transcribe_audio", mcp_payload["operations"])


if __name__ == "__main__":
    unittest.main()
