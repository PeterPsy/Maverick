from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import unittest

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    AgenticToolResult,
    EphemeralCredential,
)
from core.providers.openrouter_agentic_client import (
    OpenRouterAgenticClient,
    openrouter_deepinfra_v4_flash_request_ceiling_microusd,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_MODEL_ID,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
    OPENROUTER_AGENTIC_UPSTREAM_ID,
)
from core.providers.openrouter_agentic_profile import openrouter_agentic_routing_constraint
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.execution import execute_runtime_turn
from tests.support.hosted_agentic_harness import HostedAgenticHarness


REASONING_DETAIL = {
    "type": "reasoning.text",
    "text": "private fixture reasoning",
    "signature": "private-signature",
    "id": "reasoning-1",
    "format": "openrouter",
    "index": 0,
}


class OpenRouterAgenticCodecTest(unittest.TestCase):
    def test_accepts_empty_terminal_usage_chunk_repeating_finish_reason(self) -> None:
        stream = _tool_stream("generation-terminal-usage", "maverick_probe_echo")
        terminal = stream[-1]
        stream[-1] = {
            **_identity("generation-terminal-usage"),
            "choices": terminal["choices"],
        }
        stream.append({
            **_identity("generation-terminal-usage"),
            "choices": [{
                "index": 0,
                "delta": {"role": None, "content": None},
                "finish_reason": "tool_calls",
            }],
            "usage": terminal["usage"],
            "openrouter_metadata": terminal["openrouter_metadata"],
        })
        client = OpenRouterAgenticClient(transport=_ScriptedTransport([stream]))

        events = asyncio.run(_events(client, _request("request-terminal-usage")))

        self.assertEqual(events[-1].event_type, "completed")
        self.assertFalse(any(event.event_type == "error" for event in events))

    def test_request_pins_every_router_control(self) -> None:
        transport = _ScriptedTransport([_text_stream("generation-routing", "answer")])
        client = OpenRouterAgenticClient(transport=transport)

        events = asyncio.run(_events(client, _request("request-routing")))

        self.assertEqual(events[-1].event_type, "completed")
        payload = transport.payloads[0]
        self.assertEqual(payload["model"], OPENROUTER_AGENTIC_MODEL_ID)
        self.assertEqual(
            payload["provider"],
            {
                "only": ["deepinfra/fp8"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
                "quantizations": ["fp8"],
            },
        )
        self.assertEqual(payload["reasoning"], {"effort": "medium"})
        self.assertEqual(payload["stream_options"], {"include_usage": True})

    def test_any_relaxed_router_control_fails_before_transport(self) -> None:
        certified = openrouter_agentic_routing_constraint()
        variants = (
            replace(certified, endpoint_id="another-endpoint"),
            replace(certified, allowed_upstream_ids=("deepinfra",)),
            replace(certified, allow_fallbacks=True),
            replace(certified, require_parameters=False),
            replace(certified, data_collection_policy="provider_contract"),
            replace(certified, require_zdr=False),
            replace(certified, allowed_quantizations=()),
        )
        for index, routing in enumerate(variants):
            with self.subTest(index=index):
                transport = _ScriptedTransport([])
                events = asyncio.run(
                    _events(
                        OpenRouterAgenticClient(transport=transport),
                        replace(_request(f"request-relaxed-{index}"), routing_constraint=routing),
                    )
                )
                self.assertEqual(events[0].error_code, "provider_routing_not_certified")
                self.assertEqual(transport.payloads, [])

    def test_text_stream_verifies_upstream_and_keeps_reasoning_private(self) -> None:
        client = OpenRouterAgenticClient(
            transport=_ScriptedTransport([_text_stream("generation-text", "final answer")])
        )

        events = asyncio.run(_events(client, _request("request-text")))

        self.assertEqual(events[0].event_type, "accepted")
        self.assertEqual(events[0].upstream_id, OPENROUTER_AGENTIC_UPSTREAM_ID)
        self.assertEqual(
            "".join(event.text or "" for event in events if event.event_type == "text_delta"),
            "final answer",
        )
        usage = next(event.usage for event in events if event.event_type == "usage")
        self.assertEqual((usage.input_tokens, usage.output_tokens), (120, 12))
        self.assertEqual(usage.estimated_cost_microusd, 13)
        private = next(
            event.provider_private_state
            for event in events
            if event.event_type == "provider_state"
        )
        state = decode_openrouter_chat_state(private)
        self.assertEqual(state.history[-1]["reasoning_details"], [REASONING_DETAIL])
        public = [event for event in events if event.event_type != "provider_state"]
        self.assertNotIn("private fixture reasoning", repr(public))
        self.assertNotIn("private-signature", repr(public))

    def test_tool_result_replays_exact_assistant_state_and_supports_next_tool_round(self) -> None:
        transport = _ScriptedTransport(
            [
                _tool_stream("generation-tool-1", "fixture_read", call_id="call-1"),
                _tool_stream("generation-tool-2", "fixture_read", call_id="call-2"),
                _text_stream("generation-tool-3", "complete"),
            ]
        )
        client = OpenRouterAgenticClient(transport=transport)
        first = asyncio.run(_events(client, _request("request-tool-1")))
        first_private = _private_state(first)
        second = asyncio.run(
            _events(
                client,
                _request(
                    "request-tool-2",
                    private_state=first_private,
                    tool_results=(_tool_result("call-1"),),
                ),
            )
        )
        second_private = _private_state(second)
        third = asyncio.run(
            _events(
                client,
                _request(
                    "request-tool-3",
                    private_state=second_private,
                    tool_results=(_tool_result("call-1"), _tool_result("call-2")),
                ),
            )
        )

        second_messages = transport.payloads[1]["messages"]
        self.assertEqual(second_messages[-2]["tool_calls"][0]["id"], "call-1")
        self.assertEqual(second_messages[-2]["reasoning_details"], [REASONING_DETAIL])
        self.assertEqual(second_messages[-1], {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"value":4}',
        })
        self.assertEqual(transport.payloads[2]["messages"][-1]["tool_call_id"], "call-2")
        final_state = decode_openrouter_chat_state(_private_state(third))
        self.assertEqual(final_state.pending_tool_call, None)
        self.assertEqual(final_state.consumed_tool_call_ids, ("call-1", "call-2"))
        self.assertEqual(third[-2].text, "complete")

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
            "index": 1,
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
        self.assertEqual(events[-1].error_code, "provider_parallel_tool_calls_forbidden")

    def test_no_eligible_endpoint_is_a_stable_fail_closed_error(self) -> None:
        payload = {
            "error": {
                "code": 404,
                "message": "No allowed providers are available.",
                "metadata": {"error_type": "no_available_provider"},
            }
        }
        events = asyncio.run(
            _events(
                OpenRouterAgenticClient(transport=_ScriptedTransport([[payload]])),
                _request("request-no-endpoint"),
            )
        )
        self.assertEqual(events[0].error_code, "provider_no_eligible_endpoint")

    def test_real_codec_runs_through_shared_tool_loop(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="openrouter",
            model_id=OPENROUTER_AGENTIC_MODEL_ID,
            provider_protocol="openrouter-chat-completions",
            routing_constraint=openrouter_agentic_routing_constraint(),
        )
        transport = _ScriptedTransport([
            _tool_stream("generation-loop-1", harness.read_tool_name),
            _text_stream("generation-loop-2", "OpenRouter fixture answer"),
        ])
        adapter = harness.adapter(
            OpenRouterAgenticClient(transport=transport),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            credential=EphemeralCredential("fixture-openrouter-key"),
            cost_estimator=openrouter_deepinfra_v4_flash_request_ceiling_microusd,
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

        self.assertEqual(result.output_text, "OpenRouter fixture answer")
        self.assertEqual(harness.cli_calls, 1)
        self.assertEqual(transport.payloads[1]["provider"]["only"], ["deepinfra/fp8"])
        serialized = json.dumps([event.payload for event in public_events], default=str)
        self.assertNotIn("private fixture reasoning", serialized)
        self.assertNotIn("private-signature", serialized)


class _ScriptedTransport:
    def __init__(self, scripts: list[list[dict[str, object]]]) -> None:
        self.scripts = scripts
        self.payloads: list[dict[str, object]] = []

    async def stream(self, *, payload, credential):
        self.payloads.append(payload)
        if "fixture-openrouter-key" in repr(credential):
            raise AssertionError("credential leaked through repr")
        for event in self.scripts.pop(0):
            yield event


async def _events(client, request):
    return [
        event
        async for event in client.create_response(
            request,
            credential=EphemeralCredential("test-key"),
        )
    ]


def _request(request_id: str, *, private_state=None, tool_results=()) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id=request_id,
        correlation_id="turn-openrouter",
        model_id=OPENROUTER_AGENTIC_MODEL_ID,
        reasoning_effort="medium",
        content_blocks=(
            AgenticRequestContentBlock(
                f"{request_id}:system", "system", "workspace_internal_fake",
                "platform_instruction", "trusted_platform", "text/plain",
                b"Use synthetic fixture data only.",
            ),
            AgenticRequestContentBlock(
                f"{request_id}:user", "user", "workspace_internal_fake",
                "user_input", "trusted_actor", "text/plain", b"Read fixture value four.",
            ),
        ),
        tool_definitions=(AgenticToolDefinition(
            "fixture_read",
            "Read a synthetic fixture.",
            {"type": "object", "properties": {"value": {"type": "integer"}}},
        ),),
        tool_results=tool_results,
        provider_private_state=private_state,
        routing_constraint=openrouter_agentic_routing_constraint(),
        max_output_tokens=1024,
    )


