from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import unittest

from core.providers.agentic_protocol import AgenticRequestContentBlock, AgenticToolResult
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.google_interactions_state import decode_google_interaction_state
from tests.unit.providers.google_interactions_fixture import _events, _ScriptedTransport, _request, _tool_stream, _text_stream, _created, _completed, _public_event


THOUGHT_SIGNATURE = "opaque-google-thought-signature"


class GoogleInteractionsCodecTest(unittest.TestCase):
    def test_unconfigured_client_rejects_request_level_zdr_claims_before_transport(self) -> None:
        transport = _ScriptedTransport([_text_stream("not-sent", "done")])
        client = GoogleInteractionsAgenticClient(transport=transport)
        request = _request("zdr-denied")
        request = replace(request, routing_constraint=replace(
            request.routing_constraint, data_collection_policy="deny", require_zdr=True,
        ))
        events = asyncio.run(_events(client, request))
        self.assertEqual(events[-1].error_code, "provider_routing_not_allowed")
        self.assertEqual(transport.payloads, [])

    def test_distinct_json_sources_are_encoded_as_text_without_losing_block_boundaries(self) -> None:
        transport = _ScriptedTransport([_text_stream("interaction-json", "done")])
        client = GoogleInteractionsAgenticClient(state_mode="stateful", transport=transport)
        request = _request("request-json")
        request = replace(
            request,
            content_blocks=(
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
                    "request-json:attachment",
                    "user",
                    "public",
                    "attachment",
                    "trusted_actor",
                    "application/json",
                    b'{"relative_path":"storage/uploaded/fixture.txt"}',
                ),
            ),
        )

        events = asyncio.run(_events(client, request))

        self.assertEqual(events[-1].event_type, "completed")
        payload = transport.payloads[0]
        self.assertEqual(
            payload["system_instruction"],
            'Use synthetic fixture data only.\n\n{"skill_id":"fixture"}',
        )
        self.assertEqual(
            payload["input"][0]["content"],
            [
                {"type": "text", "text": "Read fixture value four."},
                {
                    "type": "text",
                    "text": '{"relative_path":"storage/uploaded/fixture.txt"}',
                },
            ],
        )

    def test_stateful_function_call_preserves_interaction_and_exact_result_pair(self) -> None:
        transport = _ScriptedTransport([_tool_stream("interaction-1")])
        client = GoogleInteractionsAgenticClient(state_mode="stateful", transport=transport)

        first = asyncio.run(_events(client, _request("request-1")))

        self.assertEqual(
            [event.event_type for event in first],
            ["accepted", "tool_call", "provider_state", "usage", "completed"],
        )
        call = first[1].tool_call
        self.assertEqual((call.provider_tool_call_id, call.provider_tool_name), ("call-1", "fixture_read"))
        self.assertEqual(call.arguments, {"value": 4})
        private = first[2].provider_private_state
        self.assertIsNotNone(private)
        state = decode_google_interaction_state(private, default_mode="stateful")
        self.assertEqual(state.previous_interaction_id, "interaction-1")
        self.assertEqual(state.history, ())
        self.assertEqual(state.pending_function_calls[0].call_id, "call-1")
        self.assertNotIn(
            THOUGHT_SIGNATURE,
            json.dumps([_public_event(event) for event in first if event.event_type != "provider_state"]),
        )

        transport.scripts.append(_text_stream("interaction-2", "done"))
        second_request = _request(
            "request-2",
            private_state=private,
            tool_results=(
                AgenticToolResult(
                    provider_tool_call_id="call-1",
                    provider_tool_name="fixture_read",
                    content_type="application/json",
                    content=b'{"value":4}',
                    is_error=False,
                ),
            ),
        )
        second = asyncio.run(_events(client, second_request))

        payload = transport.payloads[1]
        self.assertEqual(payload["previous_interaction_id"], "interaction-1")
        self.assertEqual(
            payload["input"],
            [
                {
                    "type": "function_result",
                    "name": "fixture_read",
                    "call_id": "call-1",
                    "result": [{"type": "text", "text": '{"value":4}'}],
                }
            ],
        )
        self.assertEqual(second[-2].text, "done")
        final_state = decode_google_interaction_state(
            next(event.provider_private_state for event in second if event.event_type == "provider_state"),
            default_mode="stateful",
        )
        self.assertEqual(final_state.previous_interaction_id, "interaction-2")
        self.assertEqual(final_state.pending_function_calls, ())

    def test_stateless_history_replays_every_model_step_and_signature_exactly(self) -> None:
        transport = _ScriptedTransport([_tool_stream("interaction-stateless-1")])
        client = GoogleInteractionsAgenticClient(state_mode="stateless", transport=transport)

        first = asyncio.run(_events(client, _request("request-stateless-1")))
        private = next(event.provider_private_state for event in first if event.event_type == "provider_state")
        state = decode_google_interaction_state(private, default_mode="stateless")

        self.assertEqual(state.history[0]["type"], "user_input")
        self.assertEqual(
            state.history[1],
            {"type": "thought", "signature": THOUGHT_SIGNATURE},
        )
        self.assertIn(THOUGHT_SIGNATURE, private.content.decode())
        self.assertEqual(
            state.history[2],
            {
                "type": "function_call",
                "id": "call-1",
                "name": "fixture_read",
                "arguments": {"value": 4},
            },
        )
        transport.scripts.append(_text_stream("interaction-stateless-2", "finished"))
        asyncio.run(
            _events(
                client,
                _request(
                    "request-stateless-2",
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
                ),
            )
        )

        payload = transport.payloads[1]
        self.assertIs(payload["store"], False)
        self.assertNotIn("previous_interaction_id", payload)
        self.assertEqual(payload["input"][:3], list(state.history))
        self.assertEqual(payload["input"][3]["call_id"], "call-1")
        self.assertEqual(payload["input"][3]["name"], "fixture_read")

    def test_stateless_stream_accepts_empty_unstored_interaction_id(self) -> None:
        client = GoogleInteractionsAgenticClient(
            state_mode="stateless",
            transport=_ScriptedTransport([_tool_stream("")]),
        )

        events = asyncio.run(_events(client, _request("request-empty-id")))

        self.assertEqual(
            [event.event_type for event in events],
            ["accepted", "tool_call", "provider_state", "usage", "completed"],
        )
        self.assertIsNone(events[0].provider_response_id)
        state = decode_google_interaction_state(
            events[2].provider_private_state,
            default_mode="stateless",
        )
        self.assertIsNone(state.previous_interaction_id)

    def test_mismatched_function_result_fails_before_transport(self) -> None:
        transport = _ScriptedTransport([_tool_stream("interaction-pairing")])
        client = GoogleInteractionsAgenticClient(state_mode="stateful", transport=transport)
        first = asyncio.run(_events(client, _request("request-pairing-1")))
        private = next(event.provider_private_state for event in first if event.event_type == "provider_state")

        result = asyncio.run(
            _events(
                client,
                _request(
                    "request-pairing-2",
                    private_state=private,
                    tool_results=(
                        AgenticToolResult(
                            "wrong-call",
                            "fixture_read",
                            "application/json",
                            b"{}",
                            False,
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(len(transport.payloads), 1)
        self.assertEqual(result[0].event_type, "error")
        self.assertEqual(result[0].error_code, "provider_tool_result_pairing_invalid")

    def test_stream_requires_one_function_call_and_exact_model_identity(self) -> None:
        for event_index in (0, -1):
            with self.subTest(event_index=event_index):
                events = _tool_stream("interaction-parallel")
                events[event_index]["interaction"]["model"] = "wrong-model"
                client = GoogleInteractionsAgenticClient(
                    transport=_ScriptedTransport([events])
                )

                result = asyncio.run(
                    _events(client, _request(f"request-invalid-model:{event_index}"))
                )

                self.assertEqual(result[-1].event_type, "error")
                self.assertEqual(result[-1].error_code, "provider_response_invalid")

    def test_stream_accepts_documented_partial_lifecycle_identity(self) -> None:
        events = _text_stream("interaction-partial", "done")
        events[0]["interaction"].pop("model")
        events[-1]["interaction"].pop("model")
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport([events])
        )

        result = asyncio.run(_events(client, _request("request-partial-model")))

        self.assertEqual(
            [event.event_type for event in result],
            [
                "accepted",
                "text_delta",
                "provider_state",
                "usage",
                "text_final",
                "completed",
            ],
        )
        self.assertEqual(result[-2].text, "done")

    def test_invalid_stream_reports_only_a_bounded_private_diagnostic(self) -> None:
        events = _tool_stream("interaction-diagnostic")
        events[2]["delta"] = {"type": "undocumented_delta", "private": "secret"}
        diagnostics = []
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport([events]),
            response_failure_diagnostic=diagnostics.append,
        )

        result = asyncio.run(_events(client, _request("request-diagnostic")))

        self.assertEqual(result[-1].error_code, "provider_response_invalid")
        self.assertEqual(diagnostics, ["step_delta_unknown_invalid"])
        self.assertNotIn("secret", repr(diagnostics))

    def test_created_model_diagnostic_compares_without_copying_identity(self) -> None:
        events = _tool_stream("interaction-model-resource")
        events[0]["interaction"]["model"] = "models/gemini-3.6-flash"
        diagnostics = []
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport([events]),
            response_failure_diagnostic=diagnostics.append,
        )

        result = asyncio.run(_events(client, _request("request-model-resource")))

        self.assertEqual(result[-1].error_code, "provider_response_invalid")
        self.assertEqual(
            diagnostics,
            ["interaction_created_model_resource_name_invalid"],
        )
        self.assertNotIn("gemini", repr(diagnostics))

    def test_created_id_diagnostic_uses_only_safe_structural_cases(self) -> None:
        cases = (
            ({}, "interaction_created_id_missing_invalid"),
            ({"id": None}, "interaction_created_id_null_invalid"),
            ({"id": 7}, "interaction_created_id_type_invalid"),
            ({"id": ""}, "interaction_created_id_empty_invalid"),
            ({"id": "x" * 4097}, "interaction_created_id_oversize_invalid"),
        )
        for interaction, expected in cases:
            with self.subTest(expected=expected):
                events = _tool_stream("interaction-id-diagnostic")
                events[0]["interaction"] = interaction
                diagnostics = []
                client = GoogleInteractionsAgenticClient(
                    transport=_ScriptedTransport([events]),
                    response_failure_diagnostic=diagnostics.append,
                )

                result = asyncio.run(
                    _events(client, _request(f"request-{expected}"))
                )

                self.assertEqual(
                    result[-1].error_code,
                    "provider_response_invalid",
                )
                self.assertEqual(diagnostics, [expected])
                self.assertNotIn("4097", repr(diagnostics))

    def test_provider_error_before_acceptance_is_normalized(self) -> None:
        for code, reason_code in (
            ("quota_exceeded", "provider_quota_exceeded"),
            ("resource_exhausted", "provider_resource_exhausted"),
            ("rate_limit_exceeded", "provider_rate_limited"),
        ):
            with self.subTest(code=code):
                client = GoogleInteractionsAgenticClient(
                    transport=_ScriptedTransport(
                        [[
                            {"event_type": "error", "error": {"code": code}},
                            RuntimeError("provider stream must not be drained after a terminal error"),
                        ]]
                    )
                )

                result = asyncio.run(
                    _events(client, _request(f"request-provider-error:{code}"))
                )

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].event_type, "error")
                self.assertEqual(result[0].error_code, reason_code)

    def test_documented_terminal_failures_retain_usage_and_report_precise_errors(self) -> None:
        cases = (
            ("incomplete", "provider_output_incomplete", None),
            ("budget_exceeded", "provider_budget_exceeded", None),
            ("cancelled", "provider_cancelled", None),
            ("failed", "provider_resource_exhausted", {"code": "resource_exhausted"}),
            ("failed", "provider_unavailable", None),
        )
        for status, reason_code, provider_error in cases:
            with self.subTest(status=status, reason_code=reason_code):
                completed = _completed(
                    f"interaction-{status}",
                    status,
                    input_tokens=20,
                    output_tokens=128,
                )
                if provider_error is not None:
                    completed["interaction"]["error"] = provider_error
                stream = [
                    _created(f"interaction-{status}"),
                    {
                        "event_type": "interaction.status_update",
                        "interaction_id": f"interaction-{status}",
                        "status": status,
                    },
                    completed,
                ]
                client = GoogleInteractionsAgenticClient(
                    transport=_ScriptedTransport([stream])
                )

                result = asyncio.run(
                    _events(client, _request(f"request-{status}"))
                )

                self.assertEqual(
                    [event.event_type for event in result],
                    ["accepted", "usage", "error"],
                )
                self.assertEqual(result[-1].error_code, reason_code)
                self.assertEqual(result[-2].usage.output_tokens, 128)
                self.assertFalse(
                    any(
                        event.event_type in {"provider_state", "text_final", "completed"}
                        for event in result
                    )
                )


if __name__ == "__main__":
    unittest.main()
