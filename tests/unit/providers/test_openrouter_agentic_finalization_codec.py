from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from core.providers.agentic_protocol import (
    AgenticRequestContentBlock,
    AgenticToolResult,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from tests.unit.providers.test_openrouter_agentic_codec import (
    _events,
    _private_state,
    _request,
    _ScriptedTransport,
    _text_stream,
    _tool_stream,
)


def _finalize(request, block_id: str):
    return replace(
        request,
        request_phase="finalization",
        tool_definitions=(),
        content_blocks=(
            *request.content_blocks,
            AgenticRequestContentBlock(
                block_id,
                "system",
                "public",
                "finalization_instruction",
                "trusted_platform",
                "text/plain",
                HOSTED_FINALIZATION_INSTRUCTION.encode(),
            ),
        ),
    )


class OpenRouterAgenticFinalizationCodecTest(unittest.TestCase):
    def test_finalization_forces_tool_choice_none_after_paired_result(self) -> None:
        transport = _ScriptedTransport(
            [
                _tool_stream(
                    "generation-finalize-1",
                    "fixture_read",
                    call_id="call-finalize",
                ),
                _text_stream("generation-finalize-2", "done"),
            ]
        )
        client = OpenRouterAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-finalize-1")))
        request = _finalize(
            _request(
                "request-finalize-2",
                private_state=_private_state(first),
                tool_results=(
                    AgenticToolResult(
                        "call-finalize",
                        "fixture_read",
                        "application/json",
                        b'{"value":4}',
                        False,
                    ),
                ),
            ),
            "request-finalize-2:finalize",
        )

        events = asyncio.run(_events(client, request))

        self.assertEqual(events[-1].event_type, "completed")
        payload = transport.payloads[1]
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertEqual(payload["messages"][-2]["role"], "tool")
        self.assertEqual(
            payload["messages"][-1],
            {"role": "system", "content": HOSTED_FINALIZATION_INSTRUCTION},
        )
        self._assert_mutations_fail_before_transport(client, transport, request)

    def test_initial_finalization_instruction_is_last_wire_message(self) -> None:
        transport = _ScriptedTransport(
            [_text_stream("generation-initial-final", "done")]
        )
        client = OpenRouterAgenticClient(transport=transport)
        request = _finalize(
            _request("request-initial-final"),
            "request-initial-final:finalize",
        )

        events = asyncio.run(_events(client, request))

        self.assertEqual(events[-1].event_type, "completed")
        messages = transport.payloads[0]["messages"]
        self.assertTrue(any(item["role"] == "user" for item in messages[:-1]))
        self.assertEqual(
            messages[-1],
            {"role": "system", "content": HOSTED_FINALIZATION_INSTRUCTION},
        )

    def _assert_mutations_fail_before_transport(self, client, transport, request) -> None:
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
