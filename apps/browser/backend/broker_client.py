"""HTTP client for the Browser app's local Playwright broker sidecar."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from errors import BrowserBrokerUnavailableError


BROKER_URL_ENV = "MAVERICK_BROWSER_BROKER_URL"
DEFAULT_BROKER_URL = "http://127.0.0.1:9323"
BROKER_TIMEOUT_SECONDS_ENV = "MAVERICK_BROWSER_BROKER_TIMEOUT_SECONDS"
DEFAULT_BROKER_TIMEOUT_SECONDS = 25.0
BROKER_TOKEN_ENV = "MAVERICK_BROWSER_BROKER_TOKEN"


@dataclass(frozen=True)
class BrokerHttpResponse:
    status_code: int
    payload: dict[str, Any]


def broker_url() -> str:
    configured = os.environ.get(BROKER_URL_ENV, DEFAULT_BROKER_URL).strip()
    return configured.rstrip("/") or DEFAULT_BROKER_URL


def broker_timeout_seconds() -> float:
    raw = os.environ.get(BROKER_TIMEOUT_SECONDS_ENV, "").strip()
    if not raw:
        return DEFAULT_BROKER_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_BROKER_TIMEOUT_SECONDS
    if value <= 0 or value > 120:
        return DEFAULT_BROKER_TIMEOUT_SECONDS
    return value


def broker_token() -> str:
    token = os.environ.get(BROKER_TOKEN_ENV, "").strip()
    if not token:
        raise BrowserBrokerUnavailableError(f"Browser broker requires {BROKER_TOKEN_ENV}.")
    return token


def broker_health() -> dict[str, Any]:
    url = broker_url()
    try:
        response = _request("GET", f"{url}/health")
    except BrowserBrokerUnavailableError as error:
        return {
            "status": "unreachable",
            "provider": "playwright_lab",
            "url": redact_endpoint(url),
            "detail": str(error),
        }
    payload = response.payload
    payload.setdefault("status", "ready" if response.status_code < 400 else "degraded")
    payload.setdefault("provider", "playwright_lab")
    payload["url"] = redact_endpoint(url)
    return payload


def call_broker_action(action: str, body: dict[str, Any]) -> BrokerHttpResponse:
    payload = {"action": action, "payload": body}
    return _request("POST", f"{broker_url()}/actions", payload=payload)


def _request(method: str, url: str, *, payload: dict[str, Any] | None = None) -> BrokerHttpResponse:
    data = None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {broker_token()}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=broker_timeout_seconds()) as response:
            return BrokerHttpResponse(response.status, _decode_payload(response.read()))
    except HTTPError as error:
        return BrokerHttpResponse(error.code, _decode_payload(error.read()))
    except (OSError, URLError) as error:
        raise BrowserBrokerUnavailableError(f"Browser broker is not reachable at {redact_endpoint(url)}.") from error


def _decode_payload(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrowserBrokerUnavailableError("Browser broker returned a non-JSON response.") from error
    if not isinstance(decoded, dict):
        raise BrowserBrokerUnavailableError("Browser broker returned an invalid JSON response.")
    return decoded


def redact_endpoint(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if host and ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "", "", ""))
