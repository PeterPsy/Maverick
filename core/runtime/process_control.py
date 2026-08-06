"""In-process control for live provider subprocesses."""

from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
import signal
import subprocess
from threading import Lock
import time


_LOCK = Lock()
_PROCESSES_BY_SESSION: dict[str, set[subprocess.Popen]] = defaultdict(set)
RUNTIME_PROVIDER_OOM_SCORE_ADJ = 0


def configure_runtime_process_oom_score(
    process: subprocess.Popen,
    *,
    proc_root: str | Path = "/proc",
) -> bool:
    """Keep a provider at neutral Linux OOM priority.

    The systemd-hosted core uses a negative ``OOMScoreAdjust`` so the platform
    control plane survives memory pressure. Provider processes are reset to a
    neutral score instead of receiving a positive adjustment that would make
    every active session an early-OOM victim. Provider descendants inherit the
    neutral value. The operation is best-effort so unsupported hosts or
    restricted procfs mounts do not prevent a turn from starting.
    """
    try:
        pid = int(process.pid)
    except (AttributeError, TypeError, ValueError):
        return False
    if pid <= 1:
        return False
    score_path = Path(proc_root) / str(pid) / "oom_score_adj"
    try:
        score_path.write_text(f"{RUNTIME_PROVIDER_OOM_SCORE_ADJ}\n", encoding="ascii")
    except OSError:
        return False
    return True


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
        if terminate_runtime_process(process, timeout_seconds=timeout_seconds):
            terminated += 1
        unregister_runtime_process(session_id, process)
    return terminated


def terminate_runtime_process(process: subprocess.Popen, *, timeout_seconds: float = 1.5) -> bool:
    """Terminate one provider subprocess and its process group."""
    if process.poll() is not None:
        return False
    _terminate_process_tree(process)
    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        _kill_process_tree(process)
    return True


def terminate_codex_app_server_processes_for_session(session_id: str, *, timeout_seconds: float = 1.5) -> int:
    """Best-effort fallback for Codex app-server processes lost from the in-memory registry."""
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return 0
    terminated = 0
    for name in os.listdir(proc_root):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            if not _proc_matches_codex_app_server_session(pid, session_id):
                continue
            if _terminate_process_group_pid(pid, timeout_seconds=timeout_seconds):
                terminated += 1
        except ProcessLookupError:
            continue
        except Exception:
            continue
    return terminated


def _proc_matches_codex_app_server_session(pid: int, session_id: str) -> bool:
    base = f"/proc/{pid}"
    with open(f"{base}/environ", "rb") as handle:
        environ = handle.read().split(b"\0")
    if f"MAVERICK_RUNTIME_SESSION_ID={session_id}".encode() not in environ:
        return False
    with open(f"{base}/cmdline", "rb") as handle:
        cmdline = handle.read().decode("utf-8", errors="ignore").replace("\0", " ")
    return "codex" in cmdline and "app-server" in cmdline and "--listen" in cmdline


def _terminate_process_group_pid(pid: int, *, timeout_seconds: float) -> bool:
    if not _pid_exists(pid):
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while _pid_exists(pid) and time.monotonic() < deadline:
        if _try_reap_pid(pid):
            return True
        time.sleep(0.05)
    if _pid_exists(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            os.kill(pid, signal.SIGKILL)
    _try_reap_pid(pid)
    return True


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _try_reap_pid(pid: int) -> bool:
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return not _pid_exists(pid)
    except ProcessLookupError:
        return True
    return waited == pid


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
