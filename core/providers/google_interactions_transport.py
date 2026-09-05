"""Bounded HTTPS/SSE transport for the Google Gemini Interactions API."""

from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
import socket
from typing import Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.agentic_sse import encode_bounded_json, read_bounded_json_sse
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
            endpoint != GOOGLE_INTERACTIONS_ENDPOINT
            or parsed.scheme != "https"
            or parsed.hostname != "generativelanguage.googleapis.com"
        ):
            raise ValueError("Google Interactions endpoint must use the pinned HTTPS route.")
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
    async for payload in read_bounded_json_sse(
        response,
        max_event_bytes=MAX_GOOGLE_SSE_EVENT_BYTES,
        max_stream_bytes=MAX_GOOGLE_STREAM_BYTES,
        error=GoogleInteractionsProtocolError,
    ):
        yield payload


def _encode_request(payload: dict[str, object]) -> bytes:
    return encode_bounded_json(
        payload,
        max_bytes=MAX_GOOGLE_REQUEST_BYTES,
        error=GoogleInteractionsProtocolError,
    )


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
