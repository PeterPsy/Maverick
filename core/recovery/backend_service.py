"""Helpers for restarting the platform backend host service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen


_SYSTEMCTL_AUTH_FAILURE_MARKERS = (
    "interactive authentication required",
    "access denied",
    "authentication is required",
)


@dataclass(frozen=True)
class BackendServiceRestartResult:
    """Structured outcome for one backend host restart attempt."""

    service_name: str
    health_url: str
    scheduled: bool
    restarted: bool
    method: str
    detail: str
    previous_pid: int | None
    current_pid: int | None
    active_state: str
    sub_state: str
    healthy: bool

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


def restart_backend_service(
    *,
    service_name: str = "maverick-core.service",
    health_url: str = "http://127.0.0.1:8014/health",
    process_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    process_killer: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 15.0,
) -> BackendServiceRestartResult:
    """Restart one systemd-managed backend service, with a non-root fallback.

    The preferred path is `systemctl restart`. When the current caller cannot
    authenticate for that operation but the service is configured with
    `Restart=always`, the helper falls back to sending `SIGTERM` to the current
    `MainPID` and waiting for systemd to respawn the service.
    """

    before = _service_status(service_name=service_name, process_runner=process_runner)
    previous_pid = _parse_pid(before.get("MainPID"))
    restart_policy = before.get("Restart", "")

    restart = process_runner(
        ["systemctl", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
    )
    method = "systemctl"
    if restart.returncode != 0:
        detail = (restart.stderr or restart.stdout or "").strip() or "systemctl restart failed."
        if not _is_systemctl_auth_failure(detail) or previous_pid is None or restart_policy != "always":
            after = _service_status(service_name=service_name, process_runner=process_runner)
            return BackendServiceRestartResult(
                service_name=service_name,
                health_url=health_url,
                scheduled=False,
                restarted=False,
                method=method,
                detail=detail,
                previous_pid=previous_pid,
                current_pid=_parse_pid(after.get("MainPID")),
                active_state=after.get("ActiveState", ""),
                sub_state=after.get("SubState", ""),
                healthy=_health_ok(health_url),
            )
        if previous_pid == os.getpid():
            _schedule_delayed_sigterm(
                previous_pid,
                force_after_seconds=timeout_seconds,
            )
            return BackendServiceRestartResult(
                service_name=service_name,
                health_url=health_url,
                scheduled=True,
                restarted=True,
                method="deferred-signal",
                detail="Backend service restart scheduled through a detached helper process.",
                previous_pid=previous_pid,
                current_pid=previous_pid,
                active_state=before.get("ActiveState", ""),
                sub_state=before.get("SubState", ""),
                healthy=_health_ok(health_url),
            )
        process_killer(previous_pid, signal.SIGTERM)
        method = "signal"

    deadline = time.monotonic() + timeout_seconds
    latest = before
    while time.monotonic() < deadline:
        latest = _service_status(service_name=service_name, process_runner=process_runner)
        current_pid = _parse_pid(latest.get("MainPID"))
        if (
            latest.get("ActiveState") == "active"
            and latest.get("SubState") == "running"
            and current_pid is not None
            and (method == "systemctl" or current_pid != previous_pid)
        ):
            healthy = _health_ok(health_url)
            if healthy:
                return BackendServiceRestartResult(
                    service_name=service_name,
                    health_url=health_url,
                    scheduled=False,
                    restarted=True,
                    method=method,
                    detail="Backend service restarted and health check passed.",
                    previous_pid=previous_pid,
                    current_pid=current_pid,
                    active_state=latest.get("ActiveState", ""),
                    sub_state=latest.get("SubState", ""),
                    healthy=True,
                )
        sleep(0.5)

    return BackendServiceRestartResult(
        service_name=service_name,
        health_url=health_url,
        scheduled=False,
        restarted=False,
        method=method,
        detail="Backend service did not become healthy before the timeout.",
        previous_pid=previous_pid,
        current_pid=_parse_pid(latest.get("MainPID")),
        active_state=latest.get("ActiveState", ""),
        sub_state=latest.get("SubState", ""),
        healthy=_health_ok(health_url),
    )


def _is_systemctl_auth_failure(detail: str) -> bool:
    """Return true when systemctl failed because the caller cannot authorize restart."""
    normalized = detail.casefold()
    return any(marker in normalized for marker in _SYSTEMCTL_AUTH_FAILURE_MARKERS)


def _service_status(
    *,
    service_name: str,
    process_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, str]:
    response = process_runner(
        ["systemctl", "show", service_name, "-p", "MainPID", "-p", "Restart", "-p", "ActiveState", "-p", "SubState"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = response.stdout if response.returncode == 0 else response.stderr
    values: dict[str, str] = {}
    for line in str(output or "").splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        values[key.strip()] = raw_value.strip()
    return values


def _parse_pid(raw_value: str | None) -> int | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        pid = int(value)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _schedule_delayed_sigterm(
    pid: int,
    *,
    delay_seconds: float = 0.75,
    force_after_seconds: float = 15.0,
) -> None:
    process_start_token = _process_start_token(pid)
    if process_start_token is None:
        raise RuntimeError(f"Could not identify backend process `{pid}` before restart.")
    subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from core.recovery.backend_service import _terminate_process_with_escalation; "
                "_terminate_process_with_escalation("
                "int(sys.argv[1]), sys.argv[2], "
                "delay_seconds=float(sys.argv[3]), force_after_seconds=float(sys.argv[4]))"
            ),
            str(pid),
            process_start_token,
            str(delay_seconds),
            str(force_after_seconds),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _terminate_process_with_escalation(
    pid: int,
    expected_start_token: str,
    *,
    delay_seconds: float,
    force_after_seconds: float,
    process_killer: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    process_start_token: Callable[[int], str | None] | None = None,
) -> None:
    """Terminate one process, escalating only while its PID still has the same owner."""
    read_start_token = process_start_token or _process_start_token
    sleep(max(0.0, delay_seconds))
    if read_start_token(pid) != expected_start_token:
        return
    try:
        process_killer(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = monotonic() + max(0.0, force_after_seconds)
    while read_start_token(pid) == expected_start_token:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.25, remaining))
    if read_start_token(pid) != expected_start_token:
        return
    try:
        process_killer(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _process_start_token(pid: int) -> str | None:
    """Return the Linux process start token used to detect PID reuse."""
    try:
        raw_stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    command_end = raw_stat.rfind(")")
    if command_end < 0:
        return None
    fields_after_command = raw_stat[command_end + 1 :].split()
    return fields_after_command[19] if len(fields_after_command) > 19 else None


def _health_ok(health_url: str) -> bool:
    try:
        with urlopen(health_url, timeout=3) as response:  # noqa: S310
            return 200 <= int(response.status) < 300
    except (OSError, URLError, ValueError):
        return False
