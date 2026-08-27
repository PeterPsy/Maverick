"""CAS-backed provider-step WAL/saga without cross-collection transactions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.provider_state import ProviderPrivateEnvelope, RuntimeProviderState
from core.runtime.provider_step_models import ProviderStepJournalRecord
from core.runtime.store import RuntimeStore


PROVIDER_STEP_JOURNAL_SCHEMA_VERSION = "1"
ProviderStepFaultHook = Callable[[str, ProviderStepJournalRecord], None]
PROVEN_PROVIDER_TERMINAL_FAILURES = frozenset(
    {
        "provider_budget_exceeded",
        "provider_cancelled",
        "provider_output_incomplete",
    }
)


class ProviderStepJournal:
    """Advance one durable request saga with idempotent, revision-fenced writes."""

    def __init__(
        self,
        *,
        store: RuntimeStore,
        fault_hook: ProviderStepFaultHook | None = None,
    ) -> None:
        self.store = store
        self._fault_hook = fault_hook

    def begin_request(
        self,
        *,
        session,
        binding,
        provider_state: RuntimeProviderState,
        request_id: str,
        turn_id: str,
        step_index: int,
        codec,
        pairing_source_journal_id: str | None,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        """Persist REQUEST_READY before any transport operation can begin."""
        timestamp = now or datetime.now(tz=UTC)
        journal_id = str(
            uuid5(
                NAMESPACE_URL,
                f"maverick:provider-step:{session.workspace_id}:{session.session_id}:"
                f"{turn_id}:{request_id}",
            )
        )
        base_envelope = provider_state.provider_private_envelope
        record = ProviderStepJournalRecord(
            journal_id=journal_id,
            schema_version=PROVIDER_STEP_JOURNAL_SCHEMA_VERSION,
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            turn_id=turn_id,
            request_id=request_id,
            step_index=step_index,
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            model_provider_id=binding.model_provider_id,
            provider_protocol=binding.provider_protocol,
            provider_api_version=binding.provider_api_version,
            codec_id=codec.codec_id,
            codec_version=codec.codec_version,
            codec_schema_version=codec.schema_version,
            codec_content_type=codec.content_type,
            base_provider_state_revision=provider_state.revision,
            base_provider_state_digest=(
                None if base_envelope is None else base_envelope.content_sha256
            ),
            pairing_source_journal_id=pairing_source_journal_id,
            request_status="ready",
            acceptance_status="pending",
            stream_status="pending",
            step_status="pending",
            proposal_status="pending",
            disposition_status="pending",
            result_status="pending",
            pairing_status="pending",
            commit_status="pending",
            provider_response_id=None,
            provider_upstream_id=None,
            staged_provider_state=None,
            proposal_ids=(),
            disposition_ids=(),
            result_ids=(),
            observed_call_count=0,
            final_output_validated=False,
            stream_failure_reason_code=None,
            recovery_reason_code=None,
            recovery_detail_private_ref=None,
            revision=0,
            created_at=timestamp,
            updated_at=timestamp,
        )
        if not record.turn_id:
            raise ValueError("Provider-step journal requires a turn identity.")
        persisted = self.store.initialize_provider_step_journal(record)
        self._fault("request_ready", persisted)
        return persisted

    def journal_request(
        self, record: ProviderStepJournalRecord, *, now: datetime | None = None
    ) -> ProviderStepJournalRecord:
        if record.request_status == "journaled":
            return record
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "request_journaled",
            request_status="journaled",
            request_journaled_at=timestamp,
            now=timestamp,
        )

    def accept(
        self,
        record: ProviderStepJournalRecord,
        *,
        provider_response_id: str | None,
        provider_upstream_id: str | None,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if record.acceptance_status == "accepted":
            if (
                record.provider_response_id != provider_response_id
                or record.provider_upstream_id != provider_upstream_id
            ):
                raise RuntimeProviderStateError("provider_acceptance_identity_conflict")
            return record
        if record.request_status != "journaled" or record.commit_status != "pending":
            raise RuntimeProviderStateError("provider_acceptance_transition_invalid")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "provider_accepted",
            acceptance_status="accepted",
            provider_response_id=provider_response_id,
            provider_upstream_id=provider_upstream_id,
            accepted_at=timestamp,
            now=timestamp,
        )

    def stage_provider_state(
        self,
        record: ProviderStepJournalRecord,
        envelope: ProviderPrivateEnvelope,
        *,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if record.staged_provider_state is not None:
            existing = record.staged_provider_state
            if (
                existing.opaque_state_ref,
                existing.content_sha256,
                existing.size_bytes,
                existing.codec_identity,
                existing.provider_request_id,
                existing.turn_generation,
            ) != (
                envelope.opaque_state_ref,
                envelope.content_sha256,
                envelope.size_bytes,
                envelope.codec_identity,
                envelope.provider_request_id,
                envelope.turn_generation,
            ):
                raise RuntimeProviderStateError("provider_staged_state_identity_conflict")
            return record
        if record.acceptance_status != "accepted" or record.commit_status != "pending":
            raise RuntimeProviderStateError("provider_staged_state_transition_invalid")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "provider_state_staged",
            step_status="staged",
            staged_provider_state=envelope,
            staged_at=timestamp,
            now=timestamp,
        )

    def add_proposal(
        self,
        record: ProviderStepJournalRecord,
        proposal_id: str,
        *,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if proposal_id in record.proposal_ids:
            return record
        return self._update(
            record,
            "proposal_persisted",
            proposal_ids=(*record.proposal_ids, proposal_id),
            observed_call_count=record.observed_call_count + 1,
            now=now,
        )

    def complete_stream(
        self,
        record: ProviderStepJournalRecord,
        *,
        final_output_validated: bool,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if record.stream_status == "completed":
            if record.final_output_validated != final_output_validated:
                raise RuntimeProviderStateError("provider_stream_terminal_conflict")
            return record
        if record.acceptance_status != "accepted":
            raise RuntimeProviderStateError("provider_stream_completion_without_acceptance")
        timestamp = now or datetime.now(tz=UTC)
        no_calls = record.observed_call_count == 0
        if final_output_validated != no_calls:
            raise RuntimeProviderStateError("provider_stream_terminal_invalid")
        return self._update(
            record,
            "provider_stream_completed",
            stream_status="completed",
            proposal_status="not_applicable" if no_calls else "complete",
            disposition_status="not_applicable" if no_calls else record.disposition_status,
            result_status="not_applicable" if no_calls else record.result_status,
            pairing_status="not_applicable" if no_calls else record.pairing_status,
            final_output_validated=final_output_validated,
            stream_completed_at=timestamp,
            proposals_completed_at=timestamp,
            now=timestamp,
        )

    def fail_stream(
        self,
        record: ProviderStepJournalRecord,
        *,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if record.stream_status == "failed":
            if record.stream_failure_reason_code != reason_code:
                raise RuntimeProviderStateError("provider_stream_terminal_conflict")
            return record
        if record.stream_status != "pending" or record.commit_status != "pending":
            return record
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "provider_stream_failed",
            stream_status="failed",
            stream_failure_reason_code=reason_code,
            stream_failed_at=timestamp,
            now=timestamp,
        )

    def add_disposition(
        self,
        record: ProviderStepJournalRecord,
        disposition_id: str,
        *,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if disposition_id in record.disposition_ids:
            return record
        return self._update(
            record,
            "disposition_persisted",
            disposition_ids=(*record.disposition_ids, disposition_id),
            now=now,
        )

    def complete_dispositions(
        self, record: ProviderStepJournalRecord, *, now: datetime | None = None
    ) -> ProviderStepJournalRecord:
        if record.disposition_status == "complete":
            return record
        if (
            record.proposal_status != "complete"
            or len(record.disposition_ids) != len(record.proposal_ids)
        ):
            raise RuntimeProviderStateError("provider_dispositions_incomplete")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "dispositions_completed",
            disposition_status="complete",
            dispositions_completed_at=timestamp,
            now=timestamp,
        )

    def add_result(
        self,
        record: ProviderStepJournalRecord,
        result_id: str,
        *,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if result_id in record.result_ids:
            return record
        return self._update(
            record,
            "result_persisted",
            result_ids=(*record.result_ids, result_id),
            now=now,
        )

    def mark_pairing_ready(
        self, record: ProviderStepJournalRecord, *, now: datetime | None = None
    ) -> ProviderStepJournalRecord:
        if record.pairing_status in {"ready", "consumed"}:
            return record
        if (
            record.stream_status != "completed"
            or record.step_status != "staged"
            or record.disposition_status != "complete"
            or len(record.result_ids) != len(record.proposal_ids)
        ):
            raise RuntimeProviderStateError("provider_pairing_not_reconstructible")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "pairing_ready",
            result_status="complete",
            pairing_status="ready",
            results_completed_at=timestamp,
            pairing_ready_at=timestamp,
            now=timestamp,
        )

    def mark_committed(
        self, record: ProviderStepJournalRecord, *, now: datetime | None = None
    ) -> ProviderStepJournalRecord:
        if record.commit_status == "committed":
            return record
        if record.step_status != "staged" or record.stream_status != "completed":
            raise RuntimeProviderStateError("provider_step_commit_invalid")
        if not record.final_output_validated and record.pairing_status != "ready":
            raise RuntimeProviderStateError("provider_step_commit_before_pairing")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "committed",
            commit_status="committed",
            committed_at=timestamp,
            now=timestamp,
        )

    def mark_pairing_consumed(
        self, record: ProviderStepJournalRecord, *, now: datetime | None = None
    ) -> ProviderStepJournalRecord:
        if record.pairing_status == "consumed":
            return record
        if record.commit_status != "committed" or record.pairing_status != "ready":
            raise RuntimeProviderStateError("provider_pairing_consumption_invalid")
        return self._update(record, "pairing_consumed", pairing_status="consumed", now=now)

    def roll_back(
        self, record: ProviderStepJournalRecord, *, now: datetime | None = None
    ) -> ProviderStepJournalRecord:
        if record.commit_status == "rolled_back":
            return record
        if record.acceptance_status == "accepted" or record.commit_status != "pending":
            raise RuntimeProviderStateError("provider_step_rollback_not_proven")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "rolled_back",
            commit_status="rolled_back",
            rolled_back_at=timestamp,
            now=timestamp,
        )

    def roll_back_proven_terminal_failure(
        self,
        record: ProviderStepJournalRecord,
        *,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        """Return to the last commit only for an explicit no-state provider terminal."""
        if record.commit_status == "rolled_back":
            return record
        if not self.is_proven_terminal_failure(record):
            raise RuntimeProviderStateError("provider_terminal_rollback_not_proven")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "rolled_back",
            commit_status="rolled_back",
            rolled_back_at=timestamp,
            now=timestamp,
        )

    @staticmethod
    def is_proven_terminal_failure(record: ProviderStepJournalRecord) -> bool:
        return (
            record.acceptance_status == "accepted"
            and record.stream_status == "failed"
            and record.stream_failure_reason_code
            in PROVEN_PROVIDER_TERMINAL_FAILURES
            and record.staged_provider_state is None
            and record.observed_call_count == 0
            and not record.proposal_ids
        )

    def require_recovery(
        self,
        record: ProviderStepJournalRecord,
        *,
        reason_code: str,
        detail_private_ref: str | None,
        now: datetime | None = None,
    ) -> ProviderStepJournalRecord:
        if record.commit_status == "recovery_required":
            if (
                record.recovery_reason_code != reason_code
                or record.recovery_detail_private_ref != detail_private_ref
            ):
                raise RuntimeProviderStateError(
                    "provider_recovery_identity_conflict"
                )
            return record
        if record.commit_status in {"committed", "rolled_back"}:
            raise RuntimeProviderStateError("provider_terminal_step_cannot_require_recovery")
        timestamp = now or datetime.now(tz=UTC)
        return self._update(
            record,
            "recovery_required",
            commit_status="recovery_required",
            recovery_reason_code=reason_code,
            recovery_detail_private_ref=detail_private_ref,
            recovery_required_at=timestamp,
            now=timestamp,
        )

    def _update(
        self,
        record: ProviderStepJournalRecord,
        fault_point: str,
        *,
        now: datetime | None = None,
        **updates: object,
    ) -> ProviderStepJournalRecord:
        timestamp = now or datetime.now(tz=UTC)
        updated = replace(
            record,
            **updates,
            revision=record.revision + 1,
            updated_at=timestamp,
        )
        persisted = self.store.update_provider_step_journal(
            updated,
            expected_revision=record.revision,
        )
        self._fault(fault_point, persisted)
        return persisted

    def _fault(self, point: str, record: ProviderStepJournalRecord) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point, record)
