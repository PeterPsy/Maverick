"""Helpers for invoking app entrypoint scripts through a deterministic JSON contract."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import selectors
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Event, Lock
import time
from typing import Any

from core.shared.repository import installation_paths

SENSITIVE_ERROR_MARKERS = ("secret", "token", "password", "authorization", "raw_value")
STREAMING_ENTRYPOINT_HEADER_MAX_BYTES = 1024 * 1024

class EntrypointShutdownController:
    """Track live entrypoint subprocesses so a host can terminate them during shutdown."""

    def __init__(self, *, parent: EntrypointShutdownController | None = None) -> None:
        self._shutting_down = Event()
        self._lock = Lock()
        self._processes: set[subprocess.Popen[str]] = set()
        self._parent = parent

    def begin_shutdown(self) -> None:
        """Mark shutdown started and terminate registered subprocesses."""
        self._shutting_down.set()
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            _terminate_process_tree(process)

    def is_shutting_down(self) -> bool:
        """Return whether the host has started shutdown."""
        return self._shutting_down.is_set() or bool(self._parent and self._parent.is_shutting_down())

    def active_process_count(self) -> int:
        """Return how many entrypoint subprocesses are still registered."""
        with self._lock:
            return len(self._processes)

    def register(self, process: subprocess.Popen[str]) -> None:
        """Track one live subprocess until it exits."""
        with self._lock:
            self._processes.add(process)
        if self._parent is not None:
            self._parent.register(process)
        if self._shutting_down.is_set():
            _terminate_process_tree(process)

    def unregister(self, process: subprocess.Popen[str]) -> None:
        """Stop tracking one subprocess."""
        with self._lock:
            self._processes.discard(process)
        if self._parent is not None:
            self._parent.unregister(process)


@dataclass
class StreamingJsonEntrypointResult:
    """A backend entrypoint result whose stdout may continue as a binary stream."""

    result: dict[str, Any]
    process: subprocess.Popen[bytes] | None = None
    stdout_prefix: bytes = b""
    stderr_file: Any | None = None
    shutdown_controller: EntrypointShutdownController | None = None
    entrypoint_path: str = ""
    _closed: bool = False
    _close_lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def has_stream(self) -> bool:
        return self.process is not None

    def iter_stream(self, *, chunk_bytes: int):
        """Return an iterator that forwards each available stdout chunk immediately."""
        return _StreamingEntrypointIterator(self, chunk_bytes=chunk_bytes)

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            process = self.process
            if process is not None and process.poll() is None:
                _terminate_process_tree(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if self.shutdown_controller is not None and process is not None:
                self.shutdown_controller.unregister(process)  # type: ignore[arg-type]
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if self.stderr_file is not None:
                self.stderr_file.close()

    def _wait_for_exit(self) -> None:
        process = self.process
        if process is None:
            return
        returncode = process.wait()
        if self.shutdown_controller is not None:
            self.shutdown_controller.unregister(process)  # type: ignore[arg-type]
        if returncode != 0:
            stderr = _read_stderr_file(self.stderr_file)
            if self.shutdown_controller is not None and self.shutdown_controller.is_shutting_down():
                raise RuntimeError(f"Entrypoint `{self.entrypoint_path}` interrupted by host shutdown.")
            raise RuntimeError(
                f"Entrypoint `{self.entrypoint_path}` failed with exit code {returncode}: "
                f"{redact_entrypoint_stderr(stderr) or 'no stderr'}"
            )


class _StreamingEntrypointIterator:
    """Read one available pipe buffer at a time and support concurrent cancellation."""

    def __init__(self, result: StreamingJsonEntrypointResult, *, chunk_bytes: int) -> None:
        if chunk_bytes <= 0:
            raise ValueError("Streaming entrypoint chunk size must be positive.")
        self._result = result
        self._chunk_bytes = chunk_bytes
        self._finished = False

    def __iter__(self) -> _StreamingEntrypointIterator:
        return self

    def __next__(self) -> bytes:
        if self._finished:
            raise StopIteration
        if self._result.stdout_prefix:
            chunk = self._result.stdout_prefix
            self._result.stdout_prefix = b""
            return chunk
        process = self._result.process
        stdout = None if process is None else process.stdout
        if stdout is None:
            self.close()
            raise StopIteration
        read_available = getattr(stdout, "read1", stdout.read)
        chunk = read_available(self._chunk_bytes)
        if chunk:
            return chunk
        self._finished = True
        try:
            self._result._wait_for_exit()
        finally:
            self._result.close()
        raise StopIteration

    def close(self) -> None:
        if self._finished and self._result._closed:
            return
        self._finished = True
        self._result.close()


def run_json_entrypoint(
    entrypoint_path: str | Path,
    *,
    payload: dict[str, Any],
    cwd: str | Path,
    timeout_seconds: int | float = 30,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> dict[str, Any]:
    """Invoke one Python entrypoint script with JSON stdin and JSON stdout."""
    input_text = json.dumps(payload, ensure_ascii=True)
    repository_root = str(installation_paths(start_path=Path(cwd)).repository_root)
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        repository_root
        if not env.get("PYTHONPATH")
        else f"{repository_root}{os.pathsep}{env['PYTHONPATH']}"
    )
    process = subprocess.Popen(
        [sys.executable, str(entrypoint_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        text=True,
        start_new_session=True,
    )
    if shutdown_controller is not None:
        shutdown_controller.register(process)
    try:
        stdout, stderr = _communicate_with_limits(
            process,
            input_text=input_text,
            timeout_seconds=timeout_seconds,
            shutdown_controller=shutdown_controller,
            entrypoint_path=str(entrypoint_path),
        )
    finally:
        if shutdown_controller is not None:
            shutdown_controller.unregister(process)
    if process.returncode != 0:
        if shutdown_controller is not None and shutdown_controller.is_shutting_down():
            raise RuntimeError(f"Entrypoint `{entrypoint_path}` interrupted by host shutdown.")
        stderr_text = redact_entrypoint_stderr(stderr or "")
        raise RuntimeError(
            f"Entrypoint `{entrypoint_path}` failed with exit code {process.returncode}: {stderr_text or 'no stderr'}"
        )
    try:
        result = json.loads(stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not emit valid JSON.") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not emit a JSON object.")
    return result


def run_streaming_json_entrypoint(
    entrypoint_path: str | Path,
    *,
    payload: dict[str, Any],
    cwd: str | Path,
    timeout_seconds: int | float = 30,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> StreamingJsonEntrypointResult:
    """Invoke an entrypoint that emits one JSON header line, optionally followed by bytes."""
    input_bytes = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    repository_root = str(installation_paths(start_path=Path(cwd)).repository_root)
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        repository_root
        if not env.get("PYTHONPATH")
        else f"{repository_root}{os.pathsep}{env['PYTHONPATH']}"
    )
    stderr_file = tempfile.TemporaryFile(mode="w+b")
    process = subprocess.Popen(
        [sys.executable, str(entrypoint_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr_file,
        cwd=str(cwd),
        env=env,
        text=False,
        start_new_session=True,
    )
    if shutdown_controller is not None:
        shutdown_controller.register(process)  # type: ignore[arg-type]
    try:
        assert process.stdin is not None
        process.stdin.write(input_bytes)
        process.stdin.close()
        header, stdout_prefix = _read_streaming_json_header(
            process,
            timeout_seconds=timeout_seconds,
            shutdown_controller=shutdown_controller,
            entrypoint_path=str(entrypoint_path),
            stderr_file=stderr_file,
        )
        try:
            result = json.loads(header.decode("utf-8") or "{}")
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not emit a valid JSON stream header.") from error
        if not isinstance(result, dict):
            raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not emit a JSON object stream header.")
        if isinstance(result.get("stream_response"), dict):
            return StreamingJsonEntrypointResult(
                result=result,
                process=process,
                stdout_prefix=stdout_prefix,
                stderr_file=stderr_file,
                shutdown_controller=shutdown_controller,
                entrypoint_path=str(entrypoint_path),
            )
        remaining_stdout = stdout_prefix + (process.stdout.read() if process.stdout is not None else b"")
        returncode = process.wait()
        if shutdown_controller is not None:
            shutdown_controller.unregister(process)  # type: ignore[arg-type]
        stderr = _read_stderr_file(stderr_file)
        if process.stdout is not None:
            process.stdout.close()
        stderr_file.close()
        if returncode != 0:
            if shutdown_controller is not None and shutdown_controller.is_shutting_down():
                raise RuntimeError(f"Entrypoint `{entrypoint_path}` interrupted by host shutdown.")
            raise RuntimeError(
                f"Entrypoint `{entrypoint_path}` failed with exit code {returncode}: "
                f"{redact_entrypoint_stderr(stderr) or 'no stderr'}"
            )
        if remaining_stdout.strip():
            raise RuntimeError(f"Entrypoint `{entrypoint_path}` emitted extra stdout after its JSON response.")
        return StreamingJsonEntrypointResult(result=result)
    except Exception:
        if process.poll() is None:
            _terminate_process_tree(process)
        if shutdown_controller is not None:
            shutdown_controller.unregister(process)  # type: ignore[arg-type]
        stderr_file.close()
        raise


def redact_entrypoint_stderr(stderr: str, *, max_chars: int = 500) -> str:
    """Return bounded, public-safe stderr text for app entrypoint failures."""
    text = (stderr or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_ERROR_MARKERS):
        return "[redacted entrypoint stderr]"
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _read_streaming_json_header(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int | float,
    shutdown_controller: EntrypointShutdownController | None,
    entrypoint_path: str,
    stderr_file: Any,
) -> tuple[bytes, bytes]:
    if process.stdout is None:
        raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not expose stdout.")
    fd = process.stdout.fileno()
    deadline = time.monotonic() + timeout_seconds
    buffer = bytearray()
    selector = selectors.DefaultSelector()
    os.set_blocking(fd, False)
    selector.register(fd, selectors.EVENT_READ)
    try:
        while True:
            newline_index = buffer.find(b"\n")
            if newline_index >= 0:
                os.set_blocking(fd, True)
                return bytes(buffer[:newline_index]), bytes(buffer[newline_index + 1 :])
            if len(buffer) > STREAMING_ENTRYPOINT_HEADER_MAX_BYTES:
                _terminate_process_tree(process)
                raise RuntimeError(f"Entrypoint `{entrypoint_path}` stream header exceeded the size limit.")
            if shutdown_controller is not None and shutdown_controller.is_shutting_down():
                _terminate_process_tree_and_wait(process)  # type: ignore[arg-type]
                raise RuntimeError(f"Entrypoint `{entrypoint_path}` interrupted by host shutdown.")
            if process.poll() is not None:
                try:
                    while True:
                        chunk = os.read(fd, 65536)
                        if not chunk:
                            break
                        buffer.extend(chunk)
                except BlockingIOError:
                    pass
                if buffer:
                    os.set_blocking(fd, True)
                    return bytes(buffer), b""
                stderr = _read_stderr_file(stderr_file)
                raise RuntimeError(
                    f"Entrypoint `{entrypoint_path}` failed before emitting a stream header: "
                    f"{redact_entrypoint_stderr(stderr) or 'no stderr'}"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree_and_wait(process)  # type: ignore[arg-type]
                raise subprocess.TimeoutExpired(process.args, timeout_seconds)
            events = selector.select(remaining)
            if not events:
                continue
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                if buffer:
                    os.set_blocking(fd, True)
                    return bytes(buffer), b""
                continue
            buffer.extend(chunk)
    finally:
        selector.close()


def _read_stderr_file(stderr_file: Any | None) -> str:
    if stderr_file is None:
        return ""
    try:
        stderr_file.flush()
        stderr_file.seek(0)
        return stderr_file.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _communicate_with_limits(
    process: subprocess.Popen[str],
    *,
    input_text: str,
    timeout_seconds: int | float,
    shutdown_controller: EntrypointShutdownController | None,
    entrypoint_path: str,
) -> tuple[str, str]:
    try:
        return process.communicate(input=input_text, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_process_tree_and_wait(process)
        if shutdown_controller is not None and shutdown_controller.is_shutting_down():
            raise RuntimeError(f"Entrypoint `{entrypoint_path}` interrupted by host shutdown.") from error
        raise


def _terminate_process_tree_and_wait(process: subprocess.Popen[str], *, timeout_seconds: float = 1.0) -> None:
    if process.poll() is not None:
        return
    _terminate_process_tree(process)
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except Exception:
        process.terminate()


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        process.kill()
