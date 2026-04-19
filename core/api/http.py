"""Small HTTP helpers shared by the hosted platform APIs."""

from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any, Callable
from urllib.parse import parse_qs


StartResponse = Callable[[str, list[tuple[str, str]]], None]


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
    length = int(environ.get("CONTENT_LENGTH") or "0")
    raw = environ["wsgi.input"].read(length) if length > 0 else b""
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


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