def _tool_result(call_id: str) -> AgenticToolResult:
    return AgenticToolResult(call_id, "fixture_read", "application/json", b'{"value":4}', False)


def _private_state(events):
    return next(
        event.provider_private_state
        for event in events
        if event.event_type == "provider_state"
    )


def _identity(generation_id: str) -> dict[str, object]:
    return {
        "id": generation_id,
        "object": "chat.completion.chunk",
        "model": OPENROUTER_AGENTIC_MODEL_ID,
        "provider": "DeepInfra",
    }


def _metadata() -> dict[str, object]:
    return {
        "requested": OPENROUTER_AGENTIC_MODEL_ID,
        "strategy": "direct",
        "attempt": 1,
        "endpoints": {"total": 1, "available": [{
            "provider": "DeepInfra",
            "model": OPENROUTER_AGENTIC_MODEL_ID,
            "selected": True,
        }]},
        "attempts": [{
            "provider": "DeepInfra",
            "model": OPENROUTER_AGENTIC_MODEL_ID,
            "status": 200,
        }],
    }


def _text_stream(generation_id: str, text: str) -> list[dict[str, object]]:
    return [
        {
            **_identity(generation_id),
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": text,
                    "reasoning_details": [dict(REASONING_DETAIL)],
                },
                "finish_reason": None,
            }],
        },
        {
            **_identity(generation_id),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 12},
            "openrouter_metadata": _metadata(),
        },
    ]


def _tool_stream(
    generation_id: str,
    tool_name: str,
    *,
    call_id: str = "call-1",
) -> list[dict[str, object]]:
    return [
        {
            **_identity(generation_id),
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "reasoning_details": [dict(REASONING_DETAIL)],
                    "tool_calls": [{
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": '{"value":'},
                    }],
                },
                "finish_reason": None,
            }],
        },
        {
            **_identity(generation_id),
            "choices": [{
                "index": 0,
                "delta": {"tool_calls": [{
                    "index": 0,
                    "function": {"arguments": "4}"},
                }]},
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10},
            "openrouter_metadata": _metadata(),
        },
    ]


if __name__ == "__main__":
    unittest.main()
