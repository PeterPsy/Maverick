from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(APP_ROOT / "scripts"))

import backend_worker
import benchmark_kokoro
import kokoro_streaming
from store import read_jobs, write_settings
import streaming_synthesis


class KokoroStreamingTestCase(unittest.TestCase):
    def test_benchmark_matrix_covers_lengths_formats_and_connection_modes(self) -> None:
        cases = benchmark_kokoro.benchmark_cases(
            lengths=[40, 120],
            formats=["mp3", "pcm"],
            connection_modes=["fresh", "pooled"],
        )

        self.assertEqual(len(cases), 8)
        self.assertEqual(len(benchmark_kokoro.benchmark_text(120)), 120)
        self.assertIn({"text_chars": 40, "format": "pcm", "connection_mode": "pooled"}, cases)

    def test_pcm_stream_reuses_the_persistent_https_connection(self) -> None:
        class FakeResponse:
            status = 200
            reason = "OK"
            will_close = False

            def __init__(self, generation_id: str) -> None:
                self.generation_id = generation_id
                self.payload = bytearray(b"\x01\x02\x03\x04")
                self.closed = False

            def getheader(self, name: str, default: str = "") -> str:
                if name.lower() == "x-generation-id":
                    return self.generation_id
                if name.lower() == "content-type":
                    return "audio/pcm"
                return default

            def read(self, size: int = -1) -> bytes:
                if size < 0:
                    size = len(self.payload)
                result = bytes(self.payload[:size])
                del self.payload[:size]
                return result

            def read1(self, size: int = -1) -> bytes:
                return self.read(size)

            def close(self) -> None:
                self.closed = True

        class FakeConnection:
            def __init__(self) -> None:
                self.connect_count = 0
                self.request_bodies: list[dict] = []
                self.response_count = 0
                self.closed = False

            def connect(self) -> None:
                self.connect_count += 1

            def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
                self.request_bodies.append(json.loads(body.decode("utf-8")))
                self.method = method
                self.path = path
                self.headers = headers

            def getresponse(self) -> FakeResponse:
                self.response_count += 1
                return FakeResponse(f"gen_{self.response_count}")

            def close(self) -> None:
                self.closed = True

        connection = FakeConnection()
        pool = kokoro_streaming.KokoroConnectionPool(connection_factory=lambda _host, _timeout: connection)
        settings = {"_app_secrets": {"openrouter-api-key": "openrouter-token"}}

        first = kokoro_streaming.open_kokoro_openrouter_stream(
            text="hello",
            voice="af_heart",
            settings=settings,
            pool=pool,
        )
        first_audio = b"".join(first.iter_chunks())
        second = kokoro_streaming.open_kokoro_openrouter_stream(
            text="again",
            voice="af_heart",
            settings=settings,
            pool=pool,
        )
        second_audio = b"".join(second.iter_chunks())

        self.assertEqual(first_audio, b"\x01\x02\x03\x04")
        self.assertEqual(second_audio, b"\x01\x02\x03\x04")
        self.assertEqual(first.generation_id, "gen_1")
        self.assertEqual(second.generation_id, "gen_2")
        self.assertFalse(first.connection_reused)
        self.assertTrue(second.connection_reused)
        self.assertEqual(connection.connect_count, 1)
        self.assertEqual(connection.response_count, 2)
        self.assertEqual(connection.request_bodies[0]["response_format"], "pcm")
        self.assertEqual(connection.headers["Authorization"], "Bearer openrouter-token")
        self.assertGreaterEqual(first.timings["upstream_first_audio_byte_ms"], first.timings["upstream_headers_ms"])

    def test_streaming_synthesis_records_generation_and_upstream_phase_metrics(self) -> None:
        class FakeUpstream:
            generation_id = "gen_job_123"
            connection_reused = True
            timings = {
                "upstream_connect_ms": 0.0,
                "upstream_headers_ms": 72.5,
                "upstream_first_audio_byte_ms": 91.25,
            }

            def iter_chunks(self):
                yield b"\x00\x01"
                yield b"\x02\x03"
                self.timings["upstream_last_audio_byte_ms"] = 123.5

        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            write_settings(data_root, {"synthesis_engine": "kokoro-openrouter"})
            with patch("streaming_synthesis.open_kokoro_openrouter_stream", return_value=FakeUpstream()):
                plan = streaming_synthesis.prepare_synthesis_stream(
                    data_root=data_root,
                    body={
                        "action": "synthesize",
                        "text": "Ciao, questa parte subito.",
                        "language": "it",
                        "_backend_entrypoint_ms": 84.5,
                        "_app_secrets": {"openrouter-api-key": "openrouter-token"},
                    },
                )
                audio = b"".join(plan.iter_chunks())
            jobs = read_jobs(data_root)["jobs"]

        self.assertEqual(audio, b"\x00\x01\x02\x03")
        self.assertEqual(plan.stream_response["content_type"], "audio/pcm")
        self.assertEqual(plan.stream_response["generation_id"], "gen_job_123")
        self.assertEqual(plan.stream_response["audio"], {"sample_rate": 24000, "channels": 1, "sample_format": "s16le"})
        self.assertEqual(plan.stream_response["timings"]["backend_entrypoint_ms"], 84.5)
        self.assertEqual(jobs[0]["generation_id"], "gen_job_123")
        self.assertEqual(jobs[0]["size_bytes"], 4)
        self.assertEqual(jobs[0]["upstream_first_audio_byte_ms"], 91.25)
        self.assertIn("upstream_last_audio_byte_ms", jobs[0])
        self.assertTrue(jobs[0]["stream_completed"])

    def test_backend_worker_writes_stream_header_before_pcm_bytes(self) -> None:
        class FakePlan:
            stream_response = {
                "content_type": "audio/pcm",
                "generation_id": "gen_socket",
                "audio": {"sample_rate": 24000, "channels": 1, "sample_format": "s16le"},
            }

            def iter_chunks(self):
                yield b"pcm-one"
                yield b"pcm-two"

        server, client = socket.socketpair()
        try:
            with patch("backend_worker.prepare_synthesis_stream", return_value=FakePlan()):
                backend_worker.send_streaming_payload(
                    server,
                    {
                        "data_root": "/tmp/speech-data",
                        "body": {"action": "synthesize", "text": "hello", "response_mode": "stream"},
                    },
                )
            server.shutdown(socket.SHUT_WR)
            received = bytearray()
            while True:
                chunk = client.recv(1024)
                if not chunk:
                    break
                received.extend(chunk)
        finally:
            server.close()
            client.close()

        header_bytes, audio = bytes(received).split(b"\n", 1)
        header = json.loads(header_bytes.decode("utf-8"))
        self.assertEqual(header["status_code"], 200)
        self.assertEqual(header["stream_response"]["generation_id"], "gen_socket")
        self.assertEqual(audio, b"pcm-onepcm-two")


if __name__ == "__main__":
    unittest.main()
