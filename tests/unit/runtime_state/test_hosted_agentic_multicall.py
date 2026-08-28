from __future__ import annotations

import json
import unittest

from core.providers.agentic_protocol import EphemeralCredential
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
from core.providers.google_interactions_state import inspect_google_interaction_state
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
)
from core.providers.openrouter_agentic_profile import openrouter_agentic_routing_constraint
from core.providers.openrouter_agentic_state import inspect_openrouter_chat_state
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class _ScriptedTransport:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.payloads = []

    async def stream(self, *, payload, credential):
        self.payloads.append(payload)
        for item in self.scripts.pop(0):
            yield item


class HostedAgenticMultiCallTest(unittest.TestCase):
    def test_parallel_overflow_consumes_remaining_tool_budget_and_closes_catalog(self) -> None:
        harness = HostedAgenticHarness(
            self,
            max_tool_calls=1,
            model_provider_id="google-ai-studio",
            model_id="gemini-3.6-flash",
            provider_protocol="google-interactions",
            provider_api_version="v1",
        )
        transport = _ScriptedTransport(
            [
                _google_parallel_stream(harness.read_tool_name),
                _google_text_stream("google-budget-final", "google complete"),
            ]
        )
        adapter = harness.adapter(
            GoogleInteractionsAgenticClient(transport=transport),
            credential=EphemeralCredential("fixture-google-key"),
            private_codec=HostedProviderPrivateCodec(
                GOOGLE_INTERACTIONS_CODEC_ID,
                GOOGLE_INTERACTIONS_CODEC_VERSION,
                GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                GOOGLE_INTERACTIONS_CONTENT_TYPE,
            ),
            private_state_inspector=lambda content: inspect_google_interaction_state(
                content,
                mode="stateful",
            ),
            cost_estimator=google_36_flash_request_ceiling_microusd,
        )

        result, _events = _execute(harness, adapter)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            [
                item.resolution_status
                for item in harness.store.list_tool_invocations(
                    session_id="session-hosted"
                )
            ],
            ["parallel_denied", "budget_denied"],
        )
        journals = harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )
        self.assertEqual(journals[0].budget_tool_call_charges, 1)
        self.assertEqual(journals[1].request_phase, "finalization")
        self.assertNotIn("tools", transport.payloads[1])

    def test_google_parallel_calls_are_both_ledgered_denied_and_paired(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="google-ai-studio",
            model_id="gemini-3.6-flash",
            provider_protocol="google-interactions",
            provider_api_version="v1",
        )
        transport = _ScriptedTransport(
            [
                _google_parallel_stream(harness.read_tool_name),
                _google_text_stream("google-final", "google complete"),
            ]
        )
        adapter = harness.adapter(
            GoogleInteractionsAgenticClient(transport=transport),
            credential=EphemeralCredential("fixture-google-key"),
            private_codec=HostedProviderPrivateCodec(
                GOOGLE_INTERACTIONS_CODEC_ID,
                GOOGLE_INTERACTIONS_CODEC_VERSION,
                GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                GOOGLE_INTERACTIONS_CONTENT_TYPE,
            ),
            private_state_inspector=lambda content: inspect_google_interaction_state(
                content,
                mode="stateful",
            ),
            cost_estimator=google_36_flash_request_ceiling_microusd,
        )

        result, events = _execute(harness, adapter)

        self.assertEqual(result.output_text, "google complete")
        self._assert_parallel_accounting(harness, events)
        self.assertEqual(
            [item["call_id"] for item in transport.payloads[1]["input"]],
            ["google-call-1", "google-call-2"],
        )

    def test_openrouter_index_above_zero_is_ledgered_denied_and_paired(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="openrouter",
            model_id=OPENROUTER_AGENTIC_MODEL_ID,
            provider_protocol="openrouter-chat-completions",
            provider_api_version="v1",
            routing_constraint=openrouter_agentic_routing_constraint(),
        )
        transport = _ScriptedTransport(
            [
                _openrouter_parallel_stream(harness.read_tool_name),
                _openrouter_text_stream("openrouter-final", "openrouter complete"),
            ]
        )
        adapter = harness.adapter(
            OpenRouterAgenticClient(transport=transport),
            credential=EphemeralCredential("fixture-openrouter-key"),
            private_codec=HostedProviderPrivateCodec(
                OPENROUTER_AGENTIC_CODEC_ID,
                OPENROUTER_AGENTIC_CODEC_VERSION,
                OPENROUTER_AGENTIC_SCHEMA_VERSION,
                OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            private_state_inspector=inspect_openrouter_chat_state,
            cost_estimator=openrouter_deepinfra_v4_flash_request_ceiling_microusd,
        )

        result, events = _execute(harness, adapter)

        self.assertEqual(result.output_text, "openrouter complete")
        self._assert_parallel_accounting(harness, events)
        tool_messages = [
            item
            for item in transport.payloads[1]["messages"]
            if item.get("role") == "tool"
        ]
        self.assertEqual(
            [item["tool_call_id"] for item in tool_messages],
            ["openrouter-call-1", "openrouter-call-2"],
        )

    def _assert_parallel_accounting(self, harness, events) -> None:
        records = harness.store.list_tool_invocations(session_id="session-hosted")
        self.assertEqual(len(records), 2)
        self.assertEqual(
            [item.provider_call_index for item in records],
            [0, 1],
        )
        self.assertEqual(
            [item.resolution_status for item in records],
            ["parallel_denied", "parallel_denied"],
        )
        self.assertEqual(harness.cli_calls, 0)
        event_types = [item.event_type for item in events]
        proposed = [
            index
            for index, event_type in enumerate(event_types)
            if event_type == "runtime.tool_call.proposed"
        ]
        failed = [
            index
            for index, event_type in enumerate(event_types)
            if event_type == "runtime.tool_call.failed"
        ]
        self.assertEqual(len(proposed), 2)
        self.assertEqual(len(failed), 2)
        self.assertLess(max(proposed), min(failed))
        self.assertNotIn("runtime.tool_call.started", event_types)
        journals = harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )
        self.assertEqual(len(journals), 2)
        self.assertEqual(journals[0].observed_call_count, 2)
        self.assertEqual(journals[0].budget_tool_call_charges, 2)
        self.assertEqual(journals[0].pairing_status, "consumed")
        self.assertTrue(all(item.commit_status == "committed" for item in journals))


