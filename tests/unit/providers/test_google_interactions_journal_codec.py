"""Google call-accounting regressions owned by the provider-step journal."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import unittest

from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.google_interactions_state import decode_google_interaction_state
from tests.unit.providers.test_google_interactions_codec import (
    _ScriptedTransport,
    _events,
    _request,
    _tool_stream,
)


class GoogleInteractionsJournalCodecTest(unittest.TestCase):
    def test_parallel_function_calls_are_all_preserved_and_corrupt_state_fails(self) -> None:
        parallel = _tool_stream("interaction-parallel")
        parallel[-1:-1] = [
            {
                "event_type": "step.start",
                "index": 2,
                "step": {
                    "type": "function_call",
                    "id": "call-2",
                    "name": "fixture_read",
                    "arguments": {"value": 5},
                },
            },
            {"event_type": "step.stop", "index": 2},
        ]
        client = GoogleInteractionsAgenticClient(transport=_ScriptedTransport([parallel]))

        observed = asyncio.run(_events(client, _request("request-parallel")))

        calls = [event.tool_call for event in observed if event.event_type == "tool_call"]
        self.assertEqual(
            [call.provider_tool_call_id for call in calls],
            ["call-1", "call-2"],
        )
        self.assertEqual([call.call_index for call in calls], [0, 1])
        state = decode_google_interaction_state(
            next(
                event.provider_private_state
                for event in observed
                if event.event_type == "provider_state"
            ),
            default_mode="stateful",
        )
        self.assertEqual(
            [call.call_id for call in state.pending_function_calls],
            ["call-1", "call-2"],
        )
        transport = _ScriptedTransport([_tool_stream("interaction-private")])
        client = GoogleInteractionsAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-private-1")))
        private = next(
            event.provider_private_state
            for event in first
            if event.event_type == "provider_state"
        )
        corrupt = replace(private, content=b"{}")
        rejected = asyncio.run(
            _events(client, _request("request-private-2", private_state=corrupt))
        )
        self.assertEqual(rejected[-1].error_code, "provider_private_state_invalid")
        self.assertEqual(len(transport.payloads), 1)

    def test_call_before_terminal_stream_error_remains_observable(self) -> None:
        stream = _tool_stream("interaction-call-before-error")
        stream[-1] = {
            "event_type": "error",
            "error": {"code": "resource_exhausted"},
        }
        events = asyncio.run(
            _events(
                GoogleInteractionsAgenticClient(
                    transport=_ScriptedTransport([stream])
                ),
                _request("request-call-before-error"),
            )
        )

        self.assertEqual(
            [event.tool_call.provider_tool_call_id for event in events if event.tool_call],
            ["call-1"],
        )
        self.assertEqual(events[-1].error_code, "provider_resource_exhausted")

    def test_malformed_function_arguments_remain_observable_for_private_ledger(self) -> None:
        stream = _tool_stream("interaction-malformed")
        stream[5]["delta"]["arguments"] = '{"value":'
        events = asyncio.run(
            _events(
                GoogleInteractionsAgenticClient(
                    transport=_ScriptedTransport([stream])
                ),
                _request("request-malformed"),
            )
        )

        call = next(event.tool_call for event in events if event.tool_call)
        self.assertIsNone(call.arguments)
        self.assertEqual(call.arguments_raw, b'{"value":')
        self.assertEqual(events[-1].event_type, "completed")


if __name__ == "__main__":
    unittest.main()
