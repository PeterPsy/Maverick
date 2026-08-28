"""Client for the private Core model-access Unix broker."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import socket
from typing import Mapping


EXPECTED_SOCKET = Path("/model-access/broker.sock")
MAX_CATALOG_BYTES = 2 * 1024 * 1024


class ModelAccessClientError(RuntimeError):
    """Redaction-safe model bridge failure."""


class _UnixHttpConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path, *, timeout: float = 60) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(str(self.socket_path))
        self.sock = connection


@dataclass(frozen=True)
class ModelAccessConfiguration:
    socket_path: Path
    token: str

    @classmethod
    def from_environment(cls) -> "ModelAccessConfiguration":
        if os.environ.get("MAVERICK_MODEL_ACCESS_STATE") != "available":
            raise ModelAccessClientError("model access is unavailable")
        socket_path = Path(os.environ.get("MAVERICK_MODEL_ACCESS_SOCKET", ""))
        token = os.environ.get("MAVERICK_MODEL_ACCESS_TOKEN", "")
        if socket_path != EXPECTED_SOCKET or not token or "\x00" in token:
            raise ModelAccessClientError("model access capability is invalid")
        return cls(socket_path=socket_path, token=token)


class ModelAccessClient:
    def __init__(self, configuration: ModelAccessConfiguration) -> None:
        self.configuration = configuration

    def open(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: Mapping[str, str] | None = None,
        timeout: float = 60,
    ) -> tuple[_UnixHttpConnection, http.client.HTTPResponse]:
        connection = _UnixHttpConnection(self.configuration.socket_path, timeout=timeout)
        request_headers = {
            "Authorization": f"Bearer {self.configuration.token}",
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
            **dict(headers or {}),
        }
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as error:
            connection.close()
            raise ModelAccessClientError("model access broker is unavailable") from error
        return connection, response

    def catalog(self) -> dict[str, object]:
        connection, response = self.open("GET", "/maverick/v1/catalog", timeout=5)
        try:
            body = response.read(MAX_CATALOG_BYTES + 1)
        finally:
            connection.close()
        if response.status != 200 or len(body) > MAX_CATALOG_BYTES:
            raise ModelAccessClientError("model access catalog is unavailable")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelAccessClientError("model access catalog is invalid") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != "1":
            raise ModelAccessClientError("model access catalog is invalid")
        return payload
