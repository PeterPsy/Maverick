"""OpenRouter mixed text/tool streaming regressions."""

from __future__ import annotations

import asyncio
import json
import unittest

from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from tests.unit.providers.test_openrouter_agentic_codec import (
    REASONING_DETAIL,
    _ScriptedTransport,
    _events,
    _identity,
    _private_state,
    _request,
    _text_stream,
    _tool_result,
    _tool_stream,
)


class OpenRouterAgenticMixedStreamTest(unittest.TestCase):
    def test_single_tool_after_text_is_provisional_and_replays_without_duplication(self) -> None:
        transport = _ScriptedTransport(
            [
                _mixed_tool_stream(
                    "generation-mixed-1",
                    "fixture_read",
                    narration="I will inspect the repository first. ",
                ),
                _text_stream("generation-mixed-2", "Final answer only."),
            ]
        )
        client = OpenRouterAgenticClient(transport=transport)

        first = asyncio.run(_events(client, _request("request-mixed-1")))
        second = asyncio.run(
            _events(
                client,
                _request(
                    "request-mixed-2",
                    private_state=_private_state(first),
                    tool_results=(_tool_result("call-1"),),
                ),
            )
        )

        self.assertFalse(any(event.event_type == "text_delta" for event in first))
        mixed_assistant = transport.payloads[1]["messages"][-2]
        self.assertEqual(
            mixed_assistant["content"],
            "I will inspect the repository first. ",
        )
        self.assertEqual(mixed_assistant["tool_calls"][0]["id"], "call-1")
        visible_text = "".join(
            event.text or ""
            for event in (*first, *second)
            if event.event_type == "text_delta"
        )
        self.assertEqual(visible_text, "Final answer only.")

    def test_decode_failure_keeps_generation_identity_and_late_usage(self) -> None:
        stream = _invalid_index_stream("generation-failed")
        client = OpenRouterAgenticClient(transport=_ScriptedTransport([stream]))

        events = asyncio.run(_events(client, _request("request-failed-telemetry")))

        accepted = next(event for event in events if event.event_type == "accepted")
        self.assertEqual(accepted.provider_response_id, "generation-failed")
        usage = next(event.usage for event in events if event.event_type == "usage")
        self.assertEqual((usage.input_tokens, usage.output_tokens), (100, 10))
        self.assertEqual(events[-1].error_code, "provider_response_invalid")

    def test_decode_failure_survives_interrupted_telemetry_drain(self) -> None:
        stream = _invalid_index_stream("generation-interrupted")
        stream.append(RuntimeError("synthetic transport interruption"))

        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([stream])),
                _request("request-interrupted"),
            )
        )

        self.assertEqual(events[-1].error_code, "provider_response_invalid")

    def test_incompatible_mixed_finish_is_not_reported_as_parallel(self) -> None:
        stream = _mixed_tool_stream(
            "generation-mixed-invalid",
            "fixture_read",
            narration="provisional",
        )
        stream[-1]["choices"][0]["finish_reason"] = "stop"

        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([stream])),
                _request("request-mixed-invalid"),
            )
        )

        self.assertEqual(
            [event.tool_call.provider_tool_call_id for event in events if event.tool_call],
            ["call-1"],
        )
        self.assertEqual(events[-1].error_code, "provider_mixed_text_and_tool_call")


def _invalid_index_stream(generation_id: str) -> list[dict[str, object]]:
    stream = _mixed_tool_stream(
        generation_id,
        "fixture_read",
        narration="provisional",
    )
    stream[1]["choices"][0]["delta"]["tool_calls"][0]["index"] = 1
    return stream


def _mixed_tool_stream(
    generation_id: str,
    tool_name: str,
    *,
    narration: str,
) -> list[dict[str, object]]:
    stream = _tool_stream(generation_id, tool_name)
    encoded_arguments = json.dumps({"value": 4}, separators=(",", ":"))
    split_at = max(1, len(encoded_arguments) // 2)
    stream[0] = {
        **_identity(generation_id),
        "choices": [{
            "index": 0,
            "delta": {
                "role": "assistant",
                "content": narration,
                "reasoning_details": [dict(REASONING_DETAIL)],
            },
            "finish_reason": None,
        }],
    }
    stream.insert(
        1,
        {
            **_identity(generation_id),
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": encoded_arguments[:split_at],
                        },
                    }],
                },
                "finish_reason": None,
            }],
        },
    )
    return stream


if __name__ == "__main__":
    unittest.main()
