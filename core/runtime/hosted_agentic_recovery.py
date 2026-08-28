"""Deterministic recovery for the hosted provider-step WAL and tool ledger."""

from __future__ import annotations

from dataclasses import dataclass
import json
from uuid import NAMESPACE_URL, uuid5

from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedProviderStateInspection,
)
from core.runtime.lifecycle_service_children import transition_runtime_session
from core.runtime.lifecycle_service_events import record_runtime_turn_event_once
from core.runtime.public_status import public_runtime_recovery_reason_code
from core.runtime.provider_private_state import (
    ProviderPrivateStateError,
    ProviderPrivateStateService,
    public_provider_private_reason,
)
from core.runtime.provider_step_journal import ProviderStepJournal
from core.runtime.provider_step_models import ProviderStepJournalRecord
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_models import ToolInvocationRecord


@dataclass(frozen=True)
class HostedRecoveryResult:
    recovered: bool
    reason_code: str
    trigger: str
    inspected_journals: int = 0
    committed_journals: int = 0
    rolled_back_journals: int = 0
    recovered_pairings: int = 0
    execution_unknown_count: int = 0


class _RecoveryAmbiguous(RuntimeError):
    def __init__(
        self,
        reason_code: str,
        detail_code: str,
        journal: ProviderStepJournalRecord | None = None,
    ) -> None:
        super().__init__(detail_code)
        self.reason_code = reason_code
        self.detail_code = detail_code
        self.journal = journal