def _execute(harness, adapter):
    events: list[RuntimeExecutionEvent] = []
    result = execute_runtime_turn(
        session=harness.session,
        provider=harness.provider,
        input_text="Use only synthetic fixture data.",
        agentic_adapter=adapter,
        provider_state=harness.store.get_provider_state("session-hosted"),
        correlation_id="turn-hosted",
        effective_authority=harness.authority,
        event_sink=events.append,
    )
    return result, events


def _google_parallel_stream(tool_name: str):
    steps = []
    for index, call_id in enumerate(("google-call-1", "google-call-2")):
        steps.extend(
            [
                {
                    "event_type": "step.start",
                    "index": index,
                    "step": {
                        "type": "function_call",
                        "id": call_id,
                        "name": tool_name,
                        "arguments": {"value": index + 1},
                    },
                },
                {"event_type": "step.stop", "index": index},
            ]
        )
    return [
        {
            "event_type": "interaction.created",
            "interaction": {
                "id": "google-parallel",
                "model": "gemini-3.6-flash",
                "status": "in_progress",
            },
        },
        *steps,
        _google_completed("google-parallel", "requires_action"),
    ]


def _google_text_stream(interaction_id: str, text: str):
    return [
        {
            "event_type": "interaction.created",
            "interaction": {
                "id": interaction_id,
                "model": "gemini-3.6-flash",
                "status": "in_progress",
            },
        },
        {
            "event_type": "step.start",
            "index": 0,
            "step": {"type": "model_output"},
        },
        {
            "event_type": "step.delta",
            "index": 0,
            "delta": {"type": "text", "text": text},
        },
        {"event_type": "step.stop", "index": 0},
        _google_completed(interaction_id, "completed"),
    ]


def _google_completed(interaction_id: str, status: str):
    return {
        "event_type": "interaction.completed",
        "interaction": {
            "id": interaction_id,
            "model": "gemini-3.6-flash",
            "status": status,
            "usage": {"total_input_tokens": 10, "total_output_tokens": 2},
        },
    }


def _openrouter_parallel_stream(tool_name: str):
    calls = []
    for index, call_id in enumerate(("openrouter-call-1", "openrouter-call-2")):
        calls.append(
            {
                "index": index,
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps({"value": index + 1}),
                },
            }
        )
    return [
        {
            **_openrouter_identity("openrouter-parallel"),
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "tool_calls": calls},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            "openrouter_metadata": _openrouter_metadata(),
        }
    ]


def _openrouter_text_stream(generation_id: str, text: str):
    return [
        {
            **_openrouter_identity(generation_id),
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            "openrouter_metadata": _openrouter_metadata(),
        }
    ]


def _openrouter_identity(generation_id: str):
    return {
        "id": generation_id,
        "object": "chat.completion.chunk",
        "model": OPENROUTER_AGENTIC_MODEL_ID,
        "provider": "DeepInfra",
    }


def _openrouter_metadata():
    endpoint = {
        "provider": "DeepInfra",
        "model": OPENROUTER_AGENTIC_MODEL_ID,
    }
    return {
        "requested": OPENROUTER_AGENTIC_MODEL_ID,
        "attempt": 1,
        "endpoints": {"available": [{**endpoint, "selected": True}]},
        "attempts": [{**endpoint, "status": 200}],
    }


if __name__ == "__main__":
    unittest.main()
