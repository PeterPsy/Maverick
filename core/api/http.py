"""Small HTTP helpers shared by the hosted platform APIs."""

from __future__ import annotations

from datetime import date, datetime
import json
import os
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


StartResponse = Callable[[str, list[tuple[str, str]]], None]
# Keep the default body ceiling high enough for the workspace upload API's
# 25 MiB decoded-file contract after base64/JSON expansion.
DEFAULT_MAX_JSON_BODY_BYTES = 40 * 1024 * 1024


class HttpRequestError(ValueError):
    """HTTP parsing error with a stable status and code."""

    def __init__(self, error: str, status: str) -> None:
        super().__init__(error)
        self.error = error
        self.status = status


def status_line(status_code: int) -> str:
    """Return one WSGI status line."""
    reasons = {
        200: "OK",
        201: "Created",
        204: "No Content",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        413: "Payload Too Large",
        500: "Internal Server Error",
    }
    return f"{status_code} {reasons.get(status_code, 'OK')}"


def json_default(value: Any) -> str:
    """Serialize datetimes and dates in API payloads."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def json_response(
    start_response: StartResponse,
    payload: dict[str, Any],
    *,
    status: str = "200 OK",
    headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    """Return a JSON WSGI response."""
    body = json.dumps(payload, indent=2, default=json_default).encode("utf-8")
    response_headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [body]


def text_response(
    start_response: StartResponse,
    body: str,
    *,
    status: str = "200 OK",
    content_type: str = "text/plain; charset=utf-8",
    headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    """Return a text WSGI response."""
    encoded = body.encode("utf-8")
    response_headers = [("Content-Type", content_type), ("Content-Length", str(len(encoded)))]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [encoded]


def read_json_body(environ: dict) -> dict[str, Any]:
    """Read one JSON request body."""
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError as exc:
        raise HttpRequestError("invalid_content_length", "400 Bad Request") from exc
    max_bytes = max_json_body_bytes()
    if length > max_bytes:
        raise HttpRequestError("request_body_too_large", "413 Payload Too Large")
    raw = environ["wsgi.input"].read(length) if length > 0 else b""
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpRequestError("invalid_json_body", "400 Bad Request") from exc
    if not isinstance(payload, dict):
        raise HttpRequestError("json_body_must_be_object", "400 Bad Request")
    return payload


def max_json_body_bytes() -> int:
    """Return the configured JSON/HTTP body size limit."""
    configured = os.environ.get("MAVERICK_MAX_JSON_BODY_BYTES")
    if not configured:
        return DEFAULT_MAX_JSON_BODY_BYTES
    try:
        value = int(configured)
    except ValueError:
        return DEFAULT_MAX_JSON_BODY_BYTES
    return max(1, value)


def _max_json_body_bytes() -> int:
    return max_json_body_bytes()


def query_params(environ: dict) -> dict[str, str]:
    """Return single-value query parameters."""
    return {key: value[-1] for key, value in parse_qs(environ.get("QUERY_STRING", "")).items()}


def request_cookies(environ: dict) -> dict[str, str]:
    """Parse the request Cookie header."""
    header = environ.get("HTTP_COOKIE", "")
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    return cookies


def enforce_same_origin_for_unsafe_request(environ: dict) -> None:
    """Reject unsafe browser requests whose Origin/Referer does not match Host."""
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    host = str(environ.get("HTTP_HOST") or environ.get("SERVER_NAME") or "").lower()
    if not host:
        return
    origin = str(environ.get("HTTP_ORIGIN") or "").strip()
    referer = str(environ.get("HTTP_REFERER") or "").strip()
    candidate = origin or referer
    has_cookie_credentials = bool(str(environ.get("HTTP_COOKIE") or "").strip())
    if has_cookie_credentials and not candidate:
        raise HttpRequestError("same_origin_proof_required", "403 Forbidden")
    if not candidate:
        return
    parsed = urlparse(candidate)
    if not parsed.netloc:
        return
    if parsed.netloc.lower() != host:
        raise HttpRequestError("cross_origin_request_forbidden", "403 Forbidden")
