"""External lifecycle supervision for the unchanged official OpenDesign process."""

from __future__ import annotations

from contextlib import suppress
import http.client
import json
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Callable, Protocol


MAX_READY_RESPONSE_BYTES = 64 * 1024
READINESS_TIMEOUT_SECONDS = 20.0


class StoppableBridge(Protocol):
    def stop(self) -> None: ...


def supervise_official_process(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    model_bridge: StoppableBridge | None,
    ready_probe: Callable[[], bool],
    state_changed: Callable[[str, int | None], None],
    readiness_timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
) -> None:
    """Forward lifecycle signals and publish readiness without touching product traffic."""
    process = subprocess.Popen(command, cwd=cwd, env=environment)
    previous: dict[signal.Signals, Any] = {}

    def forward(signum, _frame) -> None:
        if process.poll() is None:
            process.send_signal(signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, forward)
        if _wait_until_ready(
            process,
            ready_probe=ready_probe,
            timeout_seconds=readiness_timeout_seconds,
        ):
            _publish_state(state_changed, "ready", None)
        exit_code = process.wait()
        _publish_state(state_changed, "stopped" if exit_code == 0 else "failed", exit_code)
    finally:
        if model_bridge is not None:
            model_bridge.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    raise SystemExit(exit_code)


def official_api_ready(*, host: str, port: int, api_token: str) -> bool:
    """Check only the upstream readiness endpoint with its technical API capability."""
    connection = http.client.HTTPConnection(host, port, timeout=1)
    try:
        connection.request(
            "GET",
            "/api/ready",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        body = response.read(MAX_READY_RESPONSE_BYTES + 1)
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()
    if response.status != 200 or len(body) > MAX_READY_RESPONSE_BYTES:
        return False
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and (payload.get("ready") is True or payload.get("ok") is True)


def _wait_until_ready(
    process: subprocess.Popen[bytes],
    *,
    ready_probe: Callable[[], bool],
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while process.poll() is None and time.monotonic() < deadline:
        try:
            if ready_probe():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def _publish_state(
    callback: Callable[[str, int | None], None],
    state: str,
    exit_code: int | None,
) -> None:
    with suppress(Exception):
        callback(state, exit_code)


__all__ = ["official_api_ready", "supervise_official_process"]
