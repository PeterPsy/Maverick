"""Bounded process, runtime-session, and host-memory safety for OpenDesign builds."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable, Iterator, TextIO


GIBIBYTE = 1024**3
START_AVAILABLE_BYTES = 4 * GIBIBYTE
STOP_AVAILABLE_BYTES = int(2.5 * GIBIBYTE)
START_WAIT_SECONDS = 60
POLL_SECONDS = 2.0


class BuildProcessError(RuntimeError):
    """Raised when a build command or host-safety invariant fails."""


@dataclass(frozen=True)
class HostMemorySnapshot:
    total_bytes: int
    available_bytes: int


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


def host_memory_snapshot(meminfo_path: Path = Path("/proc/meminfo")) -> HostMemorySnapshot:
    try:
        values = {
            key.rstrip(":"): int(value) * 1024
            for key, value, unit in (
                line.split(maxsplit=2)
                for line in meminfo_path.read_text(encoding="ascii").splitlines()
                if line.startswith(("MemTotal:", "MemAvailable:"))
            )
            if unit == "kB"
        }
    except (OSError, ValueError) as exc:
        raise BuildProcessError("cannot read host MemAvailable") from exc
    if values.get("MemTotal", 0) <= 0 or values.get("MemAvailable", 0) <= 0:
        raise BuildProcessError("host memory information is incomplete")
    return HostMemorySnapshot(values["MemTotal"], values["MemAvailable"])


def wait_for_start_capacity(
    *,
    snapshot_reader: Callable[[], HostMemorySnapshot] = host_memory_snapshot,
    sleeper: Callable[[float], None] = time.sleep,
    timeout_seconds: float = START_WAIT_SECONDS,
    poll_seconds: float = POLL_SECONDS,
) -> HostMemorySnapshot:
    deadline = time.monotonic() + timeout_seconds
    while True:
        snapshot = snapshot_reader()
        if snapshot.available_bytes >= START_AVAILABLE_BYTES:
            return snapshot
        if time.monotonic() >= deadline:
            raise BuildProcessError(
                "timed out waiting briefly for 4 GiB MemAvailable; no heavy command was started"
            )
        sleeper(min(poll_seconds, max(0.0, deadline - time.monotonic())))


def activate_runtime_attachment(*, allow_operator_detached: bool = False) -> str | None:
    if allow_operator_detached:
        return None
    runtime_session_id = str(os.environ.get("MAVERICK_RUNTIME_SESSION_ID") or "").strip()
    if not runtime_session_id:
        raise BuildProcessError("OpenDesign packaging requires a Maverick runtime attachment")
    if not runtime_session_is_in_ancestry(runtime_session_id):
        raise BuildProcessError("OpenDesign packaging runtime attachment is invalid")
    return runtime_session_id


def runtime_session_is_in_ancestry(
    runtime_session_id: str,
    *,
    parent_pid: int | None = None,
    proc_root: Path = Path("/proc"),
) -> bool:
    marker = f"MAVERICK_RUNTIME_SESSION_ID={runtime_session_id}".encode("utf-8")
    pid = os.getppid() if parent_pid is None else parent_pid
    visited: set[int] = set()
    while pid > 1 and pid not in visited:
        visited.add(pid)
        process_root = proc_root / str(pid)
        try:
            environment = (process_root / "environ").read_bytes().split(b"\0")
            command = (process_root / "cmdline").read_bytes().replace(b"\0", b" ").lower()
            status = (process_root / "status").read_text(encoding="utf-8")
        except OSError:
            return False
        if marker in environment and b"codex" in command and b"app-server" in command:
            return True
        parent_line = next((line for line in status.splitlines() if line.startswith("PPid:")), "")
        try:
            pid = int(parent_line.split(":", 1)[1].strip())
        except (IndexError, ValueError):
            return False
    return False


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    capture: bool = False,
    heavy: bool = False,
    check: bool = True,
    runtime_session_id: str | None = None,
    snapshot_reader: Callable[[], HostMemorySnapshot] = host_memory_snapshot,
) -> CommandResult:
    if not command or not all(isinstance(item, str) and item for item in command):
        raise BuildProcessError("build command must be a non-empty string list")
    if heavy:
        wait_for_start_capacity(snapshot_reader=snapshot_reader)
    log_handle: TextIO | None = None
    output_target: int | TextIO | None
    if capture:
        output_target = subprocess.PIPE
    elif log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("w", encoding="utf-8")
        output_target = log_handle
    else:
        output_target = None
    process: subprocess.Popen[str] | None = None
    label = log_path.name if log_path is not None else command[0]
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=output_target,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        while True:
            try:
                stdout, _ = process.communicate(timeout=POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if runtime_session_id and not runtime_session_is_in_ancestry(runtime_session_id):
                    _terminate_process_group(process)
                    raise BuildProcessError(f"OpenDesign command lost its runtime attachment: {label}")
                snapshot = snapshot_reader() if heavy else None
                if snapshot is not None and snapshot.available_bytes < STOP_AVAILABLE_BYTES:
                    _terminate_process_group(process)
                    available_gib = snapshot.available_bytes / GIBIBYTE
                    raise BuildProcessError(
                        f"OpenDesign command stopped below 2.5 GiB MemAvailable: "
                        f"{label} ({available_gib:.2f} GiB)"
                    )
        result = CommandResult(process.returncode, (stdout or "").strip())
        if check and result.returncode != 0:
            detail = _log_tail(log_path) if log_path is not None else result.stdout[-2000:]
            suffix = f"\n{detail}" if detail else ""
            raise BuildProcessError(
                f"OpenDesign command failed ({result.returncode}): {label}{suffix}"
            )
        return result
    except BaseException:
        if process is not None:
            _terminate_process_group(process)
        raise
    finally:
        if log_handle is not None:
            log_handle.close()


@contextmanager
def signal_guard() -> Iterator[None]:
    handled = tuple(
        candidate
        for candidate in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None))
        if candidate is not None
    )
    previous = {candidate: signal.getsignal(candidate) for candidate in handled}

    def interrupt(signum: int, _frame: object) -> None:
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = str(signum)
        raise BuildProcessError(f"OpenDesign packaging interrupted by {name}")

    try:
        for candidate in handled:
            signal.signal(candidate, interrupt)
        yield
    finally:
        for candidate, handler in previous.items():
            signal.signal(candidate, handler)


def _terminate_process_group(process: subprocess.Popen[str], *, timeout_seconds: float = 10.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=timeout_seconds)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _log_tail(path: Path, *, maximum_bytes: int = 4096) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - maximum_bytes))
            return handle.read(maximum_bytes).decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
