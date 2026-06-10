from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import stat
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import engines
import app_backend
import backend_worker
import stt_worker
import tts_worker
from errors import SpeechProviderUnavailableError, SpeechTranscriptionError, SpeechValidationError
from engines import LocalEngine, faster_whisper_model_ref, faster_whisper_model_source, tts_engine_cache_fingerprint
from models import (
    MAX_AUDIO_BYTES,
    MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES,
    MAX_INLINE_TRANSCRIPTION_SECONDS,
    MAX_TRANSCRIPTION_FILE_AUDIO_BYTES,
)
from service import app_events_for_action, handle_action, operations_manifest
from store import append_job, read_jobs, write_settings
from synthesis import evict_synthesis_cache
from transcription import cleaned_transcript


def _write_fake_faster_whisper_module(root: Path) -> None:
    (root / "faster_whisper.py").write_text(
        "class _Segment:\n"
        "    start = 0.0\n"
        "    end = 1.0\n"
        "    text = 'warm worker'\n"
        "\n"
        "class _Info:\n"
        "    language = 'en'\n"
        "    language_probability = 1.0\n"
        "    duration = 1.0\n"
        "\n"
        "class WhisperModel:\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        pass\n"
        "\n"
        "    def transcribe(self, *args, **kwargs):\n"
        "        return [_Segment()], _Info()\n",
        encoding="utf-8",
    )


