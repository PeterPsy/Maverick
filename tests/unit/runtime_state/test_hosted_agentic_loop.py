from __future__ import annotations

import asyncio
import json
from threading import Thread
import time
import unittest

from core.providers.agentic_adapter import RuntimeCancelContext, RuntimeRecoveryContext
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class HostedAgenticLoopTest(unittest.TestCase):
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

    def test_fake_provider_runs_sequential_tool_loop_and_keeps_private_state_out_of_events(self) -> None:
        client = DeterministicFakeAgenticClient(tool_name=self.harness.read_tool_name)

        result, events, _adapter = self.execute(client)

        self.assertEqual(result.output_text, "fake hosted loop answer")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.harness.cli_calls, 1)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(
            self.harness.store.get_provider_state("session-hosted").provider_request_id,
            client.requests[1].request_id,
        )
        self.assertEqual(len(client.requests[1].tool_results), 1)
        self.assertEqual(
            json.loads(client.requests[1].tool_results[0].content),
            {"value": 4},
        )
        event_payloads = json.dumps([event.payload for event in events], default=str)
        self.assertNotIn("opaque-thought-signature", event_payloads)
        self.assertNotIn('"value": 4', event_payloads)
        self.assertNotIn("Use only synthetic fixture data", json.dumps(self.harness.audit.documents, default=str))
        private_files = list(
            self.harness.root.glob(
                "workspaces/default/runtime/sessions/session-hosted/private/**/*.json"
            )
        )
        self.assertTrue(private_files)
        self.assertTrue(
            all(b"opaque-thought-signature" not in path.read_bytes() for path in private_files)
        )
        self.assertGreaterEqual(
            len(self.harness.store.list_egress_decisions(session_id="session-hosted")),
            5,
        )

    def test_mutating_tool_waits_for_persisted_confirmation_and_executes_once(self) -> None:
        client = DeterministicFakeAgenticClient(tool_name=self.harness.mutate_tool_name)
        adapter = self.harness.adapter(client)
        holder: dict[str, object] = {}

        def run() -> None:
            holder["execution"] = self.execute(client, adapter=adapter)

        thread = Thread(target=run)
        thread.start()
        invocation = self._wait_for_invocation("awaiting_confirmation")
        self.assertEqual(self.harness.mcp_calls, 0)
        policy = RuntimeToolConfirmationPolicy(
            policy_revision=invocation.policy_revision,
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            max_tool_result_bytes=self.harness.policy.max_tool_result_bytes,
        )
        decided = self.harness.orchestrator.decide_confirmation(
            invocation_id=invocation.invocation_id,
            decision="approve",
            arguments_digest=invocation.arguments_digest,
            expected_invocation_revision=invocation.revision,
            confirming_actor_id="user-1",
            policy=policy,
        )
        self.assertIsNotNone(decided.confirmation_grant)
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        result, events, _adapter = holder["execution"]  # type: ignore[misc]
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.harness.mcp_calls, 1)
        self.assertEqual(
            [status for status, _invocation_id in self.harness.turn_statuses],
            ["waiting_for_tool_confirmation", "active"],
        )
        self.assertEqual(self.harness.store.get_turn("turn-hosted").status, "active")
        self.assertIn(
            "runtime.tool_call.awaiting_confirmation",
            [event.event_type for event in events],
        )

    def test_cancel_closes_inflight_transport_without_second_request(self) -> None:
        client = DeterministicFakeAgenticClient(stall_after_acceptance=True)
        adapter = self.harness.adapter(client)
        holder: dict[str, object] = {}

        thread = Thread(
            target=lambda: holder.setdefault("execution", self.execute(client, adapter=adapter))
        )
        thread.start()
        self._wait_until(lambda: len(client.requests) == 1)
        cancel = asyncio.run(
            adapter.cancel(
                RuntimeCancelContext(
                    session=self.harness.session,
                    binding=self.harness.binding,
                    provider_state=self.harness.store.get_provider_state("session-hosted"),
                    correlation_id="turn-hosted",
                )
            )
        )
        thread.join(timeout=5)

        self.assertTrue(cancel.cancelled)
        self.assertFalse(thread.is_alive())
        result, events, _adapter = holder["execution"]  # type: ignore[misc]
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(client.closed_streams, 1)
        errors = [event.payload for event in events if event.event_type == "runtime.error"]
        self.assertEqual(errors, [{"reason_code": "runtime_cancelled"}])

    def test_denied_confirmation_resumes_turn_without_mutation(self) -> None:
        client = DeterministicFakeAgenticClient(tool_name=self.harness.mutate_tool_name)
        adapter = self.harness.adapter(client)
        holder: dict[str, object] = {}
        thread = Thread(
            target=lambda: holder.setdefault("execution", self.execute(client, adapter=adapter))
        )
        thread.start()
        invocation = self._wait_for_invocation("awaiting_confirmation")
        policy = RuntimeToolConfirmationPolicy(
            policy_revision=invocation.policy_revision,
            require_confirmation_for_mutating=True,
            require_confirmation_for_destructive=True,
            max_tool_result_bytes=self.harness.policy.max_tool_result_bytes,
        )
        self.harness.orchestrator.decide_confirmation(
            invocation_id=invocation.invocation_id,
            decision="deny",
            arguments_digest=invocation.arguments_digest,
            expected_invocation_revision=invocation.revision,
            confirming_actor_id="user-1",
            policy=policy,
        )
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        result, _events, _adapter = holder["execution"]  # type: ignore[misc]
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.harness.mcp_calls, 0)
        self.assertEqual(self.harness.store.get_turn("turn-hosted").status, "active")
        self.assertEqual(
            [status for status, _invocation_id in self.harness.turn_statuses],
            ["waiting_for_tool_confirmation", "active"],
        )

    def test_tool_budget_stops_repeating_provider_before_duplicate_side_effect(self) -> None:
        harness = HostedAgenticHarness(self, max_tool_calls=1)
        client = DeterministicFakeAgenticClient(
            tool_name=harness.read_tool_name,
            repeat_tool=True,
        )
        self.harness = harness

        result, events, _adapter = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(harness.cli_calls, 1)
        self.assertEqual(len(client.requests), 2)
        errors = [event.payload for event in events if event.event_type == "runtime.error"]
        self.assertEqual(errors, [{"reason_code": "agent_tool_call_limit_reached"}])

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

    def test_cancel_while_waiting_makes_confirmation_invocation_terminal(self) -> None:
        client = DeterministicFakeAgenticClient(tool_name=self.harness.mutate_tool_name)
        adapter = self.harness.adapter(client)
        holder: dict[str, object] = {}
        thread = Thread(
            target=lambda: holder.setdefault("execution", self.execute(client, adapter=adapter))
        )
        thread.start()
        invocation = self._wait_for_invocation("awaiting_confirmation")

        asyncio.run(
            adapter.cancel(
                RuntimeCancelContext(
                    self.harness.session,
                    self.harness.binding,
                    self.harness.store.get_provider_state("session-hosted"),
                    "turn-hosted",
                )
            )
        )
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(
            self.harness.store.get_tool_invocation(invocation.invocation_id).state,
            "cancelled",
        )
        self.assertEqual(self.harness.mcp_calls, 0)
        self.assertEqual(self.harness.store.get_turn("turn-hosted").status, "active")

    def test_transport_exception_is_normalized_without_leaking_raw_detail(self) -> None:
        client = DeterministicFakeAgenticClient(
            transport_error="provider-secret-transport-detail"
        )

        result, events, _adapter = self.execute(client)

        self.assertEqual(result.exit_code, 1)
        serialized = json.dumps([event.payload for event in events])
        self.assertNotIn("provider-secret-transport-detail", serialized)
        self.assertIn("provider_response_invalid", serialized)

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
        self.assertEqual(recovery.reason_code, "session_recovery_required")
        self.assertEqual(
            self.harness.store.get_tool_invocation(pending.invocation.invocation_id).state,
            "execution_unknown",
        )

    def _wait_for_invocation(self, state: str):
        holder: dict[str, object] = {}

        def found() -> bool:
            records = self.harness.store.list_tool_invocations(session_id="session-hosted")
            if records and records[0].state == state:
                holder["record"] = records[0]
                return True
            return False

        self._wait_until(found)
        return holder["record"]

    def _wait_until(self, predicate) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for hosted-loop test state.")


if __name__ == "__main__":
    unittest.main()
