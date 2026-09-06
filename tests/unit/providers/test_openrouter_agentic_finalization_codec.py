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
from core.providers.agentic_probe_validation import validate_probe_response
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
    def test_finalization_omits_tools_and_choice_after_paired_result(self) -> None:
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
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)
        self.assertEqual(payload["messages"][-2]["role"], "tool")
        self.assertEqual(
            payload["messages"][-1],
            {"role": "system", "content": HOSTED_FINALIZATION_INSTRUCTION},
        )
        self._assert_mutations_fail_before_transport(client, transport, request)

    def test_unsolicited_final_tool_proposal_remains_pairable_but_is_not_probe_success(self) -> None:
        transport = _ScriptedTransport([_tool_stream("generation-unsolicited", "fixture_read", call_id="call-denied")])
        client = OpenRouterAgenticClient(transport=transport)
        request = _finalize(_request("request-unsolicited"), "request-unsolicited:finalize")
        events = asyncio.run(_events(client, request))
        # Protocol completion is not user-turn completion. Preserve the exact
        # pending state for core budget_denied pairing and the protected recovery.
        self.assertFalse(validate_probe_response(events, final=True))
        self.assertTrue(any(event.event_type == "provider_state" for event in events))
        self.assertTrue(any(event.event_type == "tool_call" for event in events))

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

    def test_finalization_instruction_is_not_replayed_on_the_next_turn(self) -> None:
        transport = _ScriptedTransport(
            [
                _tool_stream(
                    "generation-transient-1",
                    "fixture_read",
                    call_id="call-transient",
                ),
                _text_stream("generation-transient-2", "first turn done"),
                _text_stream("generation-transient-3", "next turn done"),
            ]
        )
        client = OpenRouterAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-transient-1")))
        final = _finalize(
            _request(
                "request-transient-2",
                private_state=_private_state(first),
                tool_results=(
                    AgenticToolResult(
                        "call-transient",
                        "fixture_read",
                        "application/json",
                        b'{"value":4}',
                        False,
                    ),
                ),
            ),
            "request-transient-2:finalize",
        )
        finalized = asyncio.run(_events(client, final))

        next_turn = _request(
            "request-transient-3",
            private_state=_private_state(finalized),
        )
        events = asyncio.run(_events(client, next_turn))

        self.assertEqual(events[-1].event_type, "completed")
        payload = transport.payloads[-1]
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(payload["tools"])
        self.assertFalse(
            any(
                item.get("content") == HOSTED_FINALIZATION_INSTRUCTION
                for item in payload["messages"]
            )
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
