"""OpenRouter request-pairing isolation regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from tests.unit.providers.test_openrouter_agentic_codec import (
    _ScriptedTransport,
    _events,
    _private_state,
    _request,
    _tool_result,
    _tool_stream,
)


class OpenRouterAgenticPairingCodecTest(unittest.TestCase):
    def test_cross_turn_tool_pairing_rejects_new_input_before_transport(self) -> None:
        transport = _ScriptedTransport(
            [_tool_stream("generation-cross-turn", "fixture_read", call_id="call-1")]
        )
        client = OpenRouterAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-cross-turn-1")))
        private = _private_state(first)
        exact_input = b"This exact new input must not be ignored."
        request = _request(
            "request-cross-turn-2",
            private_state=private,
            tool_results=(_tool_result("call-1"),),
        )
        request = replace(
            request,
            correlation_id="turn-openrouter-new",
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
