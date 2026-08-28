from __future__ import annotations

from dataclasses import replace
import time
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import HOSTED_FINALIZATION_INSTRUCTION
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.hosted_agentic_models import HostedFinalizationPolicy
from core.runtime.hosted_agentic_request import hosted_request_control_digest
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticFinalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = HostedAgenticHarness(self, max_tool_calls=1)

    def execute(self, client, *, adapter=None):
        events: list[RuntimeExecutionEvent] = []
        active_adapter = adapter or self.harness.adapter(client)
        result = execute_runtime_turn(
            session=self.harness.session,
            provider=self.harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=active_adapter,
            provider_state=self.harness.store.get_provider_state("session-hosted"),
            correlation_id="turn-hosted",
            effective_authority=self.harness.authority,
            event_sink=events.append,
        )
        return result, events

    def test_last_tool_exhausts_only_tool_budget_and_forces_toolless_final_step(self) -> None:
        client = DeterministicFakeAgenticClient(
            tool_name=self.harness.read_tool_name
        )

        result, events = self.execute(client)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(client.requests), 2)
        first, final = client.requests
        self.assertEqual(first.request_phase, "exploration")
        self.assertTrue(first.tool_definitions)
        self.assertEqual(final.request_phase, "finalization")
        self.assertEqual(final.tool_definitions, ())
        self.assertEqual(len(final.tool_results), 1)
        self.assertEqual(
            final.content_blocks[-1].provenance,
            "finalization_instruction",
        )
        self.assertEqual(
            [
                block.content.decode()
                for block in final.content_blocks
                if block.provenance == "finalization_instruction"
            ],
            [HOSTED_FINALIZATION_INSTRUCTION],
        )
        mutated_final = replace(
            final,
            content_blocks=(
                *final.content_blocks[:-1],
                replace(final.content_blocks[-1], trust_level="trusted_actor"),
            ),
        )
        self.assertNotEqual(
            hosted_request_control_digest(final),
            hosted_request_control_digest(mutated_final),
        )
        self.assertFalse(
            any(event.event_type == "runtime.error" for event in events)
        )
        journals = self.harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )
        self.assertEqual(
            [(item.request_phase, item.budget_tool_call_charges) for item in journals],
            [("exploration", 1), ("finalization", 0)],
        )

    def test_unexpected_finalization_tool_is_budget_denied_then_recovers_once(self) -> None:
        client = DeterministicFakeAgenticClient(
            tool_sequence=(
                self.harness.read_tool_name,
                self.harness.read_tool_name,
            )
        )

        result, events = self.execute(client)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["exploration", "finalization", "finalization_recovery"],
        )
        self.assertTrue(client.requests[0].tool_definitions)
        self.assertEqual(client.requests[1].tool_definitions, ())
        self.assertEqual(client.requests[2].tool_definitions, ())
        invocations = self.harness.store.list_tool_invocations(
            session_id="session-hosted"
        )
        self.assertEqual(len(invocations), 2)
        self.assertEqual(invocations[1].resolution_status, "budget_denied")
        self.assertEqual(
            invocations[1].failure_reason,
            "agent_finalization_tool_call_forbidden",
        )
        self.assertEqual(invocations[1].state, "denied")
        self.assertFalse(
            any(event.event_type == "runtime.error" for event in events)
        )
        self.assertEqual(
            self.harness.store.get_session("session-hosted").status,
            "running",
        )

    def test_second_unexpected_finalization_tool_quarantines_without_fourth_request(self) -> None:
        client = DeterministicFakeAgenticClient(
            tool_sequence=(
                self.harness.read_tool_name,
                self.harness.read_tool_name,
                self.harness.read_tool_name,
            )
        )

        result, events = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            result.failure_reason_code,
            "agent_finalization_recovery_exhausted",
        )
        self.assertEqual(len(client.requests), 3)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["exploration", "finalization", "finalization_recovery"],
        )
        invocations = self.harness.store.list_tool_invocations(
            session_id="session-hosted"
        )
        self.assertEqual(
            [item.resolution_status for item in invocations],
            ["succeeded", "budget_denied", "budget_denied"],
        )
        session = self.harness.store.get_session("session-hosted")
        self.assertEqual(session.status, "recovery_required")
        self.assertEqual(session.recovery_reason_code, "provider_pairing_ambiguous")
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "agent_finalization_recovery_exhausted"}],
        )
        self.assertFalse(
            any(event.event_type == "runtime.output.final" for event in events)
        )

    def test_whitespace_final_is_rolled_back_and_reported_as_structured_failure(self) -> None:
        client = DeterministicFakeAgenticClient(final_text=" \n\t ")

        result, events = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.failure_reason_code, "agent_final_output_empty")
        self.assertFalse(
            any(event.event_type == "runtime.output.final" for event in events)
        )
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "agent_final_output_empty"}],
        )
        journal = self.harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )[0]
        self.assertTrue(journal.invalid_final_output)
        self.assertFalse(journal.final_output_validated)
        self.assertEqual(journal.commit_status, "rolled_back")
        self.assertEqual(journal.stream_status, "failed")
        self.assertEqual(
            self.harness.store.get_session("session-hosted").status,
            "running",
        )

    def test_missing_credential_fails_before_request_build_or_egress_export(self) -> None:
        client = DeterministicFakeAgenticClient()
        adapter = self.harness.adapter(client, credential_required=True)

        result, events = self.execute(client, adapter=adapter)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            result.failure_reason_code,
            "provider_credential_authorization_missing",
        )
        self.assertEqual(client.requests, [])
        self.assertEqual(
            self.harness.store.list_provider_step_journals(
                session_id="session-hosted"
            ),
            [],
        )
        self.assertEqual(
            self.harness.store.list_egress_decisions(session_id="session-hosted"),
            [],
        )
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "provider_credential_authorization_missing"}],
        )

    def test_unavailable_terminal_reserve_is_visible_before_provider_transport(self) -> None:
        client = DeterministicFakeAgenticClient()
        adapter = self.harness.adapter(
            client,
            finalization_policy=HostedFinalizationPolicy(
                exploration_max_output_tokens=128,
                finalization_max_output_tokens=600,
                finalization_cost_reserve_microusd_per_attempt=0,
                finalization_time_reserve_seconds_per_attempt=0.25,
                max_recovery_attempts=1,
            ),
        )

        result, events = self.execute(client, adapter=adapter)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            result.failure_reason_code,
            "agent_finalization_reserve_unavailable",
        )
        self.assertIn("final answer", result.public_error_message)
        self.assertEqual(client.requests, [])
        self.assertEqual(
            self.harness.store.list_egress_decisions(
                session_id="session-hosted"
            ),
            [],
        )
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "agent_finalization_reserve_unavailable"}],
        )

    def test_request_specific_cost_preflight_falls_back_before_egress_commit(self) -> None:
        self.harness.policy = replace(
            self.harness.policy,
            max_estimated_cost_microusd=100,
        )
        client = DeterministicFakeAgenticClient()
        adapter = self.harness.adapter(
            client,
            cost_estimator=lambda request: (
                81 if request.request_phase == "exploration" else 9
            ),
            finalization_policy=HostedFinalizationPolicy(
                exploration_max_output_tokens=128,
                finalization_max_output_tokens=128,
                finalization_cost_reserve_microusd_per_attempt=20,
                finalization_time_reserve_seconds_per_attempt=0.25,
                max_recovery_attempts=1,
            ),
        )

        result, events = self.execute(client, adapter=adapter)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["finalization"],
        )
        decisions = self.harness.store.list_egress_decisions(
            session_id="session-hosted"
        )
        self.assertEqual(
            {decision.provenance for decision in decisions},
            {"platform_instruction", "user_input", "finalization_instruction"},
        )
        self.assertFalse(
            any(event.event_type == "runtime.error" for event in events)
        )

    def test_slow_tool_is_fenced_before_it_consumes_finalization_time(self) -> None:
        self.harness.policy = replace(
            self.harness.policy,
            max_wall_time_seconds=0.2,
        )
        self.harness.read_delay_seconds = 0.25
        client = DeterministicFakeAgenticClient(
            tool_name=self.harness.read_tool_name
        )
        adapter = self.harness.adapter(
            client,
            finalization_policy=HostedFinalizationPolicy(
                exploration_max_output_tokens=128,
                finalization_max_output_tokens=128,
                finalization_cost_reserve_microusd_per_attempt=0,
                finalization_time_reserve_seconds_per_attempt=0.05,
                max_recovery_attempts=0,
            ),
        )

        result, events = self.execute(client, adapter=adapter)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["exploration", "finalization"],
        )
        invocation = self.harness.store.list_tool_invocations(
            session_id="session-hosted"
        )[0]
        self.assertEqual(invocation.state, "failed")
        self.assertEqual(
            invocation.failure_reason,
            "agent_finalization_time_reserve_reached",
        )
        self.assertIsNotNone(invocation.result_id)
        self.assertIsNone(invocation.result_private_ref)
        self.assertEqual(
            client.requests[-1].tool_results[0].content,
            b'{"error":"agent_finalization_time_reserve_reached"}',
        )
        self.assertFalse(
            any(event.event_type == "runtime.error" for event in events)
        )

    def test_slow_result_persistence_cannot_commit_success_after_deadline(self) -> None:
        self.harness.policy = replace(
            self.harness.policy,
            max_wall_time_seconds=0.2,
        )
        client = DeterministicFakeAgenticClient(
            tool_name=self.harness.read_tool_name
        )
        adapter = self.harness.adapter(
            client,
            finalization_policy=HostedFinalizationPolicy(
                exploration_max_output_tokens=128,
                finalization_max_output_tokens=128,
                finalization_cost_reserve_microusd_per_attempt=0,
                finalization_time_reserve_seconds_per_attempt=0.05,
                max_recovery_attempts=0,
            ),
        )
        private_store = self.harness.orchestrator.ledger.private_payload_store
        original_put = private_store.put

        def delayed_result_put(**kwargs):
            if kwargs.get("private_ref") is None:
                time.sleep(0.15)
            return original_put(**kwargs)

        with patch.object(private_store, "put", side_effect=delayed_result_put):
            result, events = self.execute(client, adapter=adapter)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            [request.request_phase for request in client.requests],
            ["exploration", "finalization"],
        )
        invocation = self.harness.store.list_tool_invocations(
            session_id="session-hosted"
        )[0]
        self.assertEqual(invocation.state, "failed")
        self.assertEqual(
            invocation.failure_reason,
            "agent_finalization_time_reserve_reached",
        )
        self.assertIsNotNone(invocation.result_id)
        self.assertIsNone(invocation.result_private_ref)
        self.assertEqual(
            client.requests[-1].tool_results[0].content,
            b'{"error":"agent_finalization_time_reserve_reached"}',
        )
        self.assertFalse(
            any(event.event_type == "runtime.error" for event in events)
        )


if __name__ == "__main__":
    unittest.main()