class HostedAgenticRecovery:
    """Reconcile WAL transitions using only pinned codec facts and CAS writes."""

    def __init__(
        self,
        *,
        journal: ProviderStepJournal,
        tool_ledger: RuntimeToolLedger,
        private_state_service: ProviderPrivateStateService,
    ) -> None:
        self.journal = journal
        self.tool_ledger = tool_ledger
        self.private_state_service = private_state_service

    def recover(
        self,
        *,
        session,
        binding,
        provider_runtime,
        trigger: str,
    ) -> HostedRecoveryResult:
        normalized_trigger = str(trigger or "unspecified").strip() or "unspecified"
        persisted_session = self.journal.store.get_session(session.session_id)
        if persisted_session.status == "recovery_required":
            return HostedRecoveryResult(
                recovered=False,
                reason_code=(
                    persisted_session.recovery_reason_code
                    or "provider_state_ambiguous"
                ),
                trigger=normalized_trigger,
            )
        records = self.journal.store.list_provider_step_journals(
            session_id=session.session_id
        )
        if not records:
            return self._recover_legacy_executing(
                session=session,
                binding=binding,
                provider_runtime=provider_runtime,
                trigger=normalized_trigger,
            )
        committed = 0
        rolled_back = 0
        recovered_pairings = 0
        unknown = 0
        try:
            self._validate_chain(records, binding=binding, provider_runtime=provider_runtime)
            self._repair_consumed_pairings(records)
            for original in records:
                record = self.journal.store.get_provider_step_journal(
                    original.journal_id
                )
                if record.commit_status in {"committed", "rolled_back"}:
                    continue
                if record.commit_status == "recovery_required":
                    raise _RecoveryAmbiguous(
                        record.recovery_reason_code or "provider_state_ambiguous",
                        "provider_step_already_quarantined",
                        record,
                    )
                if self.journal.is_proven_terminal_failure(record):
                    self.journal.roll_back_proven_terminal_failure(record)
                    rolled_back += 1
                    continue
                if record.acceptance_status != "accepted":
                    if record.staged_provider_state is not None:
                        raise _RecoveryAmbiguous(
                            "provider_state_ambiguous",
                            "provider_state_staged_without_acceptance",
                            record,
                        )
                    self.journal.roll_back(record)
                    rolled_back += 1
                    continue
                record, step_unknown = self._recover_accepted_step(
                    record,
                    session=session,
                    binding=binding,
                    provider_runtime=provider_runtime,
                )
                unknown += step_unknown
                if record.commit_status == "committed":
                    committed += 1
                    if record.pairing_source_journal_id:
                        source = self.journal.store.get_provider_step_journal(
                            record.pairing_source_journal_id
                        )
                        if source.pairing_status == "ready":
                            self.journal.mark_pairing_consumed(source)
                            recovered_pairings += 1
            refreshed = self.journal.store.list_provider_step_journals(
                session_id=session.session_id
            )
            self._repair_consumed_pairings(refreshed)
            self._require_single_pending_pairing(refreshed)
            self._require_pending_pairing_owner_active(refreshed)
            for record in refreshed:
                if record.commit_status == "committed" and record.final_output_validated:
                    self._validate_final_output(
                        record,
                        session=session,
                        binding=binding,
                        provider_runtime=provider_runtime,
                    )
                    if normalized_trigger == "startup_worker_loss":
                        self._materialize_final_events(
                            record,
                            session=session,
                            binding=binding,
                            provider_runtime=provider_runtime,
                        )
        except _RecoveryAmbiguous as error:
            self._quarantine(
                session=session,
                binding=binding,
                provider_runtime=provider_runtime,
                trigger=normalized_trigger,
                error=error,
            )
            return HostedRecoveryResult(
                recovered=False,
                reason_code=error.reason_code,
                trigger=normalized_trigger,
                inspected_journals=len(records),
                committed_journals=committed,
                rolled_back_journals=rolled_back,
                recovered_pairings=recovered_pairings,
                execution_unknown_count=unknown,
            )
        except Exception as error:
            ambiguous = _RecoveryAmbiguous(
                "provider_state_ambiguous",
                f"provider_recovery_internal:{type(error).__name__}",
                next(
                    (
                        item
                        for item in records
                        if item.commit_status not in {"committed", "rolled_back"}
                    ),
                    None,
                ),
            )
            self._quarantine(
                session=session,
                binding=binding,
                provider_runtime=provider_runtime,
                trigger=normalized_trigger,
                error=ambiguous,
            )
            return HostedRecoveryResult(
                recovered=False,
                reason_code=ambiguous.reason_code,
                trigger=normalized_trigger,
                inspected_journals=len(records),
                committed_journals=committed,
                rolled_back_journals=rolled_back,
                recovered_pairings=recovered_pairings,
                execution_unknown_count=unknown,
            )
        return HostedRecoveryResult(
            recovered=True,
            reason_code="recovered",
            trigger=normalized_trigger,
            inspected_journals=len(records),
            committed_journals=committed,
            rolled_back_journals=rolled_back,
            recovered_pairings=recovered_pairings,
            execution_unknown_count=unknown,
        )

    def pending_pairing(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> ProviderStepJournalRecord | None:
        """Return only the current turn's sole committed, unconsumed pairing."""
        records = self.journal.store.list_provider_step_journals(session_id=session_id)
        pending = [
            item
            for item in records
            if item.commit_status == "committed" and item.pairing_status == "ready"
        ]
        if len(pending) > 1:
            raise HostedAgenticLoopError("provider_pairing_ambiguous")
        if not pending:
            return None
        record = pending[0]
        envelope = record.staged_provider_state
        state = self.journal.store.get_provider_state(session_id)
        current = state.provider_private_envelope
        if (
            record.turn_id != turn_id
            or envelope is None
            or current is None
            or current.opaque_state_ref != envelope.opaque_state_ref
            or current.provider_request_id != record.request_id
            or current.turn_generation != record.turn_id
            or envelope.provider_request_id != record.request_id
            or envelope.turn_generation != record.turn_id
        ):
            raise HostedAgenticLoopError("provider_pairing_ambiguous")
        return record

    def contain_terminal_pairing(
        self,
        *,
        session,
        binding,
        provider_runtime,
        turn_id: str,
        trigger: str,
        terminal_reason_code: str,
    ) -> str | None:
        """Quarantine any pairing a failed turn or a different user turn could consume."""
        try:
            records = self.journal.store.list_provider_step_journals(
                session_id=session.session_id
            )
        except Exception:
            error = _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "terminal_provider_journal_unavailable",
            )
            self._quarantine(
                session=session,
                binding=binding,
                provider_runtime=provider_runtime,
                trigger=trigger,
                error=error,
            )
            persisted = self.journal.store.get_session(session.session_id)
            return (
                persisted.recovery_reason_code
                if persisted.status == "recovery_required"
                else "provider_state_ambiguous"
            )
        ready = [
            item
            for item in records
            if item.commit_status == "committed" and item.pairing_status == "ready"
        ]
        unresolved = [
            item
            for item in records
            if item.commit_status in {"pending", "recovery_required"}
        ]
        if not ready and not unresolved:
            return None
        source = next(
            (item for item in ready if item.turn_id == turn_id),
            ready[-1] if ready else unresolved[-1],
        )
        public_reason = (
            "provider_pairing_ambiguous" if ready else "provider_state_ambiguous"
        )
        error = _RecoveryAmbiguous(
            public_reason,
            (
                "terminal_turn_left_unresolved_provider_state:"
                f"{str(terminal_reason_code or 'unknown').strip() or 'unknown'}"
            ),
            source,
        )
        self._quarantine(
            session=session,
            binding=binding,
            provider_runtime=provider_runtime,
            trigger=trigger,
            error=error,
        )
        persisted = self.journal.store.get_session(session.session_id)
        return (
            persisted.recovery_reason_code
            if persisted.status == "recovery_required"
            else public_reason
        )

    def pairing_results(
        self,
        record: ProviderStepJournalRecord,
    ) -> tuple[ToolInvocationRecord, ...]:
        """Rebuild exact result ordering from proposal IDs, never collection order."""
        if record.commit_status != "committed" or record.pairing_status != "ready":
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "provider_pairing_not_ready",
                record,
            )
        invocations = tuple(
            self.tool_ledger.store.get_tool_invocation(proposal_id)
            for proposal_id in record.proposal_ids
        )
        if any(
            item.result_id is None
            or item.disposition_id is None
            or not _has_pairable_tool_result(item)
            for item in invocations
        ):
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "provider_pairing_result_missing",
                record,
            )
        return invocations

    def _recover_accepted_step(
        self,
        record: ProviderStepJournalRecord,
        *,
        session,
        binding,
        provider_runtime,
    ) -> tuple[ProviderStepJournalRecord, int]:
        envelope = record.staged_provider_state
        if envelope is None:
            codec = provider_runtime.private_codec
            envelope = self.private_state_service.recover_staged_state_for_request(
                session_id=session.session_id,
                adapter_id=binding.adapter_id,
                adapter_version=binding.adapter_version,
                codec_id=codec.codec_id,
                codec_version=codec.codec_version,
                schema_version=codec.schema_version,
                content_type=codec.content_type,
                provider_request_id=record.request_id,
                turn_generation=record.turn_id,
            )
            if envelope is not None:
                record = self.journal.stage_provider_state(record, envelope)
        if envelope is None or record.step_status != "staged":
            raise _RecoveryAmbiguous(
                "provider_acceptance_ambiguous",
                "provider_acceptance_without_staged_state",
                record,
            )
        self._validate_envelope(record, provider_runtime=provider_runtime)
        inspection = self._inspect(
            record,
            session=session,
            binding=binding,
            provider_runtime=provider_runtime,
        )
        record = self._repair_orphan_proposals(
            record,
            inspection=inspection,
            binding=binding,
        )
        if record.observed_call_count == 0:
            if record.final_output_status == "pending":
                codec = provider_runtime.private_codec
                recovered_output = (
                    self.private_state_service.recover_final_output_for_request(
                        session_id=session.session_id,
                        adapter_id=binding.adapter_id,
                        adapter_version=binding.adapter_version,
                        codec_id=codec.codec_id,
                        codec_version=codec.codec_version,
                        schema_version=codec.schema_version,
                        journal_id=record.journal_id,
                        provider_request_id=record.request_id,
                    )
                )
                if recovered_output is not None:
                    private_ref, content_sha256, size_bytes = recovered_output
                    record = self.journal.stage_final_output(
                        record,
                        output_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"maverick:provider-final-output:{record.journal_id}",
                            )
                        ),
                        private_ref=private_ref,
                        content_sha256=content_sha256,
                        size_bytes=size_bytes,
                    )
            if record.final_output_status != "ready":
                raise _RecoveryAmbiguous(
                    "provider_acceptance_ambiguous",
                    "provider_final_output_not_durably_validated",
                    record,
                )
            self._validate_final_output(
                record,
                session=session,
                binding=binding,
                provider_runtime=provider_runtime,
            )
            if record.stream_status == "pending":
                record = self.journal.complete_stream(
                    record,
                    final_output_validated=True,
                )
            if record.stream_status != "completed" or not record.final_output_validated:
                raise _RecoveryAmbiguous(
                    "provider_acceptance_ambiguous",
                    "provider_final_output_not_durably_validated",
                    record,
                )
            if inspection is not None and inspection.pending_tool_calls:
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_final_state_contains_pending_calls",
                    record,
                )
        else:
            self._require_observed_calls(record, inspection=inspection)
            if record.stream_status == "pending":
                record = self.journal.complete_stream(
                    record,
                    final_output_validated=False,
                )
            if record.stream_status != "completed":
                raise _RecoveryAmbiguous(
                    "provider_acceptance_ambiguous",
                    "provider_tool_stream_not_reconstructible",
                    record,
                )
            record, execution_unknown = self._recover_tool_results(record)
            if execution_unknown:
                raise _RecoveryAmbiguous(
                    "tool_execution_ambiguous",
                    "tool_effect_boundary_without_terminal_result",
                    record,
                )
        current = self.journal.store.get_provider_state(session.session_id)
        committed_envelope = current.provider_private_envelope
        if committed_envelope is not None and (
            committed_envelope.opaque_state_ref == envelope.opaque_state_ref
        ):
            pass
        elif current.revision == record.base_provider_state_revision:
            self.private_state_service.promote_staged_state(
                session_id=session.session_id,
                adapter_id=binding.adapter_id,
                adapter_version=binding.adapter_version,
                envelope=envelope,
                expected_revision=record.base_provider_state_revision,
            )
        else:
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "provider_state_revision_diverged_during_recovery",
                record,
            )
        record = self.journal.store.get_provider_step_journal(record.journal_id)
        return self.journal.mark_committed(record), 0

    def _repair_orphan_proposals(
        self,
        record: ProviderStepJournalRecord,
        *,
        inspection: HostedProviderStateInspection | None,
        binding,
    ) -> ProviderStepJournalRecord:
        """Complete the WAL half of a proposal insert interrupted between stores."""
        if inspection is not None and inspection.pending_tool_calls:
            candidates = []
            for call_id, safe_name in inspection.pending_tool_calls:
                item = self.tool_ledger.store.find_tool_invocation_by_provider_call(
                    session_id=record.session_id,
                    turn_id=record.turn_id,
                    provider_tool_call_id=call_id,
                )
                if item is None or item.provider_safe_name != safe_name:
                    raise _RecoveryAmbiguous(
                        "provider_pairing_ambiguous",
                        "provider_observed_call_missing_from_ledger",
                        record,
                    )
                candidates.append(item)
        else:
            candidates = [
                item
                for item in self.tool_ledger.store.list_tool_invocations(
                    session_id=record.session_id,
                    turn_id=record.turn_id,
                )
                if item.provider_request_id == record.request_id
            ]
            candidates.sort(
                key=lambda item: (item.provider_call_index, item.proposal_id)
            )
        if candidates and (
            (
                inspection is None
                and [item.provider_call_index for item in candidates]
                != list(range(len(candidates)))
            )
            or len({item.provider_tool_call_id for item in candidates})
            != len(candidates)
        ):
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "provider_orphan_proposal_order_invalid",
                record,
            )
        candidate_ids = tuple(item.proposal_id for item in candidates)
        if record.proposal_ids != candidate_ids[: len(record.proposal_ids)]:
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "provider_journal_proposal_order_conflict",
                record,
            )
        prior_charges = sum(
            item.budget_tool_call_charges
            for item in self.journal.store.list_provider_step_journals(
                session_id=record.session_id,
                turn_id=record.turn_id,
            )
            if item.step_index < record.step_index
        )
        tool_call_ceiling = min(
            binding.profile_policy_ceiling_snapshot.max_tool_calls_per_turn,
            binding.workspace_policy_ceiling_snapshot.max_tool_calls_per_turn,
        )
        for candidate in candidates[len(record.proposal_ids) :]:
            charge_tool_budget = (
                record.request_phase == "exploration"
                and record.budget_tool_call_charges == record.observed_call_count
                and prior_charges + record.budget_tool_call_charges
                < tool_call_ceiling
            )
            record = self.journal.add_proposal(
                record,
                candidate.proposal_id,
                charge_tool_budget=charge_tool_budget,
            )
        return record

    def _recover_tool_results(
        self,
        record: ProviderStepJournalRecord,
    ) -> tuple[ProviderStepJournalRecord, int]:
        execution_unknown = 0
        total_result_bytes = 0
        for call_index, proposal_id in enumerate(record.proposal_ids):
            invocation = self.tool_ledger.store.get_tool_invocation(proposal_id)
            forced_denial: tuple[str, str] | None = None
            if record.request_phase != "exploration":
                forced_denial = (
                    "budget_denied",
                    "agent_finalization_tool_call_forbidden",
                )
            elif call_index >= record.budget_tool_call_charges:
                forced_denial = (
                    "budget_denied",
                    "agent_tool_call_limit_reached",
                )
            elif record.observed_call_count > 1:
                forced_denial = (
                    "parallel_denied",
                    "provider_parallel_tool_calls_forbidden",
                )
            if forced_denial is not None:
                resolution_status, failure_reason = forced_denial
                if invocation.state == "denied":
                    if (
                        invocation.resolution_status != resolution_status
                        or invocation.failure_reason != failure_reason
                    ):
                        raise _RecoveryAmbiguous(
                            "provider_pairing_ambiguous",
                            "provider_budget_disposition_mismatch",
                            record,
                        )
                elif invocation.state in {"proposed", "validating", "validated"}:
                    invocation = self.tool_ledger.deny(
                        invocation,
                        resolution_status=resolution_status,
                        failure_reason=failure_reason,
                    )
                else:
                    raise _RecoveryAmbiguous(
                        "provider_pairing_ambiguous",
                        "provider_budget_disposition_missing_before_effect",
                        record,
                    )
            elif invocation.state == "executing":
                invocation = self.tool_ledger.recover_executing(
                    invocation,
                    safe_to_retry=False,
                )
            elif invocation.state in {
                "proposed",
                "validating",
                "validated",
                "awaiting_confirmation",
                "authorized",
            }:
                invocation = self.tool_ledger.cancel_before_effect(invocation)
            elif invocation.result_id is None and invocation.state in {
                "denied",
                "failed",
                "cancelled",
                "expired",
                "execution_unknown",
            }:
                invocation = self.tool_ledger.attach_terminal_result(invocation)
            if invocation.state == "execution_unknown":
                execution_unknown += 1
            if invocation.disposition_id is None:
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "tool_disposition_missing",
                    record,
                )
            record = self.journal.add_disposition(
                record,
                invocation.disposition_id,
            )
            if (
                invocation.result_id is None
                or not _has_pairable_tool_result(invocation)
            ):
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "tool_result_missing",
                    record,
                )
            record = self.journal.add_result(record, invocation.result_id)
            result = (
                self.tool_ledger.load_result(invocation)
                if invocation.result_private_ref is not None
                else {
                    "error": (
                        invocation.failure_reason or f"tool_{invocation.state}"
                    )
                }
            )
            serialized_size = len(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            )
            original_size = (
                invocation.result_summary.get("original_serialized_bytes")
                if isinstance(invocation.result_summary, dict)
                else None
            )
            if isinstance(original_size, int) and not isinstance(
                original_size,
                bool,
            ):
                serialized_size = max(serialized_size, original_size)
            total_result_bytes += serialized_size
        record = self.journal.record_tool_result_bytes(
            record,
            total_bytes=total_result_bytes,
        )
        record = self.journal.complete_dispositions(record)
        record = self.journal.mark_pairing_ready(record)
        return record, execution_unknown

    def _inspect(
        self,
        record: ProviderStepJournalRecord,
        *,
        session,
        binding,
        provider_runtime,
    ) -> HostedProviderStateInspection | None:
        inspector = provider_runtime.private_state_inspector
        if inspector is None:
            return None
        envelope = record.staged_provider_state
        assert envelope is not None
        try:
            payload = self.private_state_service.read_staged_state(
                session_id=session.session_id,
                adapter_id=binding.adapter_id,
                adapter_version=binding.adapter_version,
                envelope=envelope,
            )
            return inspector(payload)
        except Exception as error:
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                f"provider_staged_state_decode_failed:{type(error).__name__}",
                record,
            ) from error

    def _require_observed_calls(
        self,
        record: ProviderStepJournalRecord,
        *,
        inspection: HostedProviderStateInspection | None,
    ) -> None:
        if (
            record.observed_call_count != len(record.proposal_ids)
            or not record.proposal_ids
        ):
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "provider_proposal_count_mismatch",
                record,
            )
        invocations = [
            self.tool_ledger.store.get_tool_invocation(proposal_id)
            for proposal_id in record.proposal_ids
        ]
        if any(
            item.provider_request_id != record.request_id
            or item.provider_call_index != index
            for index, item in enumerate(invocations)
        ):
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "provider_proposal_identity_mismatch",
                record,
            )
        if inspection is not None:
            observed = tuple(
                (item.provider_tool_call_id, item.provider_safe_name)
                for item in invocations
            )
            if observed != inspection.pending_tool_calls:
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_staged_pairing_mismatch",
                    record,
                )

    def _validate_chain(self, records, *, binding, provider_runtime) -> None:
        identities = {
            (
                item.runtime_engine_id,
                item.adapter_id,
                item.adapter_version,
                item.model_provider_id,
                item.provider_protocol,
                item.provider_api_version,
                item.codec_id,
                item.codec_version,
                item.codec_schema_version,
                item.codec_content_type,
            )
            for item in records
        }
        expected = (
            binding.runtime_engine_id,
            binding.adapter_id,
            binding.adapter_version,
            binding.model_provider_id,
            binding.provider_protocol,
            binding.provider_api_version,
            provider_runtime.private_codec.codec_id,
            provider_runtime.private_codec.codec_version,
            provider_runtime.private_codec.schema_version,
            provider_runtime.private_codec.content_type,
        )
        if identities != {expected}:
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "provider_recovery_binding_or_codec_mismatch",
                records[-1],
            )
        valid_phases = {
            "exploration",
            "finalization",
            "finalization_recovery",
        }
        records_by_turn: dict[str, list[ProviderStepJournalRecord]] = {}
        for item in records:
            records_by_turn.setdefault(item.turn_id, []).append(item)
        for turn_records in records_by_turn.values():
            ordered = sorted(turn_records, key=lambda item: item.step_index)
            phases = tuple(item.request_phase for item in ordered)
            first_finalization = next(
                (
                    index
                    for index, phase in enumerate(phases)
                    if phase != "exploration"
                ),
                len(phases),
            )
            recovery_index = next(
                (
                    index
                    for index, phase in enumerate(phases)
                    if phase == "finalization_recovery"
                ),
                None,
            )
            normal_finalizations = [
                item for item in ordered if item.request_phase == "finalization"
            ]
            phase_chain_invalid = (
                any(phase not in valid_phases for phase in phases)
                or phases.count("finalization_recovery") > 1
                or "exploration" in phases[first_finalization:]
                or (
                    recovery_index is not None
                    and recovery_index != len(phases) - 1
                )
                or any(
                    item.request_phase == "finalization_recovery"
                    and item.pairing_source_journal_id is None
                    for item in ordered
                )
                or any(
                    item.acceptance_status == "accepted"
                    or item.commit_status != "rolled_back"
                    for item in normal_finalizations[:-1]
                )
            )
            if phase_chain_invalid:
                raise _RecoveryAmbiguous(
                    "provider_state_ambiguous",
                    "provider_finalization_phase_chain_invalid",
                    ordered[-1],
                )
        by_id = {item.journal_id: item for item in records}
        if len(by_id) != len(records):
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "provider_journal_identity_collision",
                records[-1],
            )
        for item in records:
            source_id = item.pairing_source_journal_id
            if source_id is None:
                continue
            source = by_id.get(source_id)
            if source is None:
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_pairing_source_missing",
                    item,
                )
            if (
                source.session_id != item.session_id
                or source.workspace_id != item.workspace_id
                or source.turn_id != item.turn_id
                or source.step_index >= item.step_index
                or source.commit_status != "committed"
                or source.pairing_status not in {"ready", "consumed"}
                or not item.request_lineage_digest
                or len(item.request_lineage_digest) != 64
                or source.request_lineage_digest != item.request_lineage_digest
                or (
                    item.request_phase == "finalization_recovery"
                    and source.request_phase != "finalization"
                )
                or (
                    source.request_phase in {
                        "finalization",
                        "finalization_recovery",
                    }
                    and item.request_phase != "finalization_recovery"
                )
            ):
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_pairing_lineage_mismatch",
                    item,
                )

    @staticmethod
    def _validate_envelope(record, *, provider_runtime) -> None:
        envelope = record.staged_provider_state
        assert envelope is not None
        codec = provider_runtime.private_codec
        if (
            envelope.codec_id,
            envelope.codec_version,
            envelope.schema_version,
            envelope.content_type,
            envelope.provider_request_id,
            envelope.turn_generation,
        ) != (
            codec.codec_id,
            codec.codec_version,
            codec.schema_version,
            codec.content_type,
            record.request_id,
            record.turn_id,
        ):
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "provider_staged_envelope_identity_mismatch",
                record,
            )

    def _repair_consumed_pairings(self, records) -> None:
        by_id = {item.journal_id: item for item in records}
        committed_sources = {
            item.pairing_source_journal_id
            for item in records
            if item.commit_status == "committed"
            and item.pairing_source_journal_id is not None
        }
        for source in records:
            if (
                source.commit_status == "committed"
                and source.pairing_status == "consumed"
                and source.journal_id not in committed_sources
            ):
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_pairing_consumed_without_committed_child",
                    source,
                )
        for child in records:
            source_id = child.pairing_source_journal_id
            if child.commit_status != "committed" or source_id is None:
                continue
            source = self.journal.store.get_provider_step_journal(source_id)
            if source.pairing_status == "ready":
                self.journal.mark_pairing_consumed(source)
            elif source.pairing_status != "consumed":
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_pairing_source_not_ready",
                    child,
                )
            by_id[source_id] = self.journal.store.get_provider_step_journal(source_id)

    @staticmethod
    def _require_single_pending_pairing(records) -> None:
        ready = [
            item
            for item in records
            if item.commit_status == "committed" and item.pairing_status == "ready"
        ]
        if len(ready) > 1:
            raise _RecoveryAmbiguous(
                "provider_pairing_ambiguous",
                "multiple_unconsumed_provider_pairings",
                ready[-1],
            )

    def _require_pending_pairing_owner_active(self, records) -> None:
        for record in records:
            if record.commit_status != "committed" or record.pairing_status != "ready":
                continue
            try:
                turn = self.journal.store.get_turn(record.turn_id)
            except Exception as error:
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_pairing_owner_turn_missing",
                    record,
                ) from error
            if turn.session_id != record.session_id or turn.status not in {
                "queued",
                "active",
                "waiting_for_tool_confirmation",
            }:
                raise _RecoveryAmbiguous(
                    "provider_pairing_ambiguous",
                    "provider_pairing_owner_turn_terminal",
                    record,
                )

    def _validate_final_output(
        self,
        record,
        *,
        session,
        binding,
        provider_runtime,
    ) -> None:
        if (
            record.final_output_status not in {"ready", "delivered"}
            or record.final_completion_status not in {"ready", "delivered"}
            or not record.final_output_id
            or not record.final_output_private_ref
            or not record.final_output_sha256
            or record.final_output_size_bytes is None
        ):
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "provider_final_output_identity_unproven",
                record,
            )
        try:
            self.private_state_service.read_final_output(
                session_id=session.session_id,
                adapter_id=binding.adapter_id,
                adapter_version=binding.adapter_version,
                codec_id=provider_runtime.private_codec.codec_id,
                codec_version=provider_runtime.private_codec.codec_version,
                schema_version=provider_runtime.private_codec.schema_version,
                private_ref=record.final_output_private_ref,
                content_sha256=record.final_output_sha256,
                size_bytes=record.final_output_size_bytes,
            )
        except Exception as error:
            raise _RecoveryAmbiguous(
                "provider_state_ambiguous",
                "provider_final_output_payload_unproven",
                record,
            ) from error

    def _materialize_final_events(
        self,
        record,
        *,
        session,
        binding,
        provider_runtime,
    ) -> None:
        """Drain a committed final outbox before backend restart closes its turn."""
        assert record.final_output_id is not None
        assert record.final_output_private_ref is not None
        assert record.final_output_sha256 is not None
        assert record.final_output_size_bytes is not None
        output_text = self.private_state_service.read_final_output(
            session_id=session.session_id,
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            codec_id=provider_runtime.private_codec.codec_id,
            codec_version=provider_runtime.private_codec.codec_version,
            schema_version=provider_runtime.private_codec.schema_version,
            private_ref=record.final_output_private_ref,
            content_sha256=record.final_output_sha256,
            size_bytes=record.final_output_size_bytes,
        )
        record_runtime_turn_event_once(
            self.journal.store,
            event_id=record.final_output_id,
            session_id=session.session_id,
            turn_id=record.turn_id,
            event_type="runtime.output.final",
            payload={
                "text": output_text,
                "complete_text": output_text,
                "provider_id": binding.model_provider_id,
                "exit_code": 0,
                "delivery_id": record.final_output_id,
            },
        )
        current = self.journal.store.get_provider_step_journal(record.journal_id)
        if current.final_output_status == "ready":
            current = self.journal.mark_final_output_delivered(current)
        record_runtime_turn_event_once(
            self.journal.store,
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"maverick:provider-completed:{record.final_output_id}",
                )
            ),
            session_id=session.session_id,
            turn_id=record.turn_id,
            event_type="provider.execution.completed",
            payload={
                "output_text": output_text,
                "exit_code": 0,
                "delivery_id": record.final_output_id,
            },
        )
        if current.final_completion_status == "ready":
            self.journal.mark_final_completion_delivered(current)

    def _recover_legacy_executing(
        self,
        *,
        session,
        binding,
        provider_runtime,
        trigger: str,
    ) -> HostedRecoveryResult:
        provider_state = self.tool_ledger.store.get_provider_state(session.session_id)
        envelope = provider_state.provider_private_envelope
        if envelope is not None:
            codec = provider_runtime.private_codec
            if (
                envelope.codec_id,
                envelope.codec_version,
                envelope.schema_version,
                envelope.content_type,
            ) != (
                codec.codec_id,
                codec.codec_version,
                codec.schema_version,
                codec.content_type,
            ):
                error = _RecoveryAmbiguous(
                    "provider_state_ambiguous",
                    "legacy_provider_codec_mismatch",
                )
                self._quarantine(
                    session=session,
                    binding=binding,
                    provider_runtime=provider_runtime,
                    trigger=trigger,
                    error=error,
                )
                return HostedRecoveryResult(False, error.reason_code, trigger)
            try:
                self.private_state_service.read_state(
                    session_id=session.session_id,
                    adapter_id=binding.adapter_id,
                    adapter_version=binding.adapter_version,
                    codec_id=codec.codec_id,
                    codec_version=codec.codec_version,
                    schema_version=codec.schema_version,
                    purpose="recovery",
                )
            except ProviderPrivateStateError as cause:
                reason = public_provider_private_reason(cause)
                error = _RecoveryAmbiguous(reason, cause.reason_code)
                self._quarantine(
                    session=session,
                    binding=binding,
                    provider_runtime=provider_runtime,
                    trigger=trigger,
                    error=error,
                )
                return HostedRecoveryResult(False, reason, trigger)
        unknown = 0
        for invocation in self.tool_ledger.store.list_tool_invocations(
            session_id=session.session_id
        ):
            if invocation.state != "executing":
                continue
            recovered = self.tool_ledger.recover_executing(
                invocation,
                safe_to_retry=False,
            )
            unknown += int(recovered.state == "execution_unknown")
        if unknown:
            error = _RecoveryAmbiguous(
                "tool_execution_ambiguous",
                "legacy_tool_effect_boundary_without_journal",
            )
            self._quarantine(
                session=session,
                binding=binding,
                provider_runtime=provider_runtime,
                trigger=trigger,
                error=error,
            )
            return HostedRecoveryResult(
                False,
                error.reason_code,
                trigger,
                execution_unknown_count=unknown,
            )
        return HostedRecoveryResult(True, "recovered", trigger)

    def _quarantine(
        self,
        *,
        session,
        binding,
        provider_runtime,
        trigger: str,
        error: _RecoveryAmbiguous,
    ) -> None:
        public_reason = public_runtime_recovery_reason_code(
            status="recovery_required",
            reason_code=error.reason_code,
        ) or "runtime_state_ambiguous"

        # Containment is authoritative and always precedes optional diagnostics.
        self._quarantine_session_bounded(
            session_id=session.session_id,
            reason_code=public_reason,
        )
        self._quarantine_journal_bounded(
            journal=error.journal,
            reason_code=public_reason,
            detail_private_ref=None,
        )

        detail_ref = None
        if error.journal is not None:
            try:
                current = self.journal.store.get_provider_step_journal(
                    error.journal.journal_id
                )
                detail_ref = current.recovery_detail_private_ref
            except Exception:
                pass
        if detail_ref is None:
            try:
                detail_ref = self.private_state_service.store_recovery_detail(
                    session_id=session.session_id,
                    adapter_id=binding.adapter_id,
                    adapter_version=binding.adapter_version,
                    codec_id=provider_runtime.private_codec.codec_id,
                    codec_version=provider_runtime.private_codec.codec_version,
                    schema_version=provider_runtime.private_codec.schema_version,
                    detail={
                        "trigger": trigger,
                        "reason_code": str(error.reason_code),
                        "detail_code": error.detail_code,
                        "journal_id": (
                            None if error.journal is None else error.journal.journal_id
                        ),
                    },
                )
            except Exception:
                detail_ref = None
        if detail_ref is not None:
            self._quarantine_journal_bounded(
                journal=error.journal,
                reason_code=public_reason,
                detail_private_ref=detail_ref,
            )

    def _quarantine_session_bounded(
        self,
        *,
        session_id: str,
        reason_code: str,
    ) -> bool:
        for _attempt in range(3):
            try:
                current = self.journal.store.get_session(session_id)
            except Exception:
                continue
            if current.status == "recovery_required":
                return True
            if current.status not in {"created", "running", "stopping", "failed"}:
                return False
            try:
                transition_runtime_session(
                    self.journal.store,
                    session_id=session_id,
                    target_status="recovery_required",
                    expected_status=current.status,
                    recovery_reason_code=reason_code,
                )
                return True
            except Exception:
                try:
                    if self.journal.store.get_session(session_id).status == "recovery_required":
                        return True
                except Exception:
                    pass
        return False

    def _quarantine_journal_bounded(
        self,
        *,
        journal: ProviderStepJournalRecord | None,
        reason_code: str,
        detail_private_ref: str | None,
    ) -> bool:
        if journal is None:
            return False
        for _attempt in range(3):
            try:
                current = self.journal.store.get_provider_step_journal(
                    journal.journal_id
                )
                if current.commit_status == "recovery_required" and (
                    detail_private_ref is None
                    or current.recovery_detail_private_ref == detail_private_ref
                ):
                    return True
                self.journal.require_recovery(
                    current,
                    reason_code=reason_code,
                    detail_private_ref=detail_private_ref,
                )
                return True
            except Exception:
                continue
        return False


def _has_pairable_tool_result(invocation: ToolInvocationRecord) -> bool:
    if invocation.result_private_ref is not None:
        return True
    return invocation.state in {"failed", "execution_unknown"} and bool(
        invocation.failure_reason
    )


__all__ = ["HostedAgenticRecovery", "HostedRecoveryResult"]
