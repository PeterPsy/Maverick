"""Bounded HTTPS/SSE transport for certified OpenRouter agentic requests."""

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
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_ENDPOINT,
    OpenRouterAgenticProtocolError,
)


MAX_OPENROUTER_REQUEST_BYTES = 4 * 1_048_576
MAX_OPENROUTER_SSE_EVENT_BYTES = 2 * 1_048_576
MAX_OPENROUTER_STREAM_BYTES = 16 * 1_048_576


class OpenRouterAgenticTransport(Protocol):
    def stream(
        self,
        *,
        payload: dict[str, object],
        credential: EphemeralCredential,
    ) -> AsyncIterator[dict[str, object]]: ...


class OpenRouterAgenticHttpTransport:
    """POST to one pinned OpenRouter path and decode bounded SSE JSON."""

    def __init__(
        self,
        *,
        endpoint: str = OPENROUTER_AGENTIC_ENDPOINT,
        timeout_seconds: int = 120,
    ) -> None:
        parsed = urllib_parse.urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "openrouter.ai"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/api/v1/chat/completions"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OpenRouter agentic endpoint must use the pinned HTTPS route.")
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
                "Authorization": f"Bearer {credential.reveal()}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-OpenRouter-Metadata": "enabled",
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
            if response.geturl() != self.endpoint:
                raise OpenRouterAgenticProtocolError("provider_request_rejected")
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/event-stream" not in content_type:
                raise OpenRouterAgenticProtocolError("provider_response_invalid")
            async for event in _read_sse(response):
                yield event
        except urllib_error.HTTPError as cause:
            raise OpenRouterAgenticProtocolError(_http_reason(cause.code)) from cause
        except (TimeoutError, socket.timeout) as cause:
            raise OpenRouterAgenticProtocolError("provider_timeout") from cause
        except urllib_error.URLError as cause:
            reason = "provider_timeout" if isinstance(cause.reason, socket.timeout) else "provider_unavailable"
            raise OpenRouterAgenticProtocolError(reason) from cause
        finally:
            if response is not None:
                await asyncio.to_thread(response.close)


class _RejectRedirects(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OpenRouterAgenticProtocolError("provider_request_rejected")


def _read_sse(response) -> AsyncIterator[dict[str, object]]:
    return read_bounded_json_sse(
        response,
        max_event_bytes=MAX_OPENROUTER_SSE_EVENT_BYTES,
        max_stream_bytes=MAX_OPENROUTER_STREAM_BYTES,
        error=OpenRouterAgenticProtocolError,
    )


def _encode_request(payload: dict[str, object]) -> bytes:
    return encode_bounded_json(
        payload,
        max_bytes=MAX_OPENROUTER_REQUEST_BYTES,
        error=OpenRouterAgenticProtocolError,
    )


def _http_reason(status_code: int) -> str:
    if status_code in {401, 403}:
        return "provider_authentication_failed"
    if status_code == 404:
        return "provider_no_eligible_endpoint"
    if status_code == 429:
        return "provider_rate_limited"
    if status_code in {408, 504}:
        return "provider_timeout"
    if 400 <= status_code < 500:
        return "provider_request_rejected"
    return "provider_unavailable"
