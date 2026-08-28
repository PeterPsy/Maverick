from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from core.providers.agentic_protocol import AgenticRequestContentBlock
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from tests.unit.providers.test_openrouter_agentic_codec import (
    _ScriptedTransport,
    _events,
    _private_state,
    _request,
    _tool_result,
    _tool_stream,
    _text_stream,
)


class OpenRouterInputCompositionTest(unittest.TestCase):
    def test_changed_authority_block_is_reinjected_during_tool_continuation(self) -> None:
        transport = _ScriptedTransport(
            [
                _tool_stream("generation-policy-1", "fixture_read"),
                _text_stream("generation-policy-2", "complete"),
            ]
        )
        client = OpenRouterAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-policy-1")))
        continuation = _request(
            "request-policy-2",
            private_state=_private_state(first),
            tool_results=(_tool_result("call-1"),),
        )
        continuation = replace(
            continuation,
            content_blocks=(
                replace(
                    continuation.content_blocks[0],
                    content=b"New platform policy.",
                ),
                AgenticRequestContentBlock(
                    "request-policy-2:workspace",
                    "developer",
                    "public",
                    "workspace_instruction",
                    "trusted_actor",
                    "text/plain",
                    b"New nested AGENTS policy.",
                ),
                continuation.content_blocks[1],
            ),
        )

        events = asyncio.run(_events(client, continuation))

        messages = transport.payloads[1]["messages"]
        system = next(item for item in messages if item["role"] == "system")
        self.assertEqual(
            system["content"],
            "New platform policy.\n\nNew nested AGENTS policy.",
        )
        self.assertNotIn("Use synthetic fixture data only.", repr(messages))
        self.assertEqual(messages[-1]["role"], "tool")
        persisted = decode_openrouter_chat_state(_private_state(events))
        self.assertEqual(persisted.history[0], system)

    def test_distinct_json_sources_form_one_stable_system_message_across_continuation(self) -> None:
        transport = _ScriptedTransport(
            [
                _text_stream("generation-json-1", "first"),
                _text_stream("generation-json-2", "second"),
            ]
        )
        client = OpenRouterAgenticClient(transport=transport)
        request = _request("request-json-1")
        blocks = (
            request.content_blocks[0],
            AgenticRequestContentBlock(
                "request-json:skill",
                "system",
                "public",
                "skill",
                "trusted_actor",
                "application/json",
                b'{"skill_id":"fixture"}',
            ),
            request.content_blocks[1],
            AgenticRequestContentBlock(
                "request-json:app-reference",
                "user",
                "public",
                "app_reference",
                "trusted_actor",
                "application/json",
                b'{"app_id":"crm"}',
            ),
        )
        first = asyncio.run(_events(client, replace(request, content_blocks=blocks)))
        second_request = replace(
            _request("request-json-2", private_state=_private_state(first)),
            content_blocks=blocks,
        )

        second = asyncio.run(_events(client, second_request))

        self.assertEqual(second[-1].event_type, "completed")
        self.assertEqual(
            transport.payloads[0]["messages"][:3],
            [
                {
                    "role": "system",
                    "content": 'Use synthetic fixture data only.\n\n{"skill_id":"fixture"}',
                },
                {"role": "user", "content": "Read fixture value four."},
                {"role": "user", "content": '{"app_id":"crm"}'},
            ],
        )
        self.assertEqual(
            sum(
                message.get("role") == "system"
                for message in transport.payloads[1]["messages"]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
