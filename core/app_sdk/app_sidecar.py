"""Public SDK client for invocation-scoped app-owned HTTP sidecars."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import socket
from typing import Any, Mapping
from urllib.parse import urlencode


_PROTOCOL = "maverick.app-sidecar.v1"
_MAX_BROKER_ENVELOPE_OVERHEAD = 64 * 1024


class AppSidecarError(RuntimeError):
    """Base error for the governed app-sidecar SDK surface."""


class AppSidecarUnavailableError(AppSidecarError):
    """The invocation did not receive a usable broker capability."""


class AppSidecarRequestError(AppSidecarError):
    """The core broker denied or failed one governed request."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class AppSidecarResponse:
    """Bounded response returned by the core sidecar broker."""

    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        """Decode a JSON response body."""
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self) -> str:
        """Decode the response body as UTF-8 text."""
        return self.body.decode("utf-8")


@dataclass(frozen=True, repr=False)
class _BrokerDescriptor:
    socket_path: str
    capability: str
    expires_in_seconds: int
    request_budget: int
    max_request_body_bytes: int
    max_response_body_bytes: int


class AppSidecarClient:
    """HTTP-like client that can reach only its core-issued broker socket."""

    def __init__(self, *, service_id: str, descriptor: _BrokerDescriptor) -> None:
        self._service_id = service_id
        self._descriptor = descriptor

    def __repr__(self) -> str:
        return f"{type(self).__name__}(service_id={self._service_id!r})"

    def get(
        self,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AppSidecarResponse:
        return self.request("GET", path, query=query, headers=headers)

    def post(
        self,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | str | None = None,
        json_body: Any | None = None,
    ) -> AppSidecarResponse:
        return self.request(
            "POST",
            path,
            query=query,
            headers=headers,
            body=body,
            json_body=json_body,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | str | None = None,
        json_body: Any | None = None,
    ) -> AppSidecarResponse:
        """Send one bounded request through the invocation broker."""
        if body is not None and json_body is not None:
            raise ValueError("Provide either body or json_body, not both.")
        normalized_path = str(path or "")
        if not normalized_path.startswith("/") or any(character in normalized_path for character in ("?", "#")):
            raise ValueError("App sidecar paths must be absolute and cannot include query or fragment text.")
        request_headers = _normalized_headers(headers)
        if json_body is not None:
            request_body = json.dumps(json_body, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("content-type", "application/json")
        elif isinstance(body, str):
            request_body = body.encode("utf-8")
        else:
            request_body = bytes(body or b"")
        if len(request_body) > self._descriptor.max_request_body_bytes:
            raise AppSidecarRequestError("request_body_too_large")
        envelope = {
            "capability": self._descriptor.capability,
            "method": str(method or "").strip().upper(),
            "path": normalized_path,
            "query_string": urlencode(query or {}, doseq=True),
            "headers": request_headers,
            "body_base64": base64.b64encode(request_body).decode("ascii"),
        }
        wire = json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"
        response_wire = self._exchange(wire)
        try:
            response_payload = json.loads(response_wire.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AppSidecarRequestError("invalid_broker_response") from error
        if not isinstance(response_payload, dict):
            raise AppSidecarRequestError("invalid_broker_response")
        if response_payload.get("ok") is not True:
            raise AppSidecarRequestError(str(response_payload.get("error") or "broker_request_failed"))
        try:
            response_body = base64.b64decode(
                str(response_payload.get("body_base64") or ""),
                validate=True,
            )
        except (ValueError, TypeError) as error:
            raise AppSidecarRequestError("invalid_broker_response") from error
        if len(response_body) > self._descriptor.max_response_body_bytes:
            raise AppSidecarRequestError("response_body_too_large")
        response_headers = response_payload.get("headers")
        if not isinstance(response_headers, dict):
            raise AppSidecarRequestError("invalid_broker_response")
        return AppSidecarResponse(
            status_code=int(response_payload.get("status_code") or 0),
            headers={str(name).lower(): str(value) for name, value in response_headers.items()},
            body=response_body,
        )

    def _exchange(self, wire: bytes) -> bytes:
        timeout = max(1, min(self._descriptor.expires_in_seconds, 30))
        maximum = (self._descriptor.max_response_body_bytes * 4 // 3) + _MAX_BROKER_ENVELOPE_OVERHEAD
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(timeout)
        try:
            connection.connect(self._descriptor.socket_path)
            connection.sendall(wire)
            response = bytearray()
            while not response.endswith(b"\n"):
                chunk = connection.recv(min(65536, maximum + 1 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > maximum:
                    raise AppSidecarRequestError("broker_response_too_large")
        except AppSidecarRequestError:
            raise
        except (OSError, TimeoutError) as error:
            raise AppSidecarUnavailableError("broker_unavailable") from error
        finally:
            connection.close()
        if not response.endswith(b"\n"):
            raise AppSidecarRequestError("invalid_broker_response")
        return bytes(response[:-1])


def app_sidecar(payload: Any, service_id: str) -> AppSidecarClient:
    """Resolve one declared sidecar client from an entrypoint payload."""
    raw = payload.raw if hasattr(payload, "raw") else payload
    if not isinstance(raw, dict):
        raise AppSidecarUnavailableError("service_not_available")
    broker = raw.get("app_sidecar")
    if not isinstance(broker, dict) or broker.get("protocol") != _PROTOCOL:
        raise AppSidecarUnavailableError("service_not_available")
    services = broker.get("services")
    service = services.get(service_id) if isinstance(services, dict) else None
    if not isinstance(service, dict) or service.get("streaming") is not False:
        raise AppSidecarUnavailableError("service_not_available")
    try:
        descriptor = _BrokerDescriptor(
            socket_path=_required_string(service, "broker_socket"),
            capability=_required_string(service, "capability"),
            expires_in_seconds=_positive_int(service, "expires_in_seconds", maximum=30),
            request_budget=_positive_int(service, "request_budget", maximum=256),
            max_request_body_bytes=_nonnegative_int(service, "max_request_body_bytes"),
            max_response_body_bytes=_positive_int(service, "max_response_body_bytes"),
        )
    except (TypeError, ValueError) as error:
        raise AppSidecarUnavailableError("service_not_available") from error
    return AppSidecarClient(service_id=service_id, descriptor=descriptor)


def _normalized_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip().lower()
        value = str(raw_value).strip()
        if not name or any(character in name + value for character in ("\r", "\n")):
            raise ValueError("App sidecar headers must be single-line name/value pairs.")
        normalized[name] = value
    return normalized


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(key)
    return value


def _positive_int(payload: dict[str, Any], key: str, *, maximum: int | None = None) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(key)
    if maximum is not None and value > maximum:
        raise ValueError(key)
    return value


def _nonnegative_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(key)
    return value
