from __future__ import annotations

from pathlib import Path
import queue
import subprocess
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

from core.shared.entrypoints import (
    EntrypointInterruptedError,
    EntrypointShutdownController,
    StreamingJsonEntrypointResult,
    redact_entrypoint_stderr,
    run_json_entrypoint,
    run_streaming_json_entrypoint,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class SharedEntrypointTests(unittest.TestCase):
    def test_timeout_kills_descendants_that_ignore_sigterm(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            child_pid = temp_root / "child.pid"
            entrypoint = temp_root / "tree_entrypoint.py"
            child_source = (
                "import os, pathlib, signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid())); "
                "time.sleep(30)"
            )
            entrypoint.write_text(
                "\n".join(
                    [
                        "import subprocess, sys, time",
                        f"subprocess.Popen([sys.executable, '-c', {child_source!r}])",
                        "time.sleep(30)",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(subprocess.TimeoutExpired):
                run_json_entrypoint(entrypoint, payload={}, cwd=REPO_ROOT, timeout_seconds=1)

            self.assertTrue(child_pid.is_file())
            pid = int(child_pid.read_text(encoding="utf-8"))
            deadline = time.time() + 2
            while Path(f"/proc/{pid}").exists() and time.time() < deadline:
                time.sleep(0.05)
            self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_shutdown_controller_runs_registered_cleanup_once(self) -> None:
        controller = EntrypointShutdownController()
        calls: list[str] = []
        controller.register_cleanup(lambda: calls.append("cleanup"))

        controller.begin_shutdown()
        controller.begin_shutdown()

        self.assertEqual(calls, ["cleanup"])

    def test_nested_shutdown_controller_reports_the_initiating_reason(self) -> None:
        host = EntrypointShutdownController()
        request = EntrypointShutdownController(parent=host, interruption_reason="client disconnect")

        request.begin_shutdown()

        self.assertEqual(request.interruption_reason(), "client disconnect")
        self.assertIsNone(host.interruption_reason())

        inherited = EntrypointShutdownController(parent=host, interruption_reason="client disconnect")
        host.begin_shutdown()
        self.assertEqual(inherited.interruption_reason(), "host shutdown")

    def test_entrypoint_stderr_redaction_hides_secret_material(self) -> None:
        self.assertEqual(
            redact_entrypoint_stderr("raw_value=super-secret-token"),
            "[redacted entrypoint stderr]",
        )
        self.assertEqual(
            redact_entrypoint_stderr("capability=opaque-value broker_socket=/tmp/private.sock"),
            "[redacted entrypoint stderr]",
        )

    def test_streaming_result_runs_owner_cleanup_once(self) -> None:
        calls: list[str] = []
        result = StreamingJsonEntrypointResult(result={})
        result.add_cleanup(lambda: calls.append("closed"))

        result.close()
        result.close()

        self.assertEqual(calls, ["closed"])

    def test_json_entrypoint_rejects_non_json_payload_before_launch(self) -> None:
        with patch("core.shared.entrypoints.subprocess.Popen") as popen:
            with self.assertRaises(TypeError):
                run_json_entrypoint(
                    Path("/tmp/not-launched.py"),
                    payload={"bad": object()},
                    cwd=REPO_ROOT,
                    timeout_seconds=5,
                )

        popen.assert_not_called()

    def test_streaming_json_entrypoint_rejects_non_json_payload_before_launch(self) -> None:
        with patch("core.shared.entrypoints.subprocess.Popen") as popen:
            with self.assertRaises(TypeError):
                run_streaming_json_entrypoint(
                    Path("/tmp/not-launched.py"),
                    payload={"bad": object()},
                    cwd=REPO_ROOT,
                    timeout_seconds=5,
                )

        popen.assert_not_called()

    def test_shutdown_controller_interrupts_live_entrypoint_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            entrypoint = temp_root / "slow_entrypoint.py"
            entrypoint.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "import time",
                        "",
                        "json.loads(sys.stdin.read() or '{}')",
                        "time.sleep(30)",
                        "print('{\"status\": \"ok\"}')",
                    ]
                ),
                encoding="utf-8",
            )
            controller = EntrypointShutdownController()
            failures: queue.Queue[BaseException] = queue.Queue()

            def target() -> None:
                try:
                    run_json_entrypoint(
                        entrypoint,
                        payload={"action": "sleep"},
                        cwd=REPO_ROOT,
                        timeout_seconds=30,
                        shutdown_controller=controller,
                    )
                except BaseException as error:
                    failures.put(error)

            worker = Thread(target=target)
            worker.start()

            deadline = time.time() + 5
            while controller.active_process_count() == 0 and time.time() < deadline:
                time.sleep(0.05)

            self.assertGreater(controller.active_process_count(), 0)

            controller.begin_shutdown()
            worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            error = failures.get_nowait()
            self.assertIsInstance(error, EntrypointInterruptedError)
            self.assertEqual(error.reason, "host shutdown")
            self.assertIn("host shutdown", str(error))

    def test_json_entrypoint_delivers_stdin_when_child_reads_after_initial_wait(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            entrypoint = Path(temp_dir) / "delayed_stdin_entrypoint.py"
            entrypoint.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "import time",
                        "",
                        "time.sleep(0.4)",
                        "payload = json.loads(sys.stdin.read() or '{}')",
                        "print(json.dumps({'status': 'ok', 'action': payload.get('action')}))",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_json_entrypoint(
                entrypoint,
                payload={"action": "delayed-read"},
                cwd=REPO_ROOT,
                timeout_seconds=5,
            )

        self.assertEqual(result, {"status": "ok", "action": "delayed-read"})

    def test_streaming_json_entrypoint_yields_header_then_binary_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            entrypoint = Path(temp_dir) / "stream_entrypoint.py"
            entrypoint.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "",
                        "json.loads(sys.stdin.read() or '{}')",
                        "sys.stdout.buffer.write(json.dumps({'status_code': 200, 'stream_response': {'content_type': 'video/mp4', 'content_length': 6}}).encode('utf-8') + b'\\n')",
                        "sys.stdout.buffer.flush()",
                        "sys.stdout.buffer.write(b'abc')",
                        "sys.stdout.buffer.flush()",
                        "sys.stdout.buffer.write(b'def')",
                        "sys.stdout.buffer.flush()",
                    ]
                ),
                encoding="utf-8",
            )

            result = run_streaming_json_entrypoint(
                entrypoint,
                payload={"action": "stream"},
                cwd=REPO_ROOT,
                timeout_seconds=5,
            )
            body = b"".join(result.iter_stream(chunk_bytes=2))

        self.assertEqual(result.result["status_code"], 200)
        self.assertEqual(result.result["stream_response"]["content_length"], 6)
        self.assertEqual(body, b"abcdef")

    def test_streaming_iterator_reads_available_pipe_bytes_without_filling_requested_chunk(self) -> None:
        class FakeStdout:
            def __init__(self) -> None:
                self.chunks = [b"first", b"second", b""]
                self.read1_sizes: list[int] = []
                self.closed = False

            def read1(self, size: int) -> bytes:
                self.read1_sizes.append(size)
                return self.chunks.pop(0)

            def read(self, _size: int) -> bytes:
                raise AssertionError("Buffered read would wait to fill the requested chunk.")

            def close(self) -> None:
                self.closed = True

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout()

            def poll(self) -> int:
                return 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

        process = FakeProcess()
        result = StreamingJsonEntrypointResult(result={"stream_response": {}}, process=process)  # type: ignore[arg-type]

        body = b"".join(result.iter_stream(chunk_bytes=1024 * 1024))

        self.assertEqual(body, b"firstsecond")
        self.assertEqual(process.stdout.read1_sizes, [1024 * 1024, 1024 * 1024, 1024 * 1024])
        self.assertTrue(process.stdout.closed)


if __name__ == "__main__":
    unittest.main()
