from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest

from core.providers.agentic_adapter import RuntimeRecoveryContext
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_agentic_state import HostedAgenticStateBridge
from core.runtime.tool_orchestrator import RuntimeToolConfirmationPolicy
from tests.support.fake_agentic_provider import DeterministicFakeAgenticClient
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class _StartupSentinel(RuntimeError):
    pass


class HostedAgenticRecoveryTest(unittest.TestCase):
    def test_finalization_phase_chain_is_scoped_to_each_turn(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        base = self._begin(harness, adapter, "request-phase-base")
        final_turn = replace(
            base,
            journal_id="journal-final-turn",
            request_id="request-final-turn",
            turn_id="turn-final",
            request_phase="finalization",
        )
        next_turn = replace(
            base,
            journal_id="journal-next-turn",
            request_id="request-next-turn",
            turn_id="turn-next",
            request_phase="exploration",
        )
        recovery = adapter.loop.recovery
        runtime = adapter.loop.provider_runtimes.resolve(harness.binding)
        recovery._validate_chain(
            (final_turn, next_turn),
            binding=harness.binding,
            provider_runtime=runtime,
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "provider_finalization_phase_chain_invalid",
        ):
            recovery._validate_chain(
                (final_turn, replace(next_turn, turn_id="turn-final")),
                binding=harness.binding,
                provider_runtime=runtime,
            )

    def test_transport_before_acceptance_rolls_back_but_after_acceptance_quarantines(self) -> None:
        safe = HostedAgenticHarness(self)
        safe_adapter = safe.adapter(DeterministicFakeAgenticClient())
        safe_journal = self._begin(safe, safe_adapter, "request-before")
        safe_adapter.loop.provider_step_journal.fail_stream(safe_journal)

        recovered = asyncio.run(
            safe_adapter.recover(
                RuntimeRecoveryContext(
                    safe.session,
                    safe.binding,
                    safe.store.get_provider_state("session-hosted"),
                    "transport_failure",
                )
            )
        )

        self.assertTrue(recovered.recovered)
        self.assertEqual(
            safe.store.get_provider_step_journal(safe_journal.journal_id).commit_status,
            "rolled_back",
        )
        self.assertEqual(safe.store.get_session("session-hosted").status, "running")

        ambiguous = HostedAgenticHarness(self)
        ambiguous_adapter = ambiguous.adapter(DeterministicFakeAgenticClient())
        accepted = self._begin(ambiguous, ambiguous_adapter, "request-after")
        accepted = ambiguous_adapter.loop.provider_step_journal.accept(
            accepted,
            provider_response_id="response-after",
            provider_upstream_id=None,
        )
        ambiguous_adapter.loop.provider_step_journal.fail_stream(accepted)

        first = asyncio.run(
            ambiguous_adapter.recover(
                RuntimeRecoveryContext(
                    ambiguous.session,
                    ambiguous.binding,
                    ambiguous.store.get_provider_state("session-hosted"),
                    "transport_failure",
                )
            )
        )
        second = asyncio.run(
            ambiguous_adapter.recover(
                RuntimeRecoveryContext(
                    ambiguous.store.get_session("session-hosted"),
                    ambiguous.binding,
                    ambiguous.store.get_provider_state("session-hosted"),
                    "restart_repeat",
                )
            )
        )

        self.assertFalse(first.recovered)
        self.assertFalse(second.recovered)
        self.assertEqual(first.reason_code, "provider_acceptance_ambiguous")
        self.assertEqual(
            ambiguous.store.get_session("session-hosted").status,
            "recovery_required",
        )

    def test_crash_matrix_reconciles_pre_effect_result_pairing_and_commit(self) -> None:
        for crash_point in ("proposal", "authorization", "result", "pairing", "pre_commit"):
            with self.subTest(crash_point=crash_point):
                harness = HostedAgenticHarness(self)
                adapter = harness.adapter(DeterministicFakeAgenticClient())
                record, outcome, envelope = self._tool_step(
                    harness,
                    adapter,
                    request_id=f"request-{crash_point}",
                )
                if crash_point in {"authorization", "result", "pairing", "pre_commit"}:
                    outcome = harness.orchestrator.prepare_observed_tool(
                        outcome.invocation,
                        requested_catalog=harness.orchestrator.materialize(
                            authority=harness.authority,
                            context=adapter.loop.actor_context_resolver(None),
                        ),
                        authority=harness.authority,
                        context=adapter.loop.actor_context_resolver(None),
                        policy=_no_confirmation_policy(),
                    )
                if crash_point in {"result", "pairing", "pre_commit"}:
                    outcome = harness.orchestrator.execute_authorized(
                        outcome.invocation,
                        authority=harness.authority,
                        context=adapter.loop.actor_context_resolver(None),
                        policy=_no_confirmation_policy(),
                    )
                    self.assertEqual(harness.cli_calls, 1)
                if crash_point in {"pairing", "pre_commit"}:
                    record = adapter.loop.provider_step_journal.add_disposition(
                        record,
                        outcome.invocation.disposition_id,
                    )
                    record = adapter.loop.provider_step_journal.complete_dispositions(record)
                    record = adapter.loop.provider_step_journal.add_result(
                        record,
                        outcome.invocation.result_id,
                    )
                    record = _record_result_budget(
                        harness,
                        adapter.loop.provider_step_journal,
                        record,
                        outcome.invocation,
                    )
                    record = adapter.loop.provider_step_journal.mark_pairing_ready(record)
                if crash_point == "pre_commit":
                    harness.private_state_service.promote_staged_state(
                        session_id="session-hosted",
                        adapter_id=harness.binding.adapter_id,
                        adapter_version=harness.binding.adapter_version,
                        envelope=envelope,
                        expected_revision=0,
                    )

                recovered = asyncio.run(
                    adapter.recover(
                        RuntimeRecoveryContext(
                            harness.session,
                            harness.binding,
                            harness.store.get_provider_state("session-hosted"),
                            f"crash_after_{crash_point}",
                        )
                    )
                )
                terminal = harness.store.get_provider_step_journal(record.journal_id)
                revision = terminal.revision
                replay = asyncio.run(
                    adapter.recover(
                        RuntimeRecoveryContext(
                            harness.session,
                            harness.binding,
                            harness.store.get_provider_state("session-hosted"),
                            "restart_repeat",
                        )
                    )
                )

                self.assertTrue(recovered.recovered)
                self.assertTrue(replay.recovered)
                self.assertEqual(terminal.commit_status, "committed")
                self.assertEqual(terminal.pairing_status, "ready")
                self.assertEqual(terminal.budget_tool_call_charges, 1)
                self.assertGreater(terminal.budget_tool_result_bytes, 0)
                self.assertEqual(
                    harness.store.get_provider_step_journal(record.journal_id).revision,
                    revision,
                )
                self.assertLessEqual(harness.cli_calls, 1)

    def test_crash_after_effect_boundary_is_execution_unknown_and_never_repeated(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        record, outcome, _envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-effect",
            provider_tool_name=harness.mutate_tool_name,
        )
        outcome = harness.orchestrator.prepare_observed_tool(
            outcome.invocation,
            requested_catalog=harness.orchestrator.materialize(
                authority=harness.authority,
                context=adapter.loop.actor_context_resolver(None),
            ),
            authority=harness.authority,
            context=adapter.loop.actor_context_resolver(None),
            policy=_no_confirmation_policy(),
        )
        executing = harness.orchestrator.ledger.transition(
            outcome.invocation,
            "executing",
        )

        first = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "worker_loss",
                )
            )
        )
        persisted = harness.store.get_tool_invocation(executing.invocation_id)
        persisted_revision = persisted.revision
        second = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.store.get_session("session-hosted"),
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "restart_repeat",
                )
            )
        )

        self.assertFalse(first.recovered)
        self.assertFalse(second.recovered)
        self.assertEqual(persisted.state, "execution_unknown")
        self.assertIsNotNone(persisted.result_id)
        self.assertEqual(harness.mcp_calls, 0)
        self.assertEqual(
            harness.store.get_tool_invocation(executing.invocation_id).revision,
            persisted_revision,
        )
        self.assertEqual(
            harness.store.get_provider_step_journal(record.journal_id).commit_status,
            "recovery_required",
        )

    def test_staged_state_is_never_authoritative_before_pairing(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        record, _outcome, envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-staged",
        )

        self.assertIsNone(
            harness.store.get_provider_state("session-hosted").provider_private_envelope
        )
        self.assertEqual(record.staged_provider_state, envelope)
        runtime = adapter.loop.provider_runtimes.resolve(harness.binding)
        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "provider_state_ambiguous",
        ):
            HostedAgenticStateBridge(
                service=harness.private_state_service,
                codec=runtime.private_codec,
            ).read(
                SimpleNamespace(session=harness.session, binding=harness.binding),
                harness.authority,
            )
        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.session,
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "staged_state_crash",
                )
            )
        )
        self.assertTrue(recovered.recovered)
        self.assertEqual(
            harness.store.get_provider_state("session-hosted")
            .provider_private_envelope.opaque_state_ref,
            envelope.opaque_state_ref,
        )

    def test_promoted_wal_half_is_not_read_before_journal_commit(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        record, outcome, envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-promoted-half",
        )
        prepared = harness.orchestrator.prepare_observed_tool(
            outcome.invocation,
            requested_catalog=harness.orchestrator.materialize(
                authority=harness.authority,
                context=adapter.loop.actor_context_resolver(None),
            ),
            authority=harness.authority,
            context=adapter.loop.actor_context_resolver(None),
            policy=_no_confirmation_policy(),
        )
        result = harness.orchestrator.execute_authorized(
            prepared.invocation,
            authority=harness.authority,
            context=adapter.loop.actor_context_resolver(None),
            policy=_no_confirmation_policy(),
        )
        journal = adapter.loop.provider_step_journal
        record = journal.add_disposition(record, result.invocation.disposition_id)
        record = journal.complete_dispositions(record)
        record = journal.add_result(record, result.invocation.result_id)
        record = _record_result_budget(
            harness,
            journal,
            record,
            result.invocation,
        )
        journal.mark_pairing_ready(record)
        harness.private_state_service.promote_staged_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            envelope=envelope,
            expected_revision=0,
        )
        runtime = adapter.loop.provider_runtimes.resolve(harness.binding)

        with self.assertRaisesRegex(
            HostedAgenticLoopError,
            "provider_state_ambiguous",
        ):
            HostedAgenticStateBridge(
                service=harness.private_state_service,
                codec=runtime.private_codec,
            ).read(
                SimpleNamespace(session=harness.session, binding=harness.binding),
                harness.authority,
            )

    def test_worker_loss_can_finish_provable_step_for_failed_session(self) -> None:
        harness = HostedAgenticHarness(self)
        adapter = harness.adapter(DeterministicFakeAgenticClient())
        record, _outcome, envelope = self._tool_step(
            harness,
            adapter,
            request_id="request-failed-worker",
        )
        harness.store.save_session(replace(harness.session, status="failed"))

        recovered = asyncio.run(
            adapter.recover(
                RuntimeRecoveryContext(
                    harness.store.get_session("session-hosted"),
                    harness.binding,
                    harness.store.get_provider_state("session-hosted"),
                    "startup_worker_loss",
                )
            )
        )

        self.assertTrue(recovered.recovered)
        self.assertEqual(
            harness.store.get_provider_step_journal(record.journal_id).commit_status,
            "committed",
        )
        self.assertEqual(
            harness.store.get_provider_state("session-hosted")
            .provider_private_envelope.opaque_state_ref,
            envelope.opaque_state_ref,
        )

    def _begin(self, harness, adapter, request_id: str):
        journal = adapter.loop.provider_step_journal
        return journal.journal_request(
            journal.begin_request(
                session=harness.session,
                binding=harness.binding,
                provider_state=harness.store.get_provider_state("session-hosted"),
                request_id=request_id,
                turn_id="turn-hosted",
                step_index=0,
                codec=adapter.loop.provider_runtimes.resolve(
                    harness.binding
                ).private_codec,
                pairing_source_journal_id=None,
                request_lineage_digest="1" * 64,
                request_control_digest="2" * 64,
                request_phase="exploration",
                request_max_output_tokens=128,
                budget_estimated_input_tokens=32,
                budget_estimated_cost_microusd=0,
            )
        )

    def _tool_step(
        self,
        harness,
        adapter,
        *,
        request_id: str,
        provider_tool_name: str | None = None,
        provider_tool_call_id: str = "provider-call",
        provider_state_payload: bytes = b"fake-provider-state",
    ):
        journal = adapter.loop.provider_step_journal
        record = self._begin(harness, adapter, request_id)
        record = journal.accept(
            record,
            provider_response_id=f"response:{request_id}",
            provider_upstream_id=None,
        )
        codec = adapter.loop.provider_runtimes.resolve(harness.binding).private_codec
        envelope = harness.private_state_service.stage_state(
            session_id="session-hosted",
            adapter_id=harness.binding.adapter_id,
            adapter_version=harness.binding.adapter_version,
            codec_id=codec.codec_id,
            codec_version=codec.codec_version,
            schema_version=codec.schema_version,
            content_type=codec.content_type,
            payload=provider_state_payload,
            turn_generation="turn-hosted",
            provider_request_id=request_id,
        )
        record = journal.stage_provider_state(record, envelope)
        outcome = harness.orchestrator.observe_provider_tool(
            provider_tool_name=provider_tool_name or harness.read_tool_name,
            provider_tool_call_id=provider_tool_call_id,
            arguments={"value": 1},
            provider_request_id=request_id,
            provider_event_ordinal=2,
            provider_call_index=0,
            authority=harness.authority,
            context=adapter.loop.actor_context_resolver(None),
            turn_id="turn-hosted",
            policy=_no_confirmation_policy(),
        )
        record = journal.add_proposal(
            record,
            outcome.invocation.proposal_id,
            charge_tool_budget=True,
        )
        record = journal.complete_stream(record, final_output_validated=False)
        return record, outcome, envelope


def _no_confirmation_policy() -> RuntimeToolConfirmationPolicy:
    return RuntimeToolConfirmationPolicy(
        policy_revision="policy:test:1",
        require_confirmation_for_mutating=False,
        require_confirmation_for_destructive=False,
        max_tool_result_bytes=4096,
    )


def _record_result_budget(harness, journal, record, invocation):
    payload = harness.orchestrator.ledger.load_result(invocation)
    size_bytes = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )
    return journal.record_tool_result_bytes(record, total_bytes=size_bytes)


if __name__ == "__main__":
    unittest.main()
