"""OpenRouter indexed-call and preliminary-ledger codec regressions."""

from __future__ import annotations

import asyncio
import unittest

from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from tests.unit.providers.test_openrouter_agentic_codec import (
    _ScriptedTransport,
    _events,
    _identity,
    _private_state,
    _request,
    _text_stream,
    _tool_result,
    _tool_stream,
)


class OpenRouterAgenticJournalCodecTest(unittest.TestCase):
    def test_fragmented_secondary_tool_proposal_is_preserved_and_paired(self) -> None:
        stream = _tool_stream("generation-serialized", "fixture_read", call_id="call-1")
        stream.insert(1, {
            **_identity("generation-serialized"),
            "choices": [{
                "index": 0,
                "delta": {"tool_calls": [{
                    "index": 1,
                    "id": "call-2",
                    "type": "function",
                    "function": {"name": "fixture_read", "arguments": "{}"},
                }]},
                "finish_reason": None,
            }],
        })
        transport = _ScriptedTransport([
            stream,
            _text_stream("generation-serialized-final", "complete"),
        ])
        client = OpenRouterAgenticClient(transport=transport)

        events = asyncio.run(_events(client, _request("request-serialized")))

        calls = [event.tool_call for event in events if event.event_type == "tool_call"]
        self.assertEqual(
            [call.provider_tool_call_id for call in calls],
            ["call-1", "call-2"],
        )
        self.assertFalse(any(event.event_type == "error" for event in events))
        private = decode_openrouter_chat_state(_private_state(events))
        self.assertEqual(
            [call["id"] for call in private.history[-1]["tool_calls"]],
            ["call-1", "call-2"],
        )
        final = asyncio.run(_events(
            client,
            _request(
                "request-serialized-final",
                private_state=_private_state(events),
                tool_results=(_tool_result("call-1"), _tool_result("call-2")),
            ),
        ))
        self.assertEqual(final[-2].text, "complete")
        self.assertEqual(
            [call["id"] for call in transport.payloads[1]["messages"][-3]["tool_calls"]],
            ["call-1", "call-2"],
        )

    def test_mismatched_result_upstream_metadata_and_parallel_calls_fail_closed(self) -> None:
        transport = _ScriptedTransport([_tool_stream("generation-pair", "fixture_read")])
        client = OpenRouterAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-pair-1")))
        rejected = asyncio.run(
            _events(
                client,
                _request(
                    "request-pair-2",
                    private_state=_private_state(first),
                    tool_results=(_tool_result("wrong-call"),),
                ),
            )
        )
        self.assertEqual(rejected[0].error_code, "provider_tool_result_pairing_invalid")
        self.assertEqual(len(transport.payloads), 1)

        wrong = _text_stream("generation-wrong", "text")
        wrong[-1]["openrouter_metadata"]["endpoints"]["available"][0]["provider"] = "Other"
        events = asyncio.run(
            _events(OpenRouterAgenticClient(transport=_ScriptedTransport([wrong])), _request("wrong"))
        )
        self.assertEqual(events[-1].error_code, "provider_upstream_not_certified")

        parallel = _tool_stream("generation-parallel", "fixture_read")
        parallel[0]["choices"][0]["delta"]["tool_calls"].append({
            "index": 0,
            "id": "call-2",
            "type": "function",
            "function": {"name": "fixture_read", "arguments": "{}"},
        })
        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([parallel])),
                _request("parallel"),
            )
        )
        self.assertEqual(events[-1].error_code, "provider_response_invalid")

        invalid_index = _tool_stream("generation-index", "fixture_read")
        invalid_index[0]["choices"][0]["delta"]["tool_calls"][0]["index"] = 1
        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([invalid_index])),
                _request("invalid-index"),
            )
        )
        self.assertEqual(events[-1].error_code, "provider_response_invalid")

    def test_calls_before_bad_terminal_metadata_remain_observable(self) -> None:
        stream = _tool_stream("generation-call-before-error", "fixture_read")
        stream[-1]["openrouter_metadata"]["endpoints"]["available"][0][
            "provider"
        ] = "Other"
        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([stream])),
                _request("request-call-before-error"),
            )
        )

        self.assertEqual(
            [event.tool_call.provider_tool_call_id for event in events if event.tool_call],
            ["call-1"],
        )
        self.assertEqual(events[-1].error_code, "provider_upstream_not_certified")

    def test_malformed_tool_arguments_remain_observable_for_private_ledger(self) -> None:
        stream = _tool_stream("generation-malformed", "fixture_read")
        stream[0]["choices"][0]["delta"]["tool_calls"][0]["function"][
            "arguments"
        ] = '{"value":'
        stream[1]["choices"][0]["delta"]["tool_calls"][0]["function"][
            "arguments"
        ] = ""
        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([stream])),
                _request("request-malformed"),
            )
        )

        call = next(event.tool_call for event in events if event.tool_call)
        self.assertIsNone(call.arguments)
        self.assertEqual(call.arguments_raw, b'{"value":')
        self.assertEqual(events[-1].event_type, "completed")


if __name__ == "__main__":
    unittest.main()
