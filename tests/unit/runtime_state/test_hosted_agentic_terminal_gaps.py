"""Terminal pairing and cross-turn input isolation regressions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from threading import Thread
import time
import unittest

from core.providers.agentic_adapter import RuntimeRecoveryContext
from core.runtime.execution import execute_runtime_turn
from core.runtime.execution_binding import canonical_digest
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness
from tests.unit.runtime_state import test_hosted_agentic_recovery as recovery_tests


NOW = datetime(2026, 8, 27, tzinfo=UTC)


class HostedAgenticTerminalGapTest(unittest.TestCase):
    _begin = recovery_tests.HostedAgenticRecoveryTest._begin
    _tool_step = recovery_tests.HostedAgenticRecoveryTest._tool_step

    def _execute(self, harness, client, *, adapter=None):
        active_adapter = adapter or harness.adapter(client)
        return execute_runtime_turn(
            session=harness.store.get_session(harness.session.session_id),
            provider=harness.provider,
            input_text="Use only synthetic fixture data.",
            agentic_adapter=active_adapter,
            provider_state=harness.store.get_provider_state(harness.session.session_id),
            correlation_id="turn-hosted",
            effective_authority=harness.authority,
        )

    def _assert_terminal_pairing_contained(self, harness) -> None:
        unresolved = [
            item
            for item in harness.store.list_provider_step_journals(
                session_id=harness.session.session_id
            )
            if item.observed_call_count > 0
            and item.commit_status in {"pending", "committed"}
            and item.pairing_status != "consumed"
        ]
        pending_provider_calls = sum(item.observed_call_count for item in unresolved)
        self.assertTrue(
            pending_provider_calls == 0
            or harness.store.get_session(harness.session.session_id).status
            == "recovery_required"
        )

    def test_step_and_cost_limits_never_leave_running_terminal_pairing(self) -> None:
        step_harness = HostedAgenticHarness(self, max_tool_calls=1)
        step_result = self._execute(
            step_harness,
            DeterministicFakeAgenticClient(
                tool_name=step_harness.read_tool_name,
                repeat_tool=True,
            ),
        )
        self.assertEqual(step_result.failure_reason_code, "agent_step_limit_reached")
        self._assert_terminal_pairing_contained(step_harness)

        cost_harness = HostedAgenticHarness(self)
        cost_harness.policy = replace(
            cost_harness.policy,
            max_estimated_cost_microusd=1,
        )
        estimates = iter((0, 2))
        cost_client = DeterministicFakeAgenticClient(
            tool_name=cost_harness.read_tool_name
        )
        cost_result = self._execute(
            cost_harness,
            cost_client,
            adapter=cost_harness.adapter(
                cost_client,
                cost_estimator=lambda _request: next(estimates),
            ),
        )
        self.assertEqual(cost_result.failure_reason_code, "agent_cost_limit_reached")
        self.assertEqual(len(cost_client.requests), 1)
        self._assert_terminal_pairing_contained(cost_harness)

    def test_cancellation_and_authority_revocation_contain_ready_pairing(self) -> None:
        cancelled = HostedAgenticHarness(self)
        cancel_client = DeterministicFakeAgenticClient(
            tool_name=cancelled.mutate_tool_name
        )
        cancel_adapter = cancelled.adapter(cancel_client)
        holder: dict[str, object] = {}
        worker = Thread(
            target=lambda: holder.setdefault(
                "result",
                self._execute(cancelled, cancel_client, adapter=cancel_adapter),
            )
        )
        worker.start()
        self._wait_until(
            lambda: any(
                item.state == "awaiting_confirmation"
                for item in cancelled.store.list_tool_invocations(
                    session_id=cancelled.session.session_id
                )
            )
        )
        asyncio.run(
            cancel_adapter.cancel(
                replace(
                    self._cancel_context(cancelled),
                    correlation_id="turn-hosted",
                )
            )
        )
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self._assert_terminal_pairing_contained(cancelled)

        for reason_code in ("runtime_actor_policy_denied", "certificate_revoked"):
            with self.subTest(reason_code=reason_code):
                harness = HostedAgenticHarness(self)
                revoked = False

                def revoke() -> None:
                    nonlocal revoked
                    revoked = True

                def refresh(_context):
                    if revoked:
                        raise HostedAgenticLoopError(reason_code)
                    return harness.authority

                client = DeterministicFakeAgenticClient(
                    tool_name=harness.read_tool_name,
                    before_tool_call=revoke,
                )
                result = self._execute(
                    harness,
                    client,
                    adapter=harness.adapter(client, authority_refresher=refresh),
                )
                self.assertEqual(result.failure_reason_code, reason_code)
                self._assert_terminal_pairing_contained(harness)

    def test_new_turn_cannot_consume_previous_turn_pairing_or_ignore_input(self) -> None:
        harness = HostedAgenticHarness(self)
        client = DeterministicFakeAgenticClient()
        adapter = harness.adapter(client)
        record, _outcome, _envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-old-turn",
        )
        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state(harness.session.session_id),
                    "same_turn_recovery",
                )
            )
        )
        self.assertTrue(recovered.recovered)
        self.assertEqual(
            harness.store.get_provider_step_journal(record.journal_id).pairing_status,
            "ready",
        )
        old_turn = harness.store.get_turn("turn-hosted")
        harness.store.save_turn(
            replace(
                old_turn,
                status="failed",
                completed_at=NOW,
                failure_reason="terminal fixture",
            )
        )
        new_input = "This exact new input must never be discarded."
        harness.store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-new",
                session_id=harness.session.session_id,
                workspace_id=harness.session.workspace_id,
                status="active",
                input_text=new_input,
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        authority = replace(
            harness.authority,
            turn_id="turn-new",
            authority_digest="",
        )
        authority = replace(authority, authority_digest=canonical_digest(authority))

        result = execute_runtime_turn(
            session=harness.store.get_session(harness.session.session_id),
            provider=harness.provider,
            input_text=new_input,
            agentic_adapter=adapter,
            provider_state=harness.store.get_provider_state(harness.session.session_id),
            correlation_id="turn-new",
            effective_authority=authority,
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(result.failure_reason_code, "provider_pairing_ambiguous")
        self.assertEqual(client.requests, [])
        self.assertEqual(harness.store.get_turn("turn-new").input_text, new_input)
        self.assertEqual(
            harness.store.get_session(harness.session.session_id).status,
            "recovery_required",
        )

    @staticmethod
    def _cancel_context(harness):
        from core.providers.agentic_adapter import RuntimeCancelContext

        return RuntimeCancelContext(
            harness.session,
            harness.binding,
            harness.store.get_provider_state(harness.session.session_id),
            "turn-hosted",
        )

    def _wait_until(self, predicate, *, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for hosted runtime state.")


if __name__ == "__main__":
    unittest.main()
