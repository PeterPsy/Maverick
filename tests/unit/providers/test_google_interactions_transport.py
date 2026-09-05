from __future__ import annotations

import asyncio
import io
import unittest

from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.providers.google_interactions_transport import (
    MAX_GOOGLE_REQUEST_BYTES,
    GoogleInteractionsHttpTransport,
    _encode_request,
    _read_sse,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.stream = io.BytesIO(payload)

    def readline(self, limit: int) -> bytes:
        return self.stream.readline(limit)


class GoogleInteractionsTransportTest(unittest.TestCase):
    def test_named_sse_events_decode_only_bounded_json_data(self) -> None:
        response = _Response(
            b'event: interaction.created\n'
            b'data: {"event_type":"interaction.created","interaction":{"id":"i-1"}}\n'
            b'\n'
            b'event: done\n'
            b'data: [DONE]\n'
            b'\n'
        )

        events = asyncio.run(_events(response))

        self.assertEqual(events[0]["event_type"], "interaction.created")
        self.assertEqual(events[0]["interaction"]["id"], "i-1")

    def test_incomplete_or_non_object_stream_fails_closed(self) -> None:
        with self.assertRaisesRegex(GoogleInteractionsProtocolError, "provider_response_invalid"):
            asyncio.run(_events(_Response(b'data: []\n\n')))
        with self.assertRaisesRegex(GoogleInteractionsProtocolError, "provider_response_invalid"):
            asyncio.run(_events(_Response(b'data: {"event_type":"interaction.created"}\n\n')))

    def test_transport_pins_https_google_host_and_bounds_request(self) -> None:
        for endpoint in (
            "https://example.com/v1/interactions?alt=sse",
            "https://generativelanguage.googleapis.com/v1/private?alt=sse",
            "https://generativelanguage.googleapis.com/v1/interactions",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                GoogleInteractionsHttpTransport(endpoint=endpoint)
        with self.assertRaisesRegex(GoogleInteractionsProtocolError, "provider_request_invalid"):
            _encode_request({"input": "x" * MAX_GOOGLE_REQUEST_BYTES})


async def _events(response) -> list[dict[str, object]]:
    return [event async for event in _read_sse(response)]


if __name__ == "__main__":
    unittest.main()
