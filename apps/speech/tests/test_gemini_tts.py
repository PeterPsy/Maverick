from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import SpeechProviderUnavailableError
import gemini_tts
from http_connection_pool import SpeechConnectionPool
from service import capabilities_payload, handle_action
from store import read_jobs, write_settings
from streaming_synthesis import prepare_synthesis_stream
from synthesis import synthesize_payload


def event_bytes(event: dict) -> bytes:
    return b"data: " + json.dumps(event).encode() + b"\r\n\r\n"


def audio_event(audio: bytes) -> dict:
    return {"event_type": "step.delta", "delta": {
        "type": "audio", "mime_type": "audio/l16", "data": base64.b64encode(audio).decode(),
    }}


COMPLETED = {"event_type": "interaction.completed", "interaction": {"status": "completed"}}
SECRETS = {gemini_tts.GEMINI_TTS_SECRET: "test-key-private"}


class FakeResponse:
    status = 200
    will_close = False

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.closed = False
        self.reads = 0

    def getheader(self, _name, _default=""):
        return "text/event-stream; charset=utf-8"

    def read1(self, _size):
        self.reads += 1
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.closed = False

    def request(self, method, path, *, body, headers):
        self.method, self.path, self.body, self.headers = method, path, json.loads(body), headers

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class GeminiTtsTests(unittest.TestCase):
    def test_cli_preflight_requests_only_the_selected_engine_credentials(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            write_settings(root, {"synthesis_engine": "gemini", "transcription_engine": "deepgram"})
            for action, secret, needed in (
                ("probe_synthesis", "google-ai-studio-api-key", True),
                ("probe_synthesis", "deepinfra-api-key", False),
                ("probe_synthesis", "deepgram-api-key", False),
                ("engine_health", "deepgram-api-key", True),
                ("engine_health", "openrouter-api-key", False),
            ):
                with self.subTest(action=action, secret=secret):
                    result = subprocess.run(
                        [sys.executable, str(Path(__file__).resolve().parents[1] / "cli" / "app_cli.py")],
                        input=json.dumps({"surface": "secret_selector", "data_root": str(root), "arguments": {"action": action},
                                          "app_secret_selector": {"logical_names": [secret]}}),
                        text=True, capture_output=True, check=True,
                    )
                    self.assertEqual(json.loads(result.stdout), {"requires_secrets": needed})

    def open_stream(self, chunks):
        response = FakeResponse(chunks)
        connection = FakeConnection(response)
        pool = SpeechConnectionPool(host=gemini_tts.GEMINI_TTS_HOST, connection_factory=lambda *_: connection)
        stream = gemini_tts.open_gemini_stream(
            text="Ciao!", voice="kore", language="it-IT", settings={"_app_secrets": SECRETS}, pool=pool,
        )
        return stream, response, connection, pool

    def test_progressive_pcm_and_complete_connection_reuse(self):
        first = event_bytes(audio_event(b"\x01\x02\x03"))
        stream, response, connection, pool = self.open_stream([
            first[:7], first[7:], event_bytes(audio_event(b"\x04")), event_bytes(COMPLETED), b"data: [DONE]\n\n",
        ])
        chunks = stream.iter_chunks()
        self.assertEqual(next(chunks), b"\x01\x02")
        self.assertEqual(response.reads, 2)  # Plays before the remaining audio or completion arrives.
        self.assertEqual(list(chunks), [b"\x03\x04"])
        self.assertTrue(response.closed)
        self.assertFalse(connection.closed)
        self.assertEqual(pool.acquire(timeout=1), (connection, True))
        self.assertEqual(connection.path, "/v1beta/interactions")
        self.assertEqual(connection.body["model"], gemini_tts.GEMINI_TTS_MODEL)
        self.assertEqual(connection.body["input"][0]["content"][0]["text"], "Ciao!")
        self.assertEqual(connection.body["generation_config"]["speech_config"], [{"voice": "Kore", "language": "it-IT"}])
        self.assertFalse(connection.body["store"])
        self.assertEqual(connection.headers["x-goog-api-key"], SECRETS[gemini_tts.GEMINI_TTS_SECRET])
        self.assertNotIn("test-key-private", json.dumps(connection.body))

    def test_invalid_or_incomplete_stream_discards_connection(self):
        cases = [
            [event_bytes(audio_event(b"\x01\x02"))],
            [event_bytes(COMPLETED)],
            [event_bytes(audio_event(b"\x01")), event_bytes(COMPLETED)],
            [event_bytes({"event_type": "step.delta", "delta": "invalid"})],
            [event_bytes({"event_type": "interaction.completed", "interaction": "invalid"})],
            [event_bytes({"event_type": "error", "message": "test-key-private Ciao!"})],
            [b"data: {invalid}\n\n"],
            [event_bytes(audio_event(b"\x01\x02"))[:-2]],
            [event_bytes({"event_type": "step.delta", "delta": {"type": "audio", "data": "!!"}})],
        ]
        for events in cases:
            with self.subTest(events=events):
                stream, _, connection, _ = self.open_stream(events)
                with self.assertRaises(SpeechProviderUnavailableError) as caught:
                    list(stream.iter_chunks())
                self.assertTrue(connection.closed)
                self.assertNotIn("test-key-private", str(caught.exception))
                self.assertNotIn("Ciao!", str(caught.exception))

    def test_unsupported_pcm_size_limit_and_cancellation(self):
        event = audio_event(b"\x01\x02\x03\x04")
        event["delta"]["mime_type"] = "audio/wav"
        stream, _, connection, _ = self.open_stream([event_bytes(event), event_bytes(COMPLETED)])
        with self.assertRaises(SpeechProviderUnavailableError):
            list(stream.iter_chunks())
        self.assertTrue(connection.closed)
        stream, _, connection, _ = self.open_stream([event_bytes(audio_event(b"\x01\x02\x03\x04")), event_bytes(COMPLETED)])
        with patch.object(gemini_tts, "MAX_AUDIO_BYTES", 2), self.assertRaises(SpeechProviderUnavailableError):
            list(stream.iter_chunks())
        self.assertTrue(connection.closed)
        stream, response, connection, _ = self.open_stream([event_bytes(COMPLETED)])
        stream.close()
        self.assertEqual(list(stream.iter_chunks()), [])
        self.assertEqual(response.reads, 0)
        self.assertTrue(connection.closed)

    def test_streaming_plan_records_completion_and_downstream_cancellation(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), TemporaryDirectory() as temp:
                root = Path(temp)
                write_settings(root, {"synthesis_engine": "gemini", "synthesis_language": "it-it"})
                stream, _, connection, _ = self.open_stream([
                    event_bytes(audio_event(b"\x01\x02")), event_bytes(audio_event(b"\x03\x04")),
                    event_bytes(COMPLETED), b"data: [DONE]\n\n",
                ])
                with patch("streaming_synthesis.open_gemini_stream", return_value=stream) as opened:
                    plan = prepare_synthesis_stream(data_root=root, body={"text": "Testo riservato", "_app_secrets": SECRETS})
                self.assertEqual(opened.call_args.kwargs["voice"], "Kore")
                self.assertEqual(plan.stream_response["audio"], {"sample_rate": 24000, "channels": 1, "sample_format": "s16le"})
                chunks = plan.iter_chunks()
                self.assertEqual(next(chunks), b"\x01\x02")
                if cancel:
                    plan.cancel()
                self.assertEqual(b"".join(chunks), b"" if cancel else b"\x03\x04")
                job = read_jobs(root)["jobs"][0]
                self.assertEqual(job["engine"], "gemini")
                self.assertEqual(job["stream_completed"], not cancel)
                self.assertEqual(connection.closed, cancel)
                self.assertNotIn("Testo riservato", json.dumps(job))
                self.assertNotIn("test-key-private", json.dumps(job))

    def test_buffered_wav_capabilities_and_probe_do_not_persist_audio_or_key(self):
        with TemporaryDirectory() as temp:
            data_root, generated_root = Path(temp) / "data", Path(temp) / "generated"
            write_settings(data_root, {"synthesis_engine": "gemini", "synthesis_language": "it-it"})
            stream, _, _, _ = self.open_stream([event_bytes(audio_event(b"\x01\x02" * 2400)), event_bytes(COMPLETED), b"data: [DONE]\n\n"])
            with patch.object(gemini_tts, "open_gemini_stream", return_value=stream):
                result = synthesize_payload(data_root=data_root, generated_storage_root=generated_root, body={"text": "Ciao!", "_app_secrets": SECRETS})
            with wave.open(io.BytesIO(base64.b64decode(result["audio_base64"]))) as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 24000))
            self.assertEqual(result["voice"], "Kore")
            self.assertFalse(result["cache"]["enabled"])
            self.assertNotIn("Ciao!", json.dumps(read_jobs(data_root)))
            self.assertNotIn("test-key-private", json.dumps(read_jobs(data_root)))
            self.assertFalse(generated_root.exists())
            capabilities = capabilities_payload(data_root, app_secrets=SECRETS)
            self.assertEqual(capabilities["interfaces"]["speech.synthesis"]["engine"], "gemini")
            self.assertTrue(capabilities["interfaces"]["speech.synthesis"]["streaming_supported"])
            with patch("synthesis_probe.synthesize_payload", return_value=result):
                status, probe = handle_action(data_root, generated_root, {"action": "probe_synthesis", "_app_secrets": SECRETS})
            self.assertEqual(status, 200)
            self.assertEqual(probe["probe"]["engine"], "gemini")
            self.assertNotIn("audio_base64", probe["probe"])
            self.assertNotIn("text", probe["probe"])
            self.assertNotIn("test-key-private", json.dumps(probe))
