from __future__ import annotations

import asyncio
import io
import unittest

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.openrouter_agentic_models import OpenRouterAgenticProtocolError
from core.providers.openrouter_agentic_transport import (
    MAX_OPENROUTER_REQUEST_BYTES,
    OpenRouterAgenticHttpTransport,
    _encode_request,
    _http_reason,
    _read_sse,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.stream = io.BytesIO(payload)

    def readline(self, limit: int) -> bytes:
        return self.stream.readline(limit)


class _HttpResponse(_Response):
    headers = {"Content-Type": "text/event-stream; charset=utf-8"}

    def geturl(self) -> str:
        return "https://openrouter.ai/api/v1/chat/completions"

    def close(self) -> None:
        return None


class _Opener:
    def __init__(self, response: _HttpResponse) -> None:
        self.response = response
        self.request = None

    def open(self, request, *, timeout):
        self.request = request
        return self.response


class OpenRouterAgenticTransportTest(unittest.TestCase):
    def test_sse_decodes_only_complete_bounded_json(self) -> None:
        response = _Response(
            b'data: {"id":"generation-1"}\n\n'
            b'data: [DONE]\n\n'
        )
        self.assertEqual(asyncio.run(_events(response)), [{"id": "generation-1"}])

        with self.assertRaisesRegex(OpenRouterAgenticProtocolError, "provider_response_invalid"):
            asyncio.run(_events(_Response(b'data: []\n\n')))
        with self.assertRaisesRegex(OpenRouterAgenticProtocolError, "provider_response_invalid"):
            asyncio.run(_events(_Response(b'data: {"id":"generation-1"}\n\n')))

    def test_transport_pins_exact_https_route_and_bounds_request(self) -> None:
        invalid = (
            "https://example.com/api/v1/chat/completions",
            "http://openrouter.ai/api/v1/chat/completions",
            "https://openrouter.ai/another-path",
            "https://openrouter.ai/api/v1/chat/completions?redirect=true",
        )
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                OpenRouterAgenticHttpTransport(endpoint=endpoint)
        with self.assertRaisesRegex(OpenRouterAgenticProtocolError, "provider_request_invalid"):
            _encode_request({"messages": "x" * MAX_OPENROUTER_REQUEST_BYTES})

    def test_no_eligible_endpoint_http_status_is_not_retried(self) -> None:
        self.assertEqual(_http_reason(404), "provider_no_eligible_endpoint")
        self.assertEqual(_http_reason(429), "provider_rate_limited")
        self.assertEqual(_http_reason(401), "provider_authentication_failed")

    def test_transport_delivers_credential_and_requests_auditable_metadata(self) -> None:
        response = _HttpResponse(b'data: {"id":"generation-1"}\n\ndata: [DONE]\n\n')
        opener = _Opener(response)
        transport = OpenRouterAgenticHttpTransport()
        transport._opener = opener

        events = asyncio.run(_transport_events(
            transport,
            EphemeralCredential("fixture-secret"),
        ))

        self.assertEqual(events, [{"id": "generation-1"}])
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer fixture-secret")
        self.assertEqual(opener.request.get_header("X-openrouter-metadata"), "enabled")
        self.assertNotIn("fixture-secret", repr(EphemeralCredential("fixture-secret")))


async def _events(response) -> list[dict[str, object]]:
    return [event async for event in _read_sse(response)]


async def _transport_events(transport, credential) -> list[dict[str, object]]:
    return [
        event
        async for event in transport.stream(
            payload={"model": "fixture"},
            credential=credential,
        )
    ]


if __name__ == "__main__":
    unittest.main()
