from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import unittest

from core.providers.agentic_models import codex_routing_constraint
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    AgenticToolResult,
    EphemeralCredential,
)
from core.providers.google_agentic_profile import google_interactions_routing_constraint
from core.providers.google_interactions_client import (
    GoogleInteractionsAgenticClient,
    google_36_flash_request_ceiling_microusd,
)
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_CONTENT_TYPE,
    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
)
from core.providers.google_interactions_state import decode_google_interaction_state
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from tests.support.hosted_agentic_harness import HostedAgenticHarness


THOUGHT_SIGNATURE = "opaque-google-thought-signature"


class GoogleInteractionsCodecTest(unittest.TestCase):
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
        events = _tool_stream("interaction-parallel")
        events[0]["interaction"]["model"] = "wrong-model"
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport([events])
        )

        result = asyncio.run(_events(client, _request("request-invalid-model")))

        self.assertEqual(result[-1].event_type, "error")
        self.assertEqual(result[-1].error_code, "provider_response_invalid")

    def test_parallel_function_calls_and_corrupt_private_state_fail_closed(self) -> None:
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

        rejected = asyncio.run(_events(client, _request("request-parallel")))

        self.assertEqual(rejected[-1].error_code, "provider_parallel_tool_calls_forbidden")
        transport = _ScriptedTransport([_tool_stream("interaction-private")])
        client = GoogleInteractionsAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-private-1")))
        private = next(event.provider_private_state for event in first if event.event_type == "provider_state")
        corrupt = replace(private, content=b"{}")
        rejected = asyncio.run(
            _events(client, _request("request-private-2", private_state=corrupt))
        )
        self.assertEqual(rejected[-1].error_code, "provider_private_state_invalid")
        self.assertEqual(len(transport.payloads), 1)

    def test_provider_error_before_acceptance_is_normalized(self) -> None:
        client = GoogleInteractionsAgenticClient(
            transport=_ScriptedTransport(
                [[{"event_type": "error", "error": {"code": "RESOURCE_EXHAUSTED"}}]]
            )
        )

        result = asyncio.run(_events(client, _request("request-provider-error")))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].event_type, "error")
        self.assertEqual(result[0].error_code, "provider_rate_limited")

    def test_real_google_codec_runs_through_shared_tool_loop(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="google-ai-studio",
            model_id="gemini-3.6-flash",
            provider_protocol="google-interactions",
            routing_constraint=google_interactions_routing_constraint(),
        )
        transport = _ScriptedTransport(
            [
                _tool_stream("interaction-loop-1", tool_name=harness.read_tool_name),
                _text_stream("interaction-loop-2", "google fixture answer"),
            ]
        )
        client = GoogleInteractionsAgenticClient(transport=transport)
        adapter = harness.adapter(
            client,
            private_codec=HostedProviderPrivateCodec(
                GOOGLE_INTERACTIONS_CODEC_ID,
                GOOGLE_INTERACTIONS_CODEC_VERSION,
                GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                GOOGLE_INTERACTIONS_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-google-key"),
            cost_estimator=google_36_flash_request_ceiling_microusd,
        )
        public_events = []

        result = execute_runtime_turn(
            session=harness.session,
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
            event_sink=public_events.append,
        )

        self.assertEqual(result.output_text, "google fixture answer")
        self.assertEqual(harness.cli_calls, 1)
        self.assertEqual(len(transport.payloads), 2)
        self.assertEqual(transport.payloads[1]["previous_interaction_id"], "interaction-loop-1")
        self.assertEqual(transport.payloads[1]["input"][0]["call_id"], "call-1")
        self.assertNotIn(
            THOUGHT_SIGNATURE,
            json.dumps([event.payload for event in public_events], default=str),
        )

        stateless = HostedAgenticHarness(
            self,
            model_provider_id="google-ai-studio",
            model_id="gemini-3.6-flash",
            provider_protocol="google-interactions",
            routing_constraint=google_interactions_routing_constraint(),
        )
        stateless_transport = _ScriptedTransport(
            [
                _tool_stream("stateless-loop-1", tool_name=stateless.read_tool_name),
                _text_stream("stateless-loop-2", "stateless answer"),
            ]
        )
        stateless_events = []
        stateless_adapter = stateless.adapter(
            GoogleInteractionsAgenticClient(
                state_mode="stateless",
                transport=stateless_transport,
            ),
            private_codec=adapter.loop.provider_runtimes.resolve(harness.binding).private_codec,
            credential=EphemeralCredential("fixture-google-key"),
            cost_estimator=google_36_flash_request_ceiling_microusd,
        )
        execute_runtime_turn(
            session=stateless.session,
            provider=stateless.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=stateless_adapter,
            provider_state=stateless.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=stateless.authority,
            event_sink=stateless_events.append,
        )
        self.assertNotIn("previous_interaction_id", stateless_transport.payloads[1])
        self.assertIn(THOUGHT_SIGNATURE, json.dumps(stateless_transport.payloads[1]))
        self.assertNotIn(
            THOUGHT_SIGNATURE,
            json.dumps([event.payload for event in stateless_events], default=str),
        )
        self.assertTrue(
            all(
                THOUGHT_SIGNATURE.encode() not in path.read_bytes()
                for path in stateless.root.glob("workspaces/default/runtime/sessions/**/*.json")
            )
        )

class _ScriptedTransport:
    def __init__(
        self,
        scripts: list[list[dict[str, object] | BaseException]],
    ) -> None:
        self.scripts = scripts
        self.payloads: list[dict[str, object]] = []

    async def stream(self, *, payload, credential):
        self.payloads.append(payload)
        self.assert_credential_redacted = "test-key" not in repr(credential)
        script = self.scripts.pop(0)
        for event in script:
            if isinstance(event, BaseException):
                raise event
            yield event


async def _events(client, request):
    return [
        event
        async for event in client.create_response(
            request,
            credential=EphemeralCredential("test-key"),
        )
    ]


def _request(
    request_id: str,
    *,
    private_state=None,
    tool_results: tuple[AgenticToolResult, ...] = (),
) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id=request_id,
        correlation_id="turn-google",
        model_id="gemini-3.6-flash",
        reasoning_effort="medium",
        content_blocks=(
            AgenticRequestContentBlock(
                f"{request_id}:system",
                "system",
                "workspace_internal_fake",
                "platform_instruction",
                "trusted_platform",
                "text/plain",
                b"Use synthetic fixture data only.",
            ),
            AgenticRequestContentBlock(
                f"{request_id}:user",
                "user",
                "workspace_internal_fake",
                "user_input",
                "trusted_actor",
                "text/plain",
                b"Read fixture value four.",
            ),
        ),
        tool_definitions=(
            AgenticToolDefinition(
                "fixture_read",
                "Read a synthetic fixture.",
                {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            ),
        ),
        tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=codex_routing_constraint(),
        max_output_tokens=256,
    )


def _tool_stream(
    interaction_id: str,
    *,
    tool_name: str = "fixture_read",
) -> list[dict[str, object]]:
    return [
        _created(interaction_id),
        {"event_type": "step.start", "index": 0, "step": {"type": "thought"}},
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "thought_signature", "signature": THOUGHT_SIGNATURE},
        },
        {"event_type": "step.stop", "index": 0},
        {
            "event_type": "step.start",
            "index": 1,
            "step": {"type": "function_call", "id": "call-1", "name": tool_name, "arguments": {}},
        },
        {
            "event_type": "step.delta",
            "index": 1,
            "delta": {"type": "arguments_delta", "arguments": '{"value":4}'},
        },
        {"event_type": "step.stop", "index": 1},
        _completed(interaction_id, "requires_action", input_tokens=20, output_tokens=4),
    ]


