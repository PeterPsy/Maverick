"""Bounded process and HTTP client for disposable official OpenDesign copies."""

from __future__ import annotations

from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
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
        port: int | None = None,
        relay_socket: Path | None = None,
        relay_capability: str | None = None,
        target_port: int | None = None,
        token: str,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        if not 0 < request_timeout_seconds <= 60:
            raise ValueError("official API request timeout is invalid")
        if (port is None) == (relay_socket is None):
            raise ValueError("official API client requires exactly one local transport")
        if relay_socket is not None and not relay_capability:
            raise ValueError("official API relay capability is required")
        authority_port = port if port is not None else target_port
        if (
            isinstance(authority_port, bool)
            or not isinstance(authority_port, int)
            or not 1 <= authority_port <= 65535
        ):
            raise ValueError("official API target port is invalid")
        self._port = port
        self._relay_socket = Path(relay_socket) if relay_socket is not None else None
        self._relay_capability = relay_capability
        self._host_header = f"127.0.0.1:{authority_port}"
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
        status, _response_headers, response_body = self.request_details(
            method,
            path,
            body=body,
            headers=headers,
        )
        return status, response_body

    def request_details(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """Issue one bounded request and retain redaction-safe response headers."""
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            raise OfficialReleaseError("official API probe method is unsupported")
        if (path != "/" and not path.startswith("/api/")) or "\x00" in path:
            raise OfficialReleaseError("official API probe path is unsafe")
        connection = (
            _RelayHTTPConnection(
                self._relay_socket,
                self._relay_capability or "",
                timeout=self._request_timeout_seconds,
            )
            if self._relay_socket is not None
            else http.client.HTTPConnection(
                "127.0.0.1",
                self._port,
                timeout=self._request_timeout_seconds,
            )
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
                    "Host": self._host_header,
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
            return (
                response.status,
                {key.lower(): value for key, value in response.getheaders()},
                body,
            )
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
    relay_secret_fd = -1
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log, tempfile.TemporaryDirectory(
        prefix="opendesign-disposable-relay-"
    ) as relay_temporary:
        relay_directory = Path(relay_temporary)
        relay_capability = secrets.token_urlsafe(32)
        try:
            relay_secret_fd = _pipe_secret(relay_capability)
            process = launch_disposable_official_release(
                installation,
                data_dir=data_dir,
                port=port,
                api_token=token,
                bridge_mode="disabled",
                relay_directory=relay_directory,
                relay_secret_fd=relay_secret_fd,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            os.close(relay_secret_fd)
            relay_secret_fd = -1
            client = OfficialApiClient(
                relay_socket=relay_directory / "api.sock",
                relay_capability=relay_capability,
                target_port=port,
                token=token,
            )
            _wait_ready(process, client=client, timeout_seconds=timeout_seconds)
            yield client
        finally:
            if relay_secret_fd >= 0:
                os.close(relay_secret_fd)
            if process is not None:
                _stop_process(process)


class _RelayHTTPConnection(http.client.HTTPConnection):
    """HTTP connection carried only over the authenticated local Unix relay."""

    def __init__(self, relay_socket: Path, capability: str, *, timeout: float) -> None:
        super().__init__("disposable-opendesign", timeout=timeout)
        self._relay_socket = Path(relay_socket)
        self._preamble = (
            b"MAVERICK-SIDECAR-RELAY/1 " + capability.encode("ascii") + b"\n"
        )

    def connect(self) -> None:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(self.timeout)
        try:
            client.connect(str(self._relay_socket))
            client.sendall(self._preamble)
        except OSError:
            client.close()
            raise
        self.sock = client


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


def _pipe_secret(capability: str) -> int:
    read_fd, write_fd = os.pipe()
    try:
        payload = capability.encode("ascii") + b"\n"
        if os.write(write_fd, payload) != len(payload):
            raise OSError("short disposable relay secret write")
    except Exception:
        os.close(read_fd)
        raise
    finally:
        os.close(write_fd)
    return read_fd


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
