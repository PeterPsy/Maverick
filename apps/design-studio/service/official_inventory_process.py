"""Bounded process and HTTP client for disposable official OpenDesign copies."""

from __future__ import annotations

from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import secrets
import socket
import subprocess
import time
from typing import Any, Iterator

from official_opendesign_release import (
    OfficialInstallation,
    OfficialReleaseError,
    launch_disposable_official_release,
)


MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class OfficialApiClient:
    """Bounded client for supported public APIs on one disposable process."""

    def __init__(
        self,
        *,
        port: int,
        token: str,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        if not 0 < request_timeout_seconds <= 60:
            raise ValueError("official API request timeout is invalid")
        self._port = port
        self._token = token
        self._request_timeout_seconds = request_timeout_seconds

    def get_json(self, path: str) -> dict[str, Any]:
        _status, body = self.request("GET", path)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OfficialReleaseError(f"official API returned invalid JSON for {path}") from error
        if not isinstance(payload, dict):
            raise OfficialReleaseError(f"official API returned a non-object for {path}")
        return payload

    def get_bytes(self, path: str) -> bytes:
        _status, body = self.request("GET", path)
        return body

    def send_json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one JSON request and require one JSON object response."""
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        _status, response = self.request(
            method,
            path,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            decoded = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OfficialReleaseError(f"official API returned invalid JSON for {path}") from error
        if not isinstance(decoded, dict):
            raise OfficialReleaseError(f"official API returned a non-object for {path}")
        return decoded

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        """Issue one bounded authenticated request to the disposable daemon."""
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            raise OfficialReleaseError("official API probe method is unsupported")
        if not path.startswith("/api/") or "\x00" in path:
            raise OfficialReleaseError("official API probe path is unsafe")
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self._port,
            timeout=self._request_timeout_seconds,
        )
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Connection": "close",
                    **(headers or {}),
                },
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if not 200 <= response.status < 300:
                raise OfficialReleaseError(
                    f"official API route {path} returned HTTP {response.status}"
                )
            if len(body) > MAX_RESPONSE_BYTES:
                raise OfficialReleaseError(
                    f"official API route {path} exceeded the inventory limit"
                )
            return response.status, body
        finally:
            connection.close()


@contextmanager
def running_official_api(
    installation: OfficialInstallation,
    *,
    data_dir: Path,
    log_path: Path,
    timeout_seconds: float,
) -> Iterator[OfficialApiClient]:
    """Launch an unchanged release with both bridges disabled, then stop it."""
    port = _unused_loopback_port()
    token = secrets.token_urlsafe(32)
    process: subprocess.Popen[bytes] | None = None
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        try:
            process = launch_disposable_official_release(
                installation,
                data_dir=data_dir,
                port=port,
                api_token=token,
                bridge_mode="disabled",
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            client = OfficialApiClient(port=port, token=token)
            _wait_ready(process, client=client, timeout_seconds=timeout_seconds)
            yield client
        finally:
            if process is not None:
                _stop_process(process)


def _wait_ready(
    process: subprocess.Popen[bytes],
    *,
    client: OfficialApiClient,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise OfficialReleaseError(
                f"official OpenDesign exited during inventory with {process.returncode}"
            )
        try:
            ready = client.get_json("/api/ready")
            if ready.get("ready") is True or ready.get("ok") is True:
                return
        except (OSError, http.client.HTTPException, OfficialReleaseError) as error:
            last_error = str(error)
        time.sleep(0.1)
    raise OfficialReleaseError(
        f"official OpenDesign inventory did not become ready: {last_error}"
    )


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
