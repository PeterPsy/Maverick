"""Google request-pairing isolation regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from core.providers.agentic_protocol import AgenticToolResult
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from tests.unit.providers.test_google_interactions_codec import (
    _ScriptedTransport,
    _events,
    _request,
    _tool_stream,
)


class GoogleInteractionsPairingCodecTest(unittest.TestCase):
    def test_cross_turn_function_pairing_rejects_new_input_before_transport(self) -> None:
        transport = _ScriptedTransport([_tool_stream("interaction-cross-turn")])
        client = GoogleInteractionsAgenticClient(
            state_mode="stateful",
            transport=transport,
        )
        first = asyncio.run(_events(client, _request("request-cross-turn-1")))
        private = next(
            event.provider_private_state
            for event in first
            if event.event_type == "provider_state"
        )
        exact_input = b"This exact new input must not be ignored."
        request = _request(
            "request-cross-turn-2",
            private_state=private,
            tool_results=(
                AgenticToolResult(
                    "call-1",
                    "fixture_read",
                    "application/json",
                    b'{"value":4}',
                    False,
                ),
            ),
        )
        request = replace(
            request,
            correlation_id="turn-google-new",
            content_blocks=(
                request.content_blocks[0],
                replace(request.content_blocks[1], content=exact_input),
            ),
        )

        rejected = asyncio.run(_events(client, request))

        self.assertEqual(len(transport.payloads), 1)
        self.assertEqual(rejected[0].error_code, "provider_tool_result_pairing_invalid")
        self.assertEqual(request.content_blocks[1].content, exact_input)


if __name__ == "__main__":
    unittest.main()
