from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from core.providers.agentic_protocol import (
    AgenticRequestContentBlock,
    AgenticToolResult,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from tests.unit.providers.test_google_interactions_codec import (
    _events,
    _request,
    _ScriptedTransport,
    _text_stream,
    _tool_stream,
)


class GoogleInteractionsFinalizationCodecTest(unittest.TestCase):
    def test_finalization_omits_tools_and_exports_explicit_system_instruction(self) -> None:
        transport = _ScriptedTransport(
            [
                _tool_stream("interaction-finalize-1"),
                _text_stream("interaction-finalize-2", "done"),
            ]
        )
        client = GoogleInteractionsAgenticClient(
            state_mode="stateful",
            transport=transport,
        )
        first = asyncio.run(_events(client, _request("request-finalize-1")))
        private = next(
            event.provider_private_state
            for event in first
            if event.event_type == "provider_state"
        )
        request = _request(
            "request-finalize-2",
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
            request_phase="finalization",
            tool_definitions=(),
            content_blocks=(
                *request.content_blocks,
                AgenticRequestContentBlock(
                    "request-finalize-2:finalize",
                    "system",
                    "public",
                    "finalization_instruction",
                    "trusted_platform",
                    "text/plain",
                    HOSTED_FINALIZATION_INSTRUCTION.encode(),
                ),
            ),
        )

        events = asyncio.run(_events(client, request))

        self.assertEqual(events[-1].event_type, "completed")
        payload = transport.payloads[1]
        self.assertNotIn("tools", payload)
        self.assertIn(HOSTED_FINALIZATION_INSTRUCTION, payload["system_instruction"])
        self.assertEqual(payload["input"][0]["type"], "function_result")
        final_block = request.content_blocks[-1]
        mutations = (
            replace(
                request,
                request_id="request-finalize-invalid",
                content_blocks=(
                    *request.content_blocks[:-1],
                    replace(final_block, content=b"Produce another tool call."),
                ),
            ),
            replace(
                request,
                request_id="request-finalize-reordered",
                content_blocks=(final_block, *request.content_blocks[:-1]),
            ),
        )
        for invalid in mutations:
            rejected = asyncio.run(_events(client, invalid))
            self.assertEqual(rejected[0].error_code, "provider_request_invalid")
        self.assertEqual(len(transport.payloads), 2)


if __name__ == "__main__":
    unittest.main()
