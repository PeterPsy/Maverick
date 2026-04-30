"""In-process control for live provider subprocesses."""

from __future__ import annotations

from collections import defaultdict
import os
import signal
import subprocess
from threading import Lock
import time


_LOCK = Lock()
_PROCESSES_BY_SESSION: dict[str, set[subprocess.Popen]] = defaultdict(set)


def register_runtime_process(session_id: str, process: subprocess.Popen) -> None:
    """Register one live provider subprocess for session-level termination."""
    with _LOCK:
        _PROCESSES_BY_SESSION[session_id].add(process)


def unregister_runtime_process(session_id: str, process: subprocess.Popen) -> None:
    """Remove one provider subprocess from the live registry."""
    with _LOCK:
        processes = _PROCESSES_BY_SESSION.get(session_id)
        if not processes:
            return
        processes.discard(process)
        if not processes:
            _PROCESSES_BY_SESSION.pop(session_id, None)


def terminate_runtime_processes(session_id: str, *, timeout_seconds: float = 1.5) -> int:
    """Terminate all live provider subprocesses for one runtime session."""
    with _LOCK:
        processes = list(_PROCESSES_BY_SESSION.get(session_id, set()))

    terminated = 0
    for process in processes:
        if process.poll() is not None:
            unregister_runtime_process(session_id, process)
            continue
        _terminate_process_tree(process)
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if process.poll() is None:
            _kill_process_tree(process)
        terminated += 1
        unregister_runtime_process(session_id, process)
    return terminated


def _terminate_process_tree(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except Exception:
        process.terminate()


def _kill_process_tree(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except Exception:
        process.kill()
