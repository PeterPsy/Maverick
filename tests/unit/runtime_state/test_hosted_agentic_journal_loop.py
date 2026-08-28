"""Hosted-loop journal, event ordering, budget, and replay regressions."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from core.providers.agentic_adapter import RuntimeRecoveryContext
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.runtime_state.test_hosted_agentic_loop import (
    _CallThenTerminalErrorClient,
)


class HostedAgenticJournalLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = HostedAgenticHarness(self)

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
        return result, events, active_adapter

    def test_events_bracket_effect_boundary_and_completion_follows_result_persistence(self) -> None:
        client = DeterministicFakeAgenticClient(tool_name=self.harness.read_tool_name)
        adapter = self.harness.adapter(client)
        ordering: list[str] = []
        original = self.harness.orchestrator._invoke_surface

        def invoke_surface(**kwargs):
            ordering.append("effect_boundary")
            self.assertIn("runtime.tool_call.proposed", ordering)
            self.assertIn("runtime.tool_call.started", ordering)
            self.assertNotIn("runtime.tool_call.completed", ordering)
            return original(**kwargs)

        def sink(item):
            ordering.append(item.event_type)
            if item.event_type == "runtime.tool_call.completed":
                invocation = self.harness.store.list_tool_invocations(
                    session_id="session-hosted"
                )[0]
                self.assertEqual(invocation.state, "succeeded")
                self.assertIsNotNone(invocation.result_private_ref)
                self.assertIsNotNone(invocation.result_persisted_at)

        with patch.object(
            self.harness.orchestrator,
            "_invoke_surface",
            side_effect=invoke_surface,
        ):
            result = execute_runtime_turn(
                session=self.harness.session,
                provider=self.harness.provider,
                input_text="Use only synthetic fixture data.",
                agentic_adapter=adapter,
                provider_state=self.harness.store.get_provider_state("session-hosted"),
                correlation_id="turn-hosted",
                effective_authority=self.harness.authority,
                event_sink=sink,
            )

        self.assertEqual(result.exit_code, 0)
        proposed = ordering.index("runtime.tool_call.proposed")
        started = ordering.index("runtime.tool_call.started")
        boundary = ordering.index("effect_boundary")
        completed = ordering.index("runtime.tool_call.completed")
        self.assertLess(proposed, started)
        self.assertLess(started, boundary)
        self.assertLess(boundary, completed)

    def test_tool_budget_allows_only_one_finalization_recovery(self) -> None:
        harness = HostedAgenticHarness(self, max_tool_calls=1)
        client = DeterministicFakeAgenticClient(
            tool_name=harness.read_tool_name,
            repeat_tool=True,
        )
        self.harness = harness

        result, events, _adapter = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(harness.cli_calls, 1)
        self.assertEqual(len(client.requests), 3)
        errors = [event.payload for event in events if event.event_type == "runtime.error"]
        self.assertEqual(
            errors,
            [{"reason_code": "agent_finalization_recovery_exhausted"}],
        )
        records = harness.store.list_tool_invocations(session_id="session-hosted")
        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record.resolution_status for record in records],
            ["succeeded", "budget_denied", "budget_denied"],
        )

    def test_restart_replay_reuses_persisted_tool_result_without_duplicate_execution(self) -> None:
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="policy:test:1",
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            max_tool_result_bytes=4096,
        )
        existing = self.harness.orchestrator.invoke_provider_tool(
            provider_tool_name=self.harness.read_tool_name,
            provider_tool_call_id="fake-call-1",
            arguments={"value": 4},
            authority=self.harness.authority,
            context=self.harness.adapter(
                DeterministicFakeAgenticClient()
            ).loop.actor_context_resolver(None),
            turn_id="turn-hosted",
            policy=policy,
        )
        self.assertEqual(existing.invocation.state, "succeeded")
        client = DeterministicFakeAgenticClient(tool_name=self.harness.read_tool_name)

        result, _events, _adapter = self.execute(client)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.harness.cli_calls, 1)
        self.assertEqual(len(client.requests), 2)

    def test_provider_outage_after_acceptance_is_terminal_without_blind_retry(self) -> None:
        client = DeterministicFakeAgenticClient(
            provider_error_code="provider_unavailable"
        )

        result, events, _adapter = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.failure_reason_code, "provider_acceptance_ambiguous")
        self.assertEqual(result.diagnostic_reference, "turn:turn-hosted")
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(self.harness.cli_calls, 0)
        self.assertEqual(
            [event.payload for event in events if event.event_type == "runtime.error"],
            [{"reason_code": "provider_acceptance_ambiguous"}],
        )

    def test_call_observed_before_terminal_error_remains_in_ledger_and_journal(self) -> None:
        client = _CallThenTerminalErrorClient(self.harness.read_tool_name)

        result, events, _adapter = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        records = self.harness.store.list_tool_invocations(
            session_id="session-hosted"
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].provider_tool_call_id, "call-before-error")
        journal = self.harness.store.list_provider_step_journals(
            session_id="session-hosted"
        )[0]
        self.assertEqual(journal.observed_call_count, 1)
        self.assertEqual(journal.commit_status, "recovery_required")
        self.assertIn(
            "runtime.tool_call.proposed",
            [event.event_type for event in events],
        )

    def test_recovery_marks_ambiguous_mutation_execution_unknown(self) -> None:
        client = DeterministicFakeAgenticClient(tool_name=self.harness.mutate_tool_name)
        adapter = self.harness.adapter(client)
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="policy:test:1",
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            max_tool_result_bytes=4096,
        )
        pending = self.harness.orchestrator.invoke_provider_tool(
            provider_tool_name=self.harness.mutate_tool_name,
            provider_tool_call_id="recovery-call",
            arguments={"value": 1},
            authority=self.harness.authority,
            context=adapter.loop.actor_context_resolver(None),
            turn_id="turn-hosted",
            policy=policy,
        )
        decided = self.harness.orchestrator.decide_confirmation(
            invocation_id=pending.invocation.invocation_id,
            decision="approve",
            arguments_digest=pending.invocation.arguments_digest,
            expected_invocation_revision=pending.invocation.revision,
            confirming_actor_id="user-1",
            policy=policy,
        )
        authorized = self.harness.orchestrator.ledger.authorize(
            invocation_id=pending.invocation.invocation_id,
            grant_id=decided.confirmation_grant.grant_id,  # type: ignore[union-attr]
        )
        self.harness.orchestrator.ledger.transition(authorized, "executing")

        recovery = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    self.harness.session,
                    self.harness.binding,
                    self.harness.store.get_provider_state("session-hosted"),
                )
            )
        )

        self.assertFalse(recovery.recovered)
        self.assertEqual(recovery.reason_code, "tool_execution_ambiguous")
        self.assertEqual(
            self.harness.store.get_tool_invocation(pending.invocation.invocation_id).state,
            "execution_unknown",
        )
        self.assertEqual(
            self.harness.store.get_session("session-hosted").status,
            "recovery_required",
        )


if __name__ == "__main__":
    unittest.main()
