"""Google Interactions integration through the shared hosted runtime loop."""

from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from core.providers.agentic_protocol import EphemeralCredential
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
from core.runtime.execution import execute_runtime_turn
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.turn_submission_service_events import _complete_turn_from_exit_code
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.providers.test_google_interactions_codec import (
    THOUGHT_SIGNATURE,
    _ScriptedTransport,
    _completed,
    _created,
    _text_stream,
    _tool_stream,
)


class GoogleInteractionsHostedLoopTest(unittest.TestCase):
    def test_terminal_failure_codes_reach_runtime_turn_failed_unchanged(self) -> None:
        cases = (
            ("incomplete", "provider_output_incomplete"),
            ("budget_exceeded", "provider_budget_exceeded"),
            ("cancelled", "provider_cancelled"),
        )
        for status, reason_code in cases:
            with self.subTest(status=status):
                harness = HostedAgenticHarness(
                    self,
                    model_provider_id="google-ai-studio",
                    model_id="gemini-3.6-flash",
                    provider_protocol="google-interactions",
                    routing_constraint=google_interactions_routing_constraint(),
                )
                interaction_id = f"interaction-loop-{status}"
                terminal = _completed(
                    interaction_id,
                    status,
                    input_tokens=20,
                    output_tokens=4,
                )
                transport = _ScriptedTransport([[
                    _created(interaction_id),
                    {
                        "event_type": "interaction.status_update",
                        "interaction_id": interaction_id,
                        "status": status,
                    },
                    terminal,
                ]])
                adapter = harness.adapter(
                    GoogleInteractionsAgenticClient(transport=transport),
                    private_codec=HostedProviderPrivateCodec(
                        GOOGLE_INTERACTIONS_CODEC_ID,
                        GOOGLE_INTERACTIONS_CODEC_VERSION,
                        GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                        GOOGLE_INTERACTIONS_CONTENT_TYPE,
                    ),
                    credential=EphemeralCredential("fixture-google-key"),
                    cost_estimator=google_36_flash_request_ceiling_microusd,
                )

                result = execute_runtime_turn(
                    session=harness.session,
                    provider=harness.provider,
                    input_text="Use only synthetic fixture data.",
                    agentic_adapter=adapter,
                    provider_state=harness.store.get_provider_state("session-hosted"),
                    correlation_id="turn-hosted",
                    effective_authority=harness.authority,
                )
                _failed, event = _complete_turn_from_exit_code(
                    SimpleNamespace(
                        runtime_store=harness.store,
                        runtime_event_bus=None,
                        repository_root=harness.root,
                    ),
                    session_id=harness.session.session_id,
                    turn_id="turn-hosted",
                    provider_id="maverick-tool-loop",
                    exit_code=result.exit_code,
                    failure_reason_code=result.failure_reason_code,
                    public_error_message=result.public_error_message,
                    diagnostic_reference=result.diagnostic_reference,
                )

                self.assertEqual(result.failure_reason_code, reason_code)
                self.assertEqual(event.event_type, "runtime.turn.failed")
                self.assertEqual(event.payload["failure_reason_code"], reason_code)

    def test_real_google_codec_runs_through_shared_tool_loop(self) -> None:
        harness = HostedAgenticHarness(
            self,
            model_provider_id="google-ai-studio",
            model_id="gemini-3.6-flash",
            provider_protocol="google-interactions",
            routing_constraint=google_interactions_routing_constraint(),
            filesystem_list=True,
        )
        transport = _ScriptedTransport(
            [
                _tool_stream(
                    "interaction-loop-1",
                    tool_name=harness.filesystem_list_tool_name,
                    arguments={"path": ".", "max_depth": 1, "max_results": 10},
                ),
                _text_stream("interaction-loop-2", "google fixture answer"),
            ]
        )
        adapter = harness.adapter(
            GoogleInteractionsAgenticClient(transport=transport),
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
        self.assertEqual(harness.cli_calls, 0)
        self.assertEqual(len(transport.payloads), 2)
        self.assertEqual(
            transport.payloads[0]["tools"][0]["name"],
            harness.filesystem_list_tool_name,
        )
        self.assertIn(harness.filesystem_marker, json.dumps(transport.payloads[1]))
        self.assertEqual(
            transport.payloads[1]["previous_interaction_id"],
            "interaction-loop-1",
        )
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
                for path in stateless.root.glob(
                    "workspaces/default/runtime/sessions/**/*.json"
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