def _text_stream(interaction_id: str, text: str) -> list[dict[str, object]]:
    return [
        _created(interaction_id),
        {"event_type": "step.start", "index": 0, "step": {"type": "model_output"}},
        {"event_type": "step.delta", "index": 0, "delta": {"type": "text", "text": text}},
        {"event_type": "step.stop", "index": 0},
        _completed(interaction_id, "completed", input_tokens=30, output_tokens=2),
    ]


def _created(interaction_id: str) -> dict[str, object]:
    return {
        "event_type": "interaction.created",
        "interaction": {"id": interaction_id, "model": "gemini-3.6-flash", "status": "in_progress"},
    }


def _completed(interaction_id: str, status: str, *, input_tokens: int, output_tokens: int):
    return {
        "event_type": "interaction.completed",
        "interaction": {
            "id": interaction_id,
            "model": "gemini-3.6-flash",
            "status": status,
            "usage": {
                "total_input_tokens": input_tokens,
                "total_output_tokens": output_tokens,
            },
        },
    }


def _public_event(event) -> dict[str, object]:
    return {
        "event_type": event.event_type,
        "text": event.text,
        "tool_call": None if event.tool_call is None else event.tool_call.arguments,
        "error_code": event.error_code,
    }


if __name__ == "__main__":
    unittest.main()