def _write_fake_piper_module(root: Path, load_counter: Path) -> None:
    package = root / "piper"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "voice.py").write_text(
        "from pathlib import Path\n"
        "\n"
        "LOAD_COUNTER = Path(%r)\n"
        "\n"
        "class PiperVoice:\n"
        "    @classmethod\n"
        "    def load(cls, *args, **kwargs):\n"
        "        count = int(LOAD_COUNTER.read_text(encoding='utf-8')) if LOAD_COUNTER.exists() else 0\n"
        "        LOAD_COUNTER.write_text(str(count + 1), encoding='utf-8')\n"
        "        return cls()\n"
        "\n"
        "    def synthesize(self, text, wav_file):\n"
        "        wav_file.setnchannels(1)\n"
        "        wav_file.setsampwidth(2)\n"
        "        wav_file.setframerate(22050)\n"
        "        wav_file.writeframes((text or 'x').encode('utf-8')[:16])\n" % str(load_counter),
        encoding="utf-8",
    )


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


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
        self.assertTrue(parsed.contract.storage.supports_export)
        self.assertTrue(parsed.contract.lifecycle.export)
        self.assertEqual([event.resource for event in parsed.contract.capabilities.data_events], ["configuration"])
        self.assertEqual(parsed.contract.hook_timeouts.backend_seconds, 300)
        self.assertEqual(parsed.contract.entrypoints.cli, "cli/app_cli.py")
        self.assertEqual(parsed.contract.entrypoints.mcp, "mcp/server.py")

    def test_capabilities_report_unavailable_without_local_engine(self) -> None:
        with patch("service.resolve_local_engine", return_value=None), patch("service.resolve_transcription_engine", return_value=""):
            status_code, payload = handle_action(Path("data"), Path("generated"), {"action": "capabilities"})

        self.assertEqual(status_code, 200)
        self.assertFalse(payload["interfaces"]["speech.synthesis"]["provider_available"])
        self.assertFalse(payload["interfaces"]["speech.synthesis"]["output"]["workspace_relative_path"])
        self.assertEqual(payload["interfaces"]["speech.synthesis"]["output"]["retention"], "derived_cache")
        self.assertFalse(payload["interfaces"]["speech.transcription"]["provider_available"])
        self.assertFalse(payload["interfaces"]["speech.transcription"]["streaming_supported"])
        self.assertTrue(payload["interfaces"]["speech.transcription"]["inputs"]["audio_base64"])
        self.assertTrue(payload["interfaces"]["speech.transcription"]["inputs"]["http_binary_body"])
        self.assertEqual(payload["interfaces"]["speech.transcription"]["max_audio_bytes"], MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)
        self.assertEqual(payload["interfaces"]["speech.transcription"]["max_inline_audio_bytes"], MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)
        self.assertEqual(payload["interfaces"]["speech.transcription"]["max_file_audio_bytes"], MAX_TRANSCRIPTION_FILE_AUDIO_BYTES)
        self.assertEqual(payload["interfaces"]["speech.transcription"]["max_inline_duration_seconds"], MAX_INLINE_TRANSCRIPTION_SECONDS)
        self.assertEqual(payload["interfaces"]["speech.transcription"]["language_detection"], "auto")
        self.assertEqual(payload["interfaces"]["speech.transcription"]["inline_default_profile"], "fast")
        self.assertIn("fast", payload["interfaces"]["speech.transcription"]["profiles"])

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
            engine_path = root / "espeak-ng"
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
            self.assertEqual(payload["retention"], "derived_cache")
            self.assertEqual(payload["voice"], "en")
            self.assertFalse(payload["cache_hit"])
            self.assertNotIn("workspace_relative_path", payload)
            self.assertFalse((root / "generated" / "speech" / f"{payload['job_id']}.wav").exists())
            jobs = (root / "data" / "jobs.json").read_text(encoding="utf-8")
            self.assertIn(payload["job_id"], jobs)
            self.assertIn('"retention": "derived_cache"', jobs)
            self.assertNotIn("workspace_relative_path", jobs)

    def test_synthesize_honors_selected_engine_and_reuses_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine_path = root / "espeak"
            counter_path = root / "count.txt"
            wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\1" * 20
            engine_path.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import sys\n"
                "if '--voices' in sys.argv:\n"
                "    print('Pty Language Age/Gender VoiceName File Other')\n"
                "    print(' 5  en             M  en       en')\n"
                "    raise SystemExit(0)\n"
                "counter = Path(%r)\n"
                "counter.write_text(str(int(counter.read_text() or '0') + 1) if counter.exists() else '1', encoding='utf-8')\n"
                "Path(sys.argv[sys.argv.index('-w') + 1]).write_bytes(%r)\n" % (str(counter_path), wav_bytes),
                encoding="utf-8",
            )
            engine_path.chmod(engine_path.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}{os.pathsep}{old_path}"
            try:
                handle_action(root / "data", root / "generated", {"action": "set_engine", "synthesis_engine": "espeak"})
                first_status, first = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "Cache me"})
                second_status, second = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "Cache me"})
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(first["engine"], "espeak")
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertEqual(base64.b64decode(second["audio_base64"]), wav_bytes)
            self.assertEqual(counter_path.read_text(encoding="utf-8"), "1")

    def test_synthesize_cache_key_changes_when_engine_binary_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine_path = root / "espeak"
            counter_path = root / "count.txt"

            def write_engine(audio_byte: bytes) -> None:
                engine_path.write_text(
                    "#!/usr/bin/env python3\n"
                    "from pathlib import Path\n"
                    "import sys\n"
                    "if '--voices' in sys.argv:\n"
                    "    print('Pty Language Age/Gender VoiceName File Other')\n"
                    "    print(' 5  en             M  en       en')\n"
                    "    raise SystemExit(0)\n"
                    "counter = Path(%r)\n"
                    "counter.write_text(str(int(counter.read_text() or '0') + 1) if counter.exists() else '1', encoding='utf-8')\n"
                    "Path(sys.argv[sys.argv.index('-w') + 1]).write_bytes(%r)\n" % (str(counter_path), b"RIFF" + audio_byte * 32),
                    encoding="utf-8",
                )
                engine_path.chmod(engine_path.stat().st_mode | stat.S_IXUSR)

            write_engine(b"1")
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}{os.pathsep}{old_path}"
            try:
                handle_action(root / "data", root / "generated", {"action": "set_engine", "synthesis_engine": "espeak"})
                _, first = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "Invalidate me"})
                write_engine(b"22")
                _, second = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "Invalidate me"})
            finally:
                os.environ["PATH"] = old_path

            self.assertFalse(first["cache_hit"])
            self.assertFalse(second["cache_hit"])
            self.assertEqual(counter_path.read_text(encoding="utf-8"), "2")

    def test_synthesize_rejects_oversize_audio_before_cache_write(self) -> None:
        engine = SimpleNamespace(name="espeak", voice_id="en", voices=(), quality_profile="diagnostic", latency_profile="low")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("synthesis.resolve_local_engine", return_value=engine):
                with patch("synthesis.tts_engine_cache_fingerprint", return_value={"engine": "fake"}):
                    with patch("synthesis.run_local_engine", return_value=b"x" * (MAX_AUDIO_BYTES + 1)):
                        with self.assertRaises(SpeechValidationError):
                            handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "Too large"})

            cache_dir = root / "data" / "cache" / "tts"
            self.assertFalse(cache_dir.exists() and any(cache_dir.iterdir()))

    def test_synthesis_cache_eviction_bounds_file_count_and_age(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "data" / "cache" / "tts"
            cache_dir.mkdir(parents=True)
            paths = [cache_dir / f"{index}.wav" for index in range(4)]
            for index, path in enumerate(paths):
                path.write_bytes(b"RIFF" + bytes([index]) * 12)
                os.utime(path, (1000 + index, 1000 + index))

            with patch("synthesis.TTS_CACHE_MAX_FILES", 2):
                with patch("synthesis.TTS_CACHE_MAX_BYTES", 1_000_000):
                    with patch("synthesis.TTS_CACHE_MAX_AGE_SECONDS", 1_000_000):
                        with patch("synthesis.time.time", return_value=1004):
                            evict_synthesis_cache(root / "data")

            self.assertEqual(sorted(path.name for path in cache_dir.glob("*.wav")), ["2.wav", "3.wav"])

    def test_synthesize_cache_miss_enforces_size_bounds_even_when_age_cleanup_is_fresh(self) -> None:
        engine = SimpleNamespace(name="espeak", voice_id="en", voices=(), quality_profile="diagnostic", latency_profile="low")
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "data" / "cache" / "tts"
            cache_dir.mkdir(parents=True)
            for index in range(2):
                path = cache_dir / f"old-{index}.wav"
                path.write_bytes(b"RIFF" + bytes([index]) * 12)
                os.utime(path, (1000 + index, 1000 + index))
            marker = cache_dir / ".last_cleanup"
            marker.touch()
            os.utime(marker, (2_000, 2_000))

            with patch("synthesis.resolve_local_engine", return_value=engine):
                with patch("synthesis.tts_engine_cache_fingerprint", return_value={"engine": "fake"}):
                    with patch("synthesis.run_local_engine", return_value=b"RIFFnew"):
                        with patch("synthesis.TTS_CACHE_MAX_FILES", 2):
                            with patch("synthesis.TTS_CACHE_MAX_BYTES", 1_000_000):
                                with patch("synthesis.TTS_CACHE_CLEANUP_INTERVAL_SECONDS", 300):
                                    with patch("synthesis.time.time", return_value=2_001):
                                        status_code, payload = handle_action(
                                            root / "data",
                                            root / "generated",
                                            {"action": "synthesize", "text": "new chunk"},
                                        )

            self.assertEqual(status_code, 200)
            self.assertFalse(payload["cache_hit"])
            cache_files = sorted(path.name for path in cache_dir.glob("*.wav"))
            self.assertEqual(len(cache_files), 2)
            self.assertNotIn("old-0.wav", cache_files)

    def test_list_engines_reports_synthesis_and_transcription(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch("settings.synthesis_engine_statuses", return_value=[{"engine": "espeak", "kind": "tts", "available": False}]):
                with patch("settings.transcription_engine_statuses", return_value=[{"engine": "faster-whisper", "kind": "stt", "available": True}]):
                    status_code, payload = handle_action(Path(temp_dir), Path("generated"), {"action": "list_engines"})

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["synthesis"][0]["engine"], "espeak")
        self.assertEqual(payload["transcription"][0]["engine"], "faster-whisper")
        self.assertEqual(payload["settings"]["transcription_engine"], "auto")
        self.assertEqual(payload["settings"]["transcription_profile"], "balanced")
        self.assertIn("faster_whisper_model_configured", payload["settings"])
        self.assertIn("whisper_cpp_model_configured", payload["settings"])

    def test_faster_whisper_model_can_be_overridden_per_profile(self) -> None:
        old_global = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_MODEL")
        old_global_all = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES")
        old_device = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_DEVICE")
        old_compute = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE")
        old_fast = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_FAST_MODEL")
        old_balanced = os.environ.get("MAVERICK_SPEECH_FASTER_WHISPER_BALANCED_MODEL")
        os.environ["MAVERICK_SPEECH_FASTER_WHISPER_MODEL"] = "/models/global"
        os.environ.pop("MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES", None)
        os.environ.pop("MAVERICK_SPEECH_FASTER_WHISPER_DEVICE", None)
        os.environ.pop("MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE", None)
        os.environ["MAVERICK_SPEECH_FASTER_WHISPER_FAST_MODEL"] = "/models/fast"
        os.environ["MAVERICK_SPEECH_FASTER_WHISPER_BALANCED_MODEL"] = "/models/balanced"
        try:
            self.assertEqual(faster_whisper_model_ref({"transcription_profile": "fast"}), "/models/fast")
            self.assertEqual(faster_whisper_model_source({"transcription_profile": "fast"}), "profile_env")
            self.assertEqual(faster_whisper_model_ref({"transcription_profile": "balanced"}), "/models/balanced")
            self.assertEqual(faster_whisper_model_ref({"transcription_profile": "accurate"}), "medium")
            self.assertEqual(faster_whisper_model_source({"transcription_profile": "accurate"}), "profile_default")
            os.environ["MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES"] = "1"
            self.assertEqual(faster_whisper_model_ref({"transcription_profile": "accurate"}), "/models/global")
            self.assertEqual(faster_whisper_model_source({"transcription_profile": "accurate"}), "global_env")
            self.assertEqual(engines.faster_whisper_device({"transcription_profile": "fast"}), "cpu")
            self.assertEqual(engines.faster_whisper_compute_type({"transcription_profile": "fast"}), "int8")
        finally:
            _restore_env("MAVERICK_SPEECH_FASTER_WHISPER_MODEL", old_global)
            _restore_env("MAVERICK_SPEECH_FASTER_WHISPER_GLOBAL_MODEL_ALL_PROFILES", old_global_all)
            _restore_env("MAVERICK_SPEECH_FASTER_WHISPER_DEVICE", old_device)
            _restore_env("MAVERICK_SPEECH_FASTER_WHISPER_COMPUTE_TYPE", old_compute)
            _restore_env("MAVERICK_SPEECH_FASTER_WHISPER_FAST_MODEL", old_fast)
            _restore_env("MAVERICK_SPEECH_FASTER_WHISPER_BALANCED_MODEL", old_balanced)

    def test_faster_whisper_worker_status_handles_model_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_dir = root / "faster-whisper-small"
            model_dir.mkdir()
            (model_dir / "config.json").write_text('{"model_type": "whisper"}', encoding="utf-8")
            (model_dir / "model.bin").write_bytes(b"weights")
            with patch.dict(
                os.environ,
                {
                    "MAVERICK_SPEECH_FASTER_WHISPER_MODEL": str(model_dir),
                    "MAVERICK_SPEECH_FASTER_WHISPER_BALANCED_MODEL": "",
                },
            ):
                fingerprint = engines._file_fingerprint(str(model_dir))
                status_code, payload = handle_action(root / "data", root / "generated", {"action": "worker_status"})

        self.assertEqual(fingerprint["kind"], "directory")
        self.assertEqual(fingerprint["files"][0]["name"], "config.json")
        weight_entries = [item for item in fingerprint["files"] if item["name"] == "model.bin"]
        self.assertEqual(weight_entries[0]["kind"], "weight_metadata")
        self.assertEqual(weight_entries[0]["size_bytes"], 7)
        self.assertNotIn("sha256", weight_entries[0])
        self.assertEqual(status_code, 200)
        self.assertTrue(payload["worker_status"]["current"]["worker_id"].startswith("fw-"))

    def test_worker_status_is_observational_by_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "auto"}):
                with patch("engines.resolve_transcription_engine", return_value="faster-whisper"):
                    with patch("engines._ensure_external_faster_whisper_worker") as ensure_worker:
                        status = engines.faster_whisper_worker_status(data_root, {"transcription_profile": "fast"})

        self.assertFalse(status["prewarm"]["attempted"])
        ensure_worker.assert_not_called()

    def test_worker_prewarm_explicitly_warms_current_faster_whisper_worker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "auto"}):
                with patch("engines.resolve_transcription_engine", return_value="faster-whisper"):
                    with patch("engines._ensure_external_faster_whisper_worker") as ensure_worker:
                        status = engines.faster_whisper_worker_status(data_root, {"transcription_profile": "fast"}, ensure_warm=True)

        self.assertTrue(status["prewarm"]["attempted"])
        self.assertTrue(status["prewarm"]["ok"])
        ensure_worker.assert_called_once()

    def test_worker_status_current_profile_matches_chat_inline_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            with patch.dict(
                os.environ,
                {
                    "MAVERICK_SPEECH_FASTER_WHISPER_FAST_MODEL": "/models/fast",
                    "MAVERICK_SPEECH_FASTER_WHISPER_BALANCED_MODEL": "/models/balanced",
                    "MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "auto",
                },
            ):
                with patch("engines.resolve_transcription_engine", return_value="faster-whisper"):
                    with patch("engines._ensure_external_faster_whisper_worker") as ensure_worker:
                        status = engines.faster_whisper_worker_status(data_root, {"transcription_profile": "balanced"})

        self.assertEqual(status["settings_profile"], "balanced")
        self.assertEqual(status["current_profile"], "fast")
        self.assertEqual(status["current_usage"], "inline_default")
        self.assertEqual(status["profiles"][0]["profile"], "fast")
        self.assertEqual(status["profiles"][0]["usages"][0]["operation"], "transcribe_audio")
        self.assertEqual(status["profiles"][1]["profile"], "balanced")
        self.assertEqual(status["profiles"][1]["usages"][0]["operation"], "transcribe_file")
        self.assertFalse(status["prewarm"]["attempted"])
        ensure_worker.assert_not_called()

    def test_worker_status_prunes_dead_pid_and_stale_socket_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            run_dir = data_root / "run"
            run_dir.mkdir(parents=True)
            stale_pid = run_dir / "fw-stale.pid"
            stale_socket = run_dir / "fw-stale.sock"
            stale_pid.write_text("99999999", encoding="utf-8")
            stale_socket.write_text("", encoding="utf-8")
            with patch("engines.resolve_transcription_engine", return_value=""):
                status = engines.faster_whisper_worker_status(data_root, {"transcription_profile": "fast"})

        self.assertFalse(stale_pid.exists())
        self.assertFalse(stale_socket.exists())
        self.assertEqual(status["workers"], [])

    def test_backend_manifest_exposes_only_read_only_worker_status(self) -> None:
        manifest = operations_manifest()

        self.assertIn("worker_status", manifest["operations"])
        self.assertNotIn("worker_stop", manifest["operations"])
        self.assertNotIn("worker_reload", manifest["operations"])

    def test_app_backend_reuses_persistent_worker_between_requests(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            payload = {
                "data_root": str(data_root),
                "generated_storage_root": str(root / "generated"),
                "uploaded_storage_root": "",
                "body": {"action": "get_settings"},
            }
            old_mode = os.environ.get("MAVERICK_SPEECH_BACKEND_WORKER")
            old_idle = os.environ.get("MAVERICK_SPEECH_BACKEND_WORKER_IDLE_SECONDS")
            os.environ["MAVERICK_SPEECH_BACKEND_WORKER"] = "persistent"
            os.environ["MAVERICK_SPEECH_BACKEND_WORKER_IDLE_SECONDS"] = "60"
            try:
                first = app_backend.handle_entrypoint_payload(payload)
                paths = app_backend.backend_worker_paths(data_root)
                first_pid = app_backend.read_worker_pid(paths["pid"])
                second = app_backend.handle_entrypoint_payload(payload)
                second_pid = app_backend.read_worker_pid(paths["pid"])
            finally:
                app_backend.stop_backend_workers(data_root)
                _restore_env("MAVERICK_SPEECH_BACKEND_WORKER", old_mode)
                _restore_env("MAVERICK_SPEECH_BACKEND_WORKER_IDLE_SECONDS", old_idle)

        self.assertEqual(first["status_code"], 200)
        self.assertEqual(second["status_code"], 200)
        self.assertGreater(first_pid, 0)
        self.assertEqual(first_pid, second_pid)

    def test_backend_worker_serves_independent_requests_concurrently(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            socket_path = root / "backend.sock"
            pid_path = root / "backend.pid"
            slow_started = threading.Event()
            release_slow = threading.Event()
            slow_result: dict[str, object] = {}

            def fake_handle_payload(payload: dict) -> dict:
                action = payload.get("body", {}).get("action")
                if action == "slow":
                    slow_started.set()
                    release_slow.wait(2)
                    return {"status_code": 200, "json": {"ok": "slow"}}
                return {"status_code": 200, "json": {"ok": "quick"}}

            def send_request(action: str, timeout: float = 1.0) -> dict:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(timeout)
                    client.connect(str(socket_path))
                    client.sendall((json.dumps({"body": {"action": action}}) + "\n").encode("utf-8"))
                    client.shutdown(socket.SHUT_WR)
                    chunks: list[bytes] = []
                    while True:
                        chunk = client.recv(1024 * 1024)
                        if not chunk:
                            break
                        chunks.append(chunk)
                return json.loads(b"".join(chunks).decode("utf-8"))

            with patch("backend_worker.handle_payload", side_effect=fake_handle_payload):
                server_thread = threading.Thread(
                    target=backend_worker.serve,
                    kwargs={"socket_path": socket_path, "pid_path": pid_path, "idle_timeout_seconds": 0.1},
                    daemon=True,
                )
                server_thread.start()
                for _ in range(50):
                    if socket_path.exists():
                        break
                    threading.Event().wait(0.02)
                slow_thread = threading.Thread(target=lambda: slow_result.update(send_request("slow", timeout=3.0)))
                slow_thread.start()
                self.assertTrue(slow_started.wait(1))

                quick = send_request("quick", timeout=1.0)
                release_slow.set()
                slow_thread.join(3)
                server_thread.join(2)

        self.assertEqual(quick["json"]["ok"], "quick")
        self.assertEqual(slow_result["json"]["ok"], "slow")

    def test_transcription_status_reports_persistent_worker_scope(self) -> None:
        with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "auto"}):
            with patch("engines.faster_whisper_available", return_value=False):
                with patch("engines.faster_whisper_model_configured", return_value=False):
                    statuses = engines.transcription_engine_statuses({"transcription_profile": "fast"})

        faster = statuses[0]
        self.assertEqual(faster["engine"], "faster-whisper")
        self.assertTrue(faster["persistent_worker"])
        self.assertEqual(faster["worker_mode"], "auto")
        self.assertEqual(faster["worker_scope"], "workspace_daemon")
        self.assertIn("model_source", faster)

    def test_transcription_status_can_report_entrypoint_worker_scope(self) -> None:
        with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "entrypoint"}):
            with patch("engines.faster_whisper_model_configured", return_value=False):
                statuses = engines.transcription_engine_statuses({"transcription_profile": "fast"})

        faster = statuses[0]
        self.assertEqual(faster["engine"], "faster-whisper")
        self.assertFalse(faster["persistent_worker"])
        self.assertEqual(faster["worker_mode"], "entrypoint")
        self.assertEqual(faster["worker_scope"], "entrypoint_process")

    def test_faster_whisper_uses_external_worker_when_data_root_is_available(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_path = root / "input.wav"
            audio_path.write_bytes(b"RIFF" + b"\0" * 512)
            fake_payload = {
                "ok": True,
                "result": {
                    "engine": "faster-whisper",
                    "model": "base",
                    "language": "en",
                    "language_probability": 0.9,
                    "duration_seconds": 1.0,
                    "segments": [],
                    "text": "hello",
                    "profile": "fast",
                    "beam_size": 1,
                    "worker": {"scope": "workspace_daemon", "cross_request_reuse": True},
                },
            }
            with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "persistent"}):
                with patch("engines._run_external_faster_whisper_worker_job", return_value=fake_payload) as external_worker:
                    result = engines._transcribe_with_faster_whisper(
                        audio_path,
                        settings={"transcription_profile": "fast", "_data_root": str(root / "data")},
                        language="en",
                    )

        self.assertEqual(result["worker"]["scope"], "workspace_daemon")
        external_worker.assert_called_once()

    def test_faster_whisper_auto_worker_fallback_is_reported(self) -> None:
        fake_payload = {"ok": True, "result": {"worker": {"scope": "entrypoint_process"}, "text": "fallback"}}
        with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "auto"}):
            with patch("engines._run_external_faster_whisper_worker_job", side_effect=OSError("socket failed")):
                with patch("engines._run_entrypoint_faster_whisper_worker_job", return_value=fake_payload) as entrypoint_worker:
                    payload = engines._run_faster_whisper_worker_job(
                        "input.wav",
                        config={"data_root": "/tmp/speech-data"},
                        language="",
                    )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["result"]["worker"]["persistent_worker_attempted"])
        self.assertIn("socket failed", payload["result"]["worker"]["persistent_worker_fallback_reason"])
        entrypoint_worker.assert_called_once()

    def test_faster_whisper_strict_persistent_worker_failure_is_visible(self) -> None:
        with patch.dict(os.environ, {"MAVERICK_SPEECH_FASTER_WHISPER_WORKER": "persistent"}):
            with patch("engines._run_external_faster_whisper_worker_job", side_effect=OSError("socket failed")):
                with patch("engines._run_entrypoint_faster_whisper_worker_job") as entrypoint_worker:
                    with self.assertRaises(SpeechTranscriptionError):
                        engines._run_faster_whisper_worker_job(
                            "input.wav",
                            config={"data_root": "/tmp/speech-data"},
                            language="",
                        )

        entrypoint_worker.assert_not_called()

    def test_external_worker_process_status_protocol_and_stop(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            _write_fake_faster_whisper_module(root)
            model_dir = root / "model-dir"
            model_dir.mkdir()
            (model_dir / "config.json").write_text("{}", encoding="utf-8")
            config = {
                "model": str(model_dir),
                "model_label": "local-path",
                "device": "auto",
                "compute_type": "default",
                "profile": "fast",
                "beam_size": 1,
                "data_root": str(data_root),
            }
            paths = engines._external_faster_whisper_worker_paths(config)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "MAVERICK_SPEECH_FASTER_WHISPER_WORKER_IDLE_SECONDS": "60",
                        "PYTHONPATH": f"{root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
                    },
                ):
                    engines._ensure_external_faster_whisper_worker(
                        config,
                        socket_path=paths["socket"],
                        pid_path=paths["pid"],
                        lock_path=paths["lock"],
                    )
                status = engines.faster_whisper_worker_status(data_root, {"transcription_profile": "fast"})
                response = engines._send_external_faster_whisper_job(
                    paths["socket"],
                    {"audio_path": str(root / "input.wav"), "language": ""},
                )
            finally:
                stopped = engines.stop_faster_whisper_workers(data_root)

            self.assertTrue(status["workers"])
            self.assertTrue(any(item["socket_reachable"] for item in status["workers"]))
            self.assertTrue(response["ok"])
            self.assertFalse(response["result"]["worker"]["cold_start"])
            self.assertTrue(paths["log"].exists())
            self.assertGreaterEqual(stopped["count"], 1)

    def test_stale_external_worker_pid_is_terminated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "data"
            _write_fake_faster_whisper_module(root)
            model_dir = root / "model-dir"
            model_dir.mkdir()
            (model_dir / "config.json").write_text("{}", encoding="utf-8")
            config = {
                "model": str(model_dir),
                "model_label": "local-path",
                "device": "auto",
                "compute_type": "default",
                "profile": "fast",
                "beam_size": 1,
                "data_root": str(data_root),
            }
            paths = engines._external_faster_whisper_worker_paths(config)
            try:
                with patch.dict(
                    os.environ,
                    {
                        "MAVERICK_SPEECH_FASTER_WHISPER_WORKER_IDLE_SECONDS": "60",
                        "PYTHONPATH": f"{root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
                    },
                ):
                    engines._ensure_external_faster_whisper_worker(
                        config,
                        socket_path=paths["socket"],
                        pid_path=paths["pid"],
                        lock_path=paths["lock"],
                    )
                pid = engines._read_worker_pid(paths["pid"])
                paths["socket"].unlink()
                engines._remove_stale_external_worker_files(paths["socket"], paths["pid"])
                self.assertFalse(engines._pid_matches_worker(pid, paths["socket"]))
                self.assertFalse(paths["pid"].exists())
            finally:
                engines.stop_faster_whisper_workers(data_root)

    def test_external_worker_listens_only_after_model_is_loaded(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            socket_path = root / "worker.sock"
            pid_path = root / "worker.pid"
            audio_path = root / "input.wav"
            audio_path.write_bytes(b"RIFF" + b"\0" * 512)
            load_events: list[bool] = []

            def fake_load_model(config: dict) -> object:
                load_events.append(socket_path.exists())
                return object()

            def fake_transcribe(model: object, audio_path: Path, *, config: dict, language: str = "") -> dict:
                return {
                    "engine": "faster-whisper",
                    "model": "fake",
                    "language": language,
                    "language_probability": 1.0,
                    "duration_seconds": 1.0,
                    "segments": [],
                    "text": "ready",
                }

            with patch("stt_worker._load_faster_whisper_model", side_effect=fake_load_model):
                with patch("stt_worker._run_faster_whisper_with_model", side_effect=fake_transcribe):
                    thread = threading.Thread(
                        target=stt_worker.serve,
                        kwargs={
                            "socket_path": socket_path,
                            "pid_path": pid_path,
                            "config": {"model_label": "fake", "beam_size": 1},
                            "idle_timeout_seconds": 1,
                        },
                    )
                    thread.start()
                    deadline = engines.time.monotonic() + 5
                    while engines.time.monotonic() < deadline and not socket_path.exists():
                        engines.time.sleep(0.05)
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.connect(str(socket_path))
                        client.sendall((json.dumps({"audio_path": str(audio_path), "language": "it"}) + "\n").encode("utf-8"))
                        client.shutdown(socket.SHUT_WR)
                        response = json.loads(client.recv(1024 * 1024).decode("utf-8"))
                    thread.join(timeout=3)

        self.assertEqual(load_events, [False])
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["worker"]["cold_start"])
        self.assertTrue(response["result"]["worker"]["ready_before_request"])

    def test_capabilities_report_default_english_voice_and_full_voice_list(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine_path = root / "espeak-ng"
            engine_path.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "if '--voices' in sys.argv:\n"
                "    print('Pty Language Age/Gender VoiceName File Other')\n"
                "    print(' 5  af             M  afrikaans    af')\n"
                "    print(' 5  en-029         M  English_(Caribbean)    en')\n"
                "    print(' 5  en-us          M  English_(America)      en')\n"
                "    raise SystemExit(0)\n"
                "raise SystemExit(1)\n",
                encoding="utf-8",
            )
            engine_path.chmod(engine_path.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}{os.pathsep}{old_path}"
            try:
                status_code, payload = handle_action(root / "data", root / "generated", {"action": "capabilities"})
            finally:
                os.environ["PATH"] = old_path

            synthesis = payload["interfaces"]["speech.synthesis"]
            self.assertEqual(status_code, 200)
            self.assertEqual(synthesis["default_voice"], "en-us")
            self.assertEqual([item["voice_id"] for item in synthesis["voices"]], ["af", "en-029", "en-us"])
            self.assertEqual([item["name"] for item in synthesis["voices"]], ["afrikaans", "English_(Caribbean)", "English_(America)"])

    def test_synthesize_maps_espeak_voice_name_to_language_code(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            engine_path = root / "espeak-ng"
            wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\2" * 20
            engine_path.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import sys\n"
                "if '--voices' in sys.argv:\n"
                "    print('Pty Language Age/Gender VoiceName File Other')\n"
                "    print(' 5  en-029         M  English_(Caribbean)    en')\n"
                "    print(' 5  en-us          M  English_(America)      en')\n"
                "    raise SystemExit(0)\n"
                "voice = sys.argv[sys.argv.index('-v') + 1]\n"
                "if voice != 'en-us':\n"
                "    print(f'unexpected voice: {voice}', file=sys.stderr)\n"
                "    raise SystemExit(2)\n"
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
                    {"action": "synthesize", "text": "Hello world", "voice": "English_(America)"},
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["voice"], "en-us")
            self.assertEqual(base64.b64decode(payload["audio_base64"]), wav_bytes)

    def test_piper_voice_registry_requires_voice_model_mapping_for_multiple_voices(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            piper = root / "piper"
            model_one = root / "voice-one.onnx"
            model_two = root / "voice-two.onnx"
            invocation_log = root / "voices.jsonl"
            model_one.write_bytes(b"one")
            model_two.write_bytes(b"two")
            piper.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "import json\n"
                "import sys\n"
                "model = Path(sys.argv[sys.argv.index('--model') + 1]).name\n"
                "with Path(%r).open('a', encoding='utf-8') as handle:\n"
                "    handle.write(json.dumps({'model': model, 'argv': sys.argv}) + '\\n')\n"
                "Path(sys.argv[sys.argv.index('--output_file') + 1]).write_bytes(b'RIFF' + model.encode('utf-8'))\n" % str(invocation_log),
                encoding="utf-8",
            )
            piper.chmod(piper.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            old_model = os.environ.get("MAVERICK_SPEECH_PIPER_MODEL")
            old_voices = os.environ.get("MAVERICK_SPEECH_PIPER_VOICES_JSON")
            os.environ["PATH"] = f"{root}{os.pathsep}{old_path}"
            os.environ["MAVERICK_SPEECH_PIPER_MODEL"] = str(model_one)
            os.environ["MAVERICK_SPEECH_PIPER_VOICES_JSON"] = json.dumps(
                [
                    {"voice_id": "one", "language": "en", "model": str(model_one)},
                    {"voice_id": "two", "language": "it", "model": str(model_two)},
                ]
            )
            try:
                status_code, payload = handle_action(root / "data", root / "generated", {"action": "set_engine", "synthesis_engine": "piper"})
                status_code, capabilities = handle_action(root / "data", root / "generated", {"action": "capabilities"})
                status_code, speech_one = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "hello", "voice": "one"})
                status_code, speech_two = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "ciao", "voice": "two"})
            finally:
                os.environ["PATH"] = old_path
                if old_model is None:
                    os.environ.pop("MAVERICK_SPEECH_PIPER_MODEL", None)
                else:
                    os.environ["MAVERICK_SPEECH_PIPER_MODEL"] = old_model
                if old_voices is None:
                    os.environ.pop("MAVERICK_SPEECH_PIPER_VOICES_JSON", None)
                else:
                    os.environ["MAVERICK_SPEECH_PIPER_VOICES_JSON"] = old_voices

            self.assertEqual(payload["settings"]["synthesis_engine"], "piper")
            self.assertEqual(status_code, 200)
            self.assertEqual(capabilities["interfaces"]["speech.synthesis"]["default_voice"], "one")
            self.assertEqual([item["voice_id"] for item in capabilities["interfaces"]["speech.synthesis"]["voices"]], ["one", "two"])
            self.assertEqual(speech_one["voice"], "one")
            self.assertEqual(speech_two["voice"], "two")
            invocations = [json.loads(line) for line in invocation_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([item["model"] for item in invocations], ["voice-one.onnx", "voice-two.onnx"])

    def test_piper_reuses_persistent_worker_for_cache_misses(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            piper = bin_dir / "piper"
            piper_invocations = root / "piper-invocations.txt"
            model = root / "voice.onnx"
            load_counter = root / "piper-loads.txt"
            model.write_bytes(b"voice")
            _write_fake_piper_module(root, load_counter)
            piper.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                "Path(%r).write_text('called', encoding='utf-8')\n" % str(piper_invocations),
                encoding="utf-8",
            )
            piper.chmod(piper.stat().st_mode | stat.S_IXUSR)
            old_path = os.environ.get("PATH", "")
            old_pythonpath = os.environ.get("PYTHONPATH")
            old_model = os.environ.get("MAVERICK_SPEECH_PIPER_MODEL")
            old_worker = os.environ.get("MAVERICK_SPEECH_PIPER_WORKER")
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
            os.environ["PYTHONPATH"] = f"{root}{os.pathsep}{old_pythonpath or ''}"
            os.environ["MAVERICK_SPEECH_PIPER_MODEL"] = str(model)
            os.environ["MAVERICK_SPEECH_PIPER_WORKER"] = "persistent"
            try:
                with patch("engines.piper_python_available", return_value=True):
                    first_status, first = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "first chunk"})
                    second_status, second = handle_action(root / "data", root / "generated", {"action": "synthesize", "text": "second chunk"})
            finally:
                engines.stop_piper_workers(root / "data")
                os.environ["PATH"] = old_path
                if old_pythonpath is None:
                    os.environ.pop("PYTHONPATH", None)
                else:
                    os.environ["PYTHONPATH"] = old_pythonpath
                _restore_env("MAVERICK_SPEECH_PIPER_MODEL", old_model)
                _restore_env("MAVERICK_SPEECH_PIPER_WORKER", old_worker)

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(first["engine"], "piper")
            self.assertEqual(second["engine"], "piper")
            self.assertFalse(first["cache_hit"])
            self.assertFalse(second["cache_hit"])
            self.assertEqual(load_counter.read_text(encoding="utf-8"), "1")
            self.assertFalse(piper_invocations.exists())

    def test_piper_worker_prepares_wav_channels_before_synthesis(self) -> None:
        class BarePiperVoice:
            config = {"sample_rate": 16000}

            def synthesize(self, text, wav_file):
                wav_file.writeframes(b"\0\0" * 4)

        audio = tts_worker._synthesize_wav(BarePiperVoice(), "hello")

        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getframerate(), 16000)

    def test_piper_cache_fingerprint_hashes_small_model_content(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "voice.onnx"
            model.write_bytes(b"aaaa")
            engine = LocalEngine(
                name="piper",
                path=str(root / "piper"),
                quality_profile="natural",
                voice_id="voice",
                voices=({"voice_id": "voice", "_model_path": str(model)},),
            )
            first = tts_engine_cache_fingerprint(engine, voice="voice")
            model.write_bytes(b"bbbb")
            second = tts_engine_cache_fingerprint(engine, voice="voice")

            self.assertNotEqual(first["model"]["sha256"], second["model"]["sha256"])

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
            status_code, payload = handle_action(root / "data", root / "generated", {"action": "set_engine", "synthesis_engine": "piper", "transcription_profile": "accurate"})
            self.assertEqual(status_code, 200)
            self.assertEqual(payload["settings"]["synthesis_engine"], "piper")
            self.assertEqual(payload["settings"]["transcription_profile"], "accurate")
            settings_json = (root / "data" / "settings.json").read_text(encoding="utf-8")
            self.assertNotIn("whisper_cpp_model_path", settings_json)
            self.assertEqual(app_events_for_action("set_engine"), [{"type": "maverick.app.data-changed", "resource": "configuration"}])

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
            self.assertEqual(payload["profile"], "")
            self.assertEqual(payload["beam_size"], 0)
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

    def test_transcribe_audio_passes_language_hint_to_engine(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        fake_result = {
            "engine": "faster-whisper",
            "model": "small",
            "language": "it",
            "language_probability": 0.95,
            "duration_seconds": 1.0,
            "segments": [],
            "text": "ciao",
            "profile": "balanced",
            "beam_size": 5,
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("transcription.transcribe_audio_file", return_value=fake_result) as transcribe_audio_file:
                status_code, payload = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {
                        "action": "transcribe_audio",
                        "content_type": "audio/wav",
                        "audio_base64": base64.b64encode(audio).decode("ascii"),
                        "language": "it",
                        "profile": "balanced",
                    },
                )

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["language"], "it")
            self.assertEqual(payload["profile"], "balanced")
            self.assertEqual(payload["beam_size"], 5)
            self.assertEqual(transcribe_audio_file.call_args.kwargs["language"], "it")
            self.assertEqual(transcribe_audio_file.call_args.kwargs["settings"]["transcription_profile"], "balanced")

    def test_transcribe_audio_uses_fast_profile_by_default_without_persisting_setting(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        fake_result = {
            "engine": "faster-whisper",
            "model": "base",
            "language": "it",
            "language_probability": 0.95,
            "duration_seconds": 1.0,
            "segments": [],
            "text": "ciao",
            "profile": "fast",
            "beam_size": 1,
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_settings(root / "data", {"transcription_profile": "balanced"})
            with patch("transcription.transcribe_audio_file", return_value=fake_result) as transcribe_audio_file:
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
            self.assertEqual(payload["profile"], "fast")
            self.assertEqual(payload["beam_size"], 1)
            self.assertEqual(transcribe_audio_file.call_args.kwargs["settings"]["transcription_profile"], "fast")
            self.assertEqual(read_jobs(root / "data")["jobs"][0]["profile"], "fast")
            self.assertEqual((root / "data" / "settings.json").read_text(encoding="utf-8").count("balanced"), 1)

    def test_transcribe_audio_chunks_accumulate_in_temporary_session_with_metrics(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        fake_results = [
            {
                "engine": "faster-whisper",
                "model": "base",
                "language": "it",
                "language_probability": 0.95,
                "duration_seconds": 1.0,
                "segments": [{"start": 0.0, "end": 1.0, "text": " ciao ciao "}],
                "text": " ciao ciao ",
                "profile": "fast",
                "beam_size": 1,
                "worker": {"cold_start": True, "model_load_seconds": 0.25},
            },
            {
                "engine": "faster-whisper",
                "model": "base",
                "language": "it",
                "language_probability": 0.95,
                "duration_seconds": 1.0,
                "segments": [{"start": 0.0, "end": 1.0, "text": " mondo "}],
                "text": " mondo ",
                "profile": "fast",
                "beam_size": 1,
                "worker": {"cold_start": False, "model_load_seconds": 0.0},
            },
        ]
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("transcription.transcribe_audio_file", side_effect=fake_results):
                first_status, first = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {
                        "action": "transcribe_audio",
                        "content_type": "audio/wav",
                        "audio_base64": base64.b64encode(audio).decode("ascii"),
                        "session_id": "chat-session",
                        "chunk_index": 0,
                    },
                )
                second_status, second = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {
                        "action": "transcribe_audio",
                        "content_type": "audio/wav",
                        "audio_base64": base64.b64encode(audio).decode("ascii"),
                        "session_id": "chat-session",
                        "chunk_index": 1,
                        "final": True,
                    },
                )

            self.assertEqual(first_status, 200)
            self.assertEqual(second_status, 200)
            self.assertEqual(first["chunk_text"], "ciao")
            self.assertTrue(first["partial"])
            self.assertEqual(second["text"], "ciao mondo")
            self.assertEqual(second["chunk_index"], 1)
            self.assertTrue(second["final"])
            self.assertGreaterEqual(second["metrics"]["transcription_seconds"], 0.0)
            self.assertEqual(first["metrics"]["model_load_seconds"], 0.25)
            self.assertFalse((root / "data" / "run" / "stt-sessions" / "chat-session.json").exists())
            jobs_json = (root / "data" / "jobs.json").read_text(encoding="utf-8")
            self.assertNotIn("ciao mondo", jobs_json)
            self.assertIn('"realtime_factor"', jobs_json)

    def test_transcribe_audio_binary_upload_uses_spooled_body_file(self) -> None:
        audio = b"not-a-real-webm" * 20
        fake_result = {
            "engine": "faster-whisper",
            "model": "base",
            "language": "it",
            "language_probability": 0.95,
            "duration_seconds": 1.0,
            "segments": [],
            "text": "ciao",
            "profile": "fast",
            "beam_size": 1,
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            body_dir = root / "data" / "run" / "http-body"
            body_dir.mkdir(parents=True)
            body_path = body_dir / "body.bin"
            body_path.write_bytes(audio)

            with patch("transcription.decoded_audio", side_effect=AssertionError("base64 path should not be used")):
                with patch("transcription.probe_audio_duration_seconds", return_value=1.0):
                    with patch("transcription.transcribe_audio_file", return_value=fake_result) as transcribe_audio_file:
                        status_code, payload = handle_action(
                            root / "data",
                            root / "storage" / "generated",
                            {
                                "action": "transcribe_audio",
                                "content_type": "audio/webm",
                                "_body_file_path": str(body_path),
                                "_body_file_size_bytes": len(audio),
                                "language": "it-IT",
                                "profile": "fast",
                            },
                        )

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["text"], "ciao")
            self.assertEqual(transcribe_audio_file.call_args.args[0], body_path)
            self.assertEqual(transcribe_audio_file.call_args.kwargs["language"], "it")
            jobs = read_jobs(root / "data")["jobs"]
            self.assertEqual(jobs[0]["source"], {"kind": "inline", "transport": "binary"})

    def test_app_backend_maps_binary_body_file_to_transcription_body(self) -> None:
        body = app_backend.body_from_payload(
            {
                "query": {"action": "transcribe_audio", "language": "it", "profile": "fast", "session_id": "chat-session", "chunk_index": "2", "final": "true"},
                "body_file": {"path": "/tmp/audio.webm", "content_type": "audio/webm", "size_bytes": 123},
            }
        )

        self.assertEqual(body["action"], "transcribe_audio")
        self.assertEqual(body["content_type"], "audio/webm")
        self.assertEqual(body["language"], "it")
        self.assertEqual(body["profile"], "fast")
        self.assertEqual(body["session_id"], "chat-session")
        self.assertEqual(body["chunk_index"], "2")
        self.assertEqual(body["final"], "true")
        self.assertEqual(body["_body_file_path"], "/tmp/audio.webm")
        self.assertEqual(body["_body_file_size_bytes"], 123)

    def test_transcribe_audio_rejects_unknown_inline_profile(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        with self.assertRaises(SpeechValidationError) as context:
            handle_action(
                Path("data"),
                Path("generated"),
                {
                    "action": "transcribe_audio",
                    "content_type": "audio/wav",
                    "audio_base64": base64.b64encode(audio).decode("ascii"),
                    "profile": "realtime",
                },
            )

        self.assertEqual(context.exception.allowed_values["profile"], ["accurate", "balanced", "fast"])

    def test_transcribe_audio_normalizes_browser_language_hint_for_engine(self) -> None:
        audio = b"RIFF" + b"\0" * 512
        fake_result = {
            "engine": "faster-whisper",
            "model": "small",
            "language": "en",
            "language_probability": 0.99,
            "duration_seconds": 1.0,
            "segments": [],
            "text": "hello",
        }
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("transcription.transcribe_audio_file", return_value=fake_result) as transcribe_audio_file:
                status_code, payload = handle_action(
                    root / "data",
                    root / "storage" / "generated",
                    {
                        "action": "transcribe_audio",
                        "content_type": "audio/wav",
                        "audio_base64": base64.b64encode(audio).decode("ascii"),
                        "language": "en-US",
                    },
                )

            self.assertEqual(status_code, 200)
            self.assertEqual(payload["language"], "en")
            self.assertEqual(transcribe_audio_file.call_args.kwargs["language"], "en")

    def test_transcribe_compressed_audio_requires_ffprobe_for_duration_preflight(self) -> None:
        audio = b"not-a-real-webm" * 20
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("transcription.shutil.which", return_value=None):
                with self.assertRaises(SpeechProviderUnavailableError):
                    handle_action(
                        root / "data",
                        root / "storage" / "generated",
                        {
                            "action": "transcribe_audio",
                            "content_type": "audio/webm",
                            "audio_base64": base64.b64encode(audio).decode("ascii"),
                        },
                    )

    def test_transcribe_audio_rejects_invalid_payloads(self) -> None:
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "transcribe_audio", "content_type": "text/plain", "audio_base64": "abcd"})
        with self.assertRaises(SpeechValidationError):
            handle_action(Path("data"), Path("generated"), {"action": "transcribe_audio", "content_type": "audio/wav", "audio_base64": "not base64"})

    def test_transcribe_audio_inline_payload_uses_json_safe_size_limit(self) -> None:
        audio = b"x" * (MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES + 1)
        with self.assertRaises(SpeechValidationError) as context:
            handle_action(
                Path("data"),
                Path("generated"),
                {
                    "action": "transcribe_audio",
                    "content_type": "audio/wav",
                    "audio_base64": base64.b64encode(audio).decode("ascii"),
                },
            )

        self.assertEqual(context.exception.allowed_values["max_audio_bytes"], [str(MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES)])

    def test_cleaned_transcript_filters_common_hallucinations_without_dropping_short_words(self) -> None:
        self.assertEqual(cleaned_transcript("Thanks for watching."), "")
        self.assertEqual(cleaned_transcript("you"), "you")
        self.assertEqual(cleaned_transcript("hi"), "hi")
        self.assertEqual(cleaned_transcript("hello hello , world"), "hello, world")
        self.assertEqual(cleaned_transcript("nuova riga"), "\n")

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

    def test_job_and_settings_writes_are_atomic_under_concurrency(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "data"

            def write_job(index: int) -> None:
                append_job(root, {"job_id": f"job_{index}", "kind": "test"})
                write_settings(root, {"transcription_profile": "fast" if index % 2 else "balanced"})

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write_job, range(24)))

            jobs = read_jobs(root)["jobs"]
            self.assertEqual(len(jobs), 24)
            self.assertEqual({job["job_id"] for job in jobs}, {f"job_{index}" for index in range(24)})
            settings_json = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            self.assertIn(settings_json["transcription_profile"], {"fast", "balanced"})

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
        self.assertIn("list_engines", cli_payload["operations"])
        self.assertIn("engine_health", cli_payload["operations"])
        self.assertIn("get_settings", cli_payload["operations"])
        self.assertIn("prewarm_worker", cli_payload["operations"])
        self.assertIn("transcribe_file", cli_payload["operations"])
        self.assertIn("worker_status", cli_payload["operations"])
        self.assertNotIn("worker_stop", cli_payload["operations"])
        self.assertNotIn("worker_reload", cli_payload["operations"])
        self.assertIn("transcribe_file", mcp_payload["operations"])
        self.assertNotIn("synthesize", cli_payload["operations"])
        self.assertNotIn("transcribe_audio", cli_payload["operations"])
        self.assertNotIn("transcribe_audio", mcp_payload["operations"])

    def test_cli_read_only_engine_actions_execute_without_audio_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_payload = {
                "workspace_id": "default",
                "app_id": "speech",
                "data_root": str(root / "data"),
                "generated_storage_root": str(root / "storage" / "generated"),
                "uploaded_storage_root": str(root / "storage" / "uploaded"),
            }
            payloads = []
            for action in ("list_engines", "engine_health", "get_settings", "worker_status"):
                result = subprocess.run(
                    [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
                    input=json.dumps({**base_payload, "arguments": {"action": action}}),
                    text=True,
                    capture_output=True,
                    check=True,
                )
                payloads.append(json.loads(result.stdout))

        list_engines, engine_health, get_settings, worker_status = payloads
        self.assertEqual(list_engines["status_code"], 200)
        self.assertIn("synthesis", list_engines)
        self.assertIn("transcription", list_engines)
        self.assertTrue(all("voices" not in item for item in list_engines["synthesis"]))
        self.assertTrue(all("voice_count" in item for item in list_engines["synthesis"]))
        self.assertEqual(engine_health["status_code"], 200)
        self.assertIn(engine_health["status"], {"ok", "partial", "degraded"})
        self.assertIn("speech.synthesis", engine_health["interfaces"])
        self.assertIn("speech.transcription", engine_health["interfaces"])
        self.assertTrue(all("voices" not in item for item in engine_health["synthesis"]))
        self.assertEqual(get_settings["status_code"], 200)
        self.assertEqual(get_settings["settings"]["synthesis_engine"], "auto")
        self.assertEqual(worker_status["status_code"], 200)
        self.assertIn("worker_status", worker_status)

    def test_cli_read_only_engine_actions_can_include_voice_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_payload = {
                "workspace_id": "default",
                "app_id": "speech",
                "data_root": str(root / "data"),
                "generated_storage_root": str(root / "storage" / "generated"),
                "uploaded_storage_root": str(root / "storage" / "uploaded"),
            }
            result = subprocess.run(
                [sys.executable, str(APP_ROOT / "cli" / "app_cli.py")],
                input=json.dumps({**base_payload, "arguments": {"action": "list_engines", "include_voices": True}}),
                text=True,
                capture_output=True,
                check=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status_code"], 200)
        self.assertTrue(all("voices" in item for item in payload["synthesis"]))
        self.assertTrue(all("voice_count" not in item for item in payload["synthesis"]))

    def test_cli_schema_lists_only_supported_operations(self) -> None:
        payload = json.loads((APP_ROOT / "cli" / "command_schemas.json").read_text(encoding="utf-8"))
        properties = payload["commands"]["speech"]["argument_schema"]["properties"]
        actions = properties["action"]["enum"]

        self.assertEqual(
            actions,
            [
                "operations.manifest",
                "list_engines",
                "engine_health",
                "get_settings",
                "worker_status",
                "prewarm_worker",
                "transcribe_file",
            ],
        )
        self.assertEqual(properties["include_voices"]["type"], "boolean")
        self.assertNotIn("synthesize", actions)
        self.assertNotIn("transcribe_audio", actions)


if __name__ == "__main__":
    unittest.main()
