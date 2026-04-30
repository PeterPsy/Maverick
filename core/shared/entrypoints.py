"""Helpers for invoking app entrypoint scripts through a deterministic JSON contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event, Lock
import time
from typing import Any

from core.shared.repository import installation_paths

SENSITIVE_ERROR_MARKERS = ("secret", "token", "password", "authorization", "raw_value")

class EntrypointShutdownController:
    """Track live entrypoint subprocesses so a host can terminate them during shutdown."""

    def __init__(self) -> None:
        self._shutting_down = Event()
        self._lock = Lock()
        self._processes: set[subprocess.Popen[str]] = set()

    def begin_shutdown(self) -> None:
        """Mark shutdown started and terminate registered subprocesses."""
        self._shutting_down.set()
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            _terminate_process_tree(process)

    def is_shutting_down(self) -> bool:
        """Return whether the host has started shutdown."""
        return self._shutting_down.is_set()

    def active_process_count(self) -> int:
        """Return how many entrypoint subprocesses are still registered."""
        with self._lock:
            return len(self._processes)

    def register(self, process: subprocess.Popen[str]) -> None:
        """Track one live subprocess until it exits."""
        with self._lock:
            self._processes.add(process)

    def unregister(self, process: subprocess.Popen[str]) -> None:
        """Stop tracking one subprocess."""
        with self._lock:
            self._processes.discard(process)


def run_json_entrypoint(
    entrypoint_path: str | Path,
    *,
    payload: dict[str, Any],
    cwd: str | Path,
    timeout_seconds: int = 30,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> dict[str, Any]:
    """Invoke one Python entrypoint script with JSON stdin and JSON stdout."""
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
            input_text=json.dumps(payload, ensure_ascii=True),
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


def _communicate_with_limits(
    process: subprocess.Popen[str],
    *,
    input_text: str,
    timeout_seconds: int,
    shutdown_controller: EntrypointShutdownController | None,
    entrypoint_path: str,
) -> tuple[str, str]:
    deadline = time.monotonic() + timeout_seconds
    pending_input: str | None = input_text
    while True:
        if shutdown_controller is not None and shutdown_controller.is_shutting_down():
            _terminate_process_tree_and_wait(process)
            raise RuntimeError(f"Entrypoint `{entrypoint_path}` interrupted by host shutdown.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_tree_and_wait(process)
            raise subprocess.TimeoutExpired(process.args, timeout_seconds)
        try:
            return process.communicate(input=pending_input, timeout=min(0.2, remaining))
        except subprocess.TimeoutExpired as error:
            pending_input = None
            if time.monotonic() >= deadline:
                _terminate_process_tree_and_wait(process)
                raise subprocess.TimeoutExpired(process.args, timeout_seconds, output=error.output, stderr=error.stderr) from error


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
