"""Bounded HTTPS/SSE transport for the Google Gemini Interactions API."""

from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
import json
import socket
from typing import Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_ENDPOINT,
    GoogleInteractionsProtocolError,
)


MAX_GOOGLE_REQUEST_BYTES = 4 * 1_048_576
MAX_GOOGLE_SSE_EVENT_BYTES = 2 * 1_048_576
MAX_GOOGLE_STREAM_BYTES = 16 * 1_048_576


class GoogleInteractionsTransport(Protocol):
    def stream(
        self,
        *,
        payload: dict[str, object],
        credential: EphemeralCredential,
    ) -> AsyncIterator[dict[str, object]]: ...


class GoogleInteractionsHttpTransport:
    """POST to one pinned Google host and decode bounded SSE JSON events."""

    def __init__(self, *, endpoint: str = GOOGLE_INTERACTIONS_ENDPOINT, timeout_seconds: int = 120) -> None:
        parsed = urllib_parse.urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "generativelanguage.googleapis.com"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Google Interactions endpoint must use the pinned Google HTTPS host.")
        self.endpoint = endpoint
        self.timeout_seconds = max(1, min(timeout_seconds, 300))
        self._opener = urllib_request.build_opener(_RejectRedirects())

    async def stream(
        self,
        *,
        payload: dict[str, object],
        credential: EphemeralCredential,
    ) -> AsyncIterator[dict[str, object]]:
        encoded = _encode_request(payload)
        request = urllib_request.Request(
            self.endpoint,
            data=encoded,
            method="POST",
            headers={
                "x-goog-api-key": credential.reveal(),
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "Maverick-Agentic-Runtime/1",
            },
        )
        response = None
        try:
            response = await asyncio.to_thread(
                self._opener.open,
                request,
                timeout=self.timeout_seconds,
            )
            if urllib_parse.urlsplit(response.geturl()).hostname != "generativelanguage.googleapis.com":
                raise GoogleInteractionsProtocolError("provider_request_rejected")
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/event-stream" not in content_type:
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            async for event in _read_sse(response):
                yield event
        except urllib_error.HTTPError as error:
            raise GoogleInteractionsProtocolError(_http_reason(error.code)) from error
        except (TimeoutError, socket.timeout) as error:
            raise GoogleInteractionsProtocolError("provider_timeout") from error
        except urllib_error.URLError as error:
            reason = "provider_timeout" if isinstance(error.reason, socket.timeout) else "provider_unavailable"
            raise GoogleInteractionsProtocolError(reason) from error
        finally:
            if response is not None:
                await asyncio.to_thread(response.close)


class _RejectRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GoogleInteractionsProtocolError("provider_request_rejected")


async def _read_sse(response) -> AsyncIterator[dict[str, object]]:
    data_lines: list[bytes] = []
    total_bytes = 0
    saw_done = False
    while True:
        line = await asyncio.to_thread(response.readline, MAX_GOOGLE_SSE_EVENT_BYTES + 1)
        if not line:
            break
        total_bytes += len(line)
        if len(line) > MAX_GOOGLE_SSE_EVENT_BYTES or total_bytes > MAX_GOOGLE_STREAM_BYTES:
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        stripped = line.rstrip(b"\r\n")
        if stripped.startswith(b"data:"):
            data_lines.append(stripped[5:].lstrip())
            if sum(len(item) for item in data_lines) > MAX_GOOGLE_SSE_EVENT_BYTES:
                raise GoogleInteractionsProtocolError("provider_response_invalid")
            continue
        if stripped or not data_lines:
            continue
        data = b"\n".join(data_lines)
        data_lines = []
        if data == b"[DONE]":
            saw_done = True
            break
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoogleInteractionsProtocolError("provider_response_invalid") from error
        if not isinstance(payload, dict):
            raise GoogleInteractionsProtocolError("provider_response_invalid")
        yield payload
    if data_lines or not saw_done:
        raise GoogleInteractionsProtocolError("provider_response_invalid")


def _encode_request(payload: dict[str, object]) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise GoogleInteractionsProtocolError("provider_request_invalid") from error
    if len(encoded) > MAX_GOOGLE_REQUEST_BYTES:
        raise GoogleInteractionsProtocolError("provider_request_invalid")
    return encoded


def _http_reason(status_code: int) -> str:
    if status_code in {401, 403}:
        return "provider_authentication_failed"
    if status_code == 429:
        return "provider_rate_limited"
    if status_code in {408, 504}:
        return "provider_timeout"
    if 400 <= status_code < 500:
        return "provider_request_rejected"
    return "provider_unavailable"
