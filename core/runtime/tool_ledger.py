"""CAS-backed tool invocation, confirmation and crash-recovery state machine."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import hmac
from uuid import NAMESPACE_URL, uuid5

from core.egress.classification import CanonicalSourceClassification
from core.runtime.errors import RuntimeToolExecutionLeaseExpiredError
from core.runtime.store import RuntimeStore
from core.runtime.tool_confirmation_ledger import (
    DEFAULT_CONFIRMATION_TTL_SECONDS,
    authorize_tool_invocation,
    confirm_tool_invocation,
)
from core.runtime.tool_errors import RuntimeToolError, RuntimeToolRevisionError
from core.runtime.tool_models import (
    ToolConfirmationGrant,
    ToolEffectClass,
    ToolInvocationRecord,
    ToolInvocationState,
    ToolResolutionStatus,
)
from core.runtime.tool_private_payloads import (
    MAX_TOOL_PRIVATE_PAYLOAD_BYTES,
    RuntimeToolPrivatePayloadStore,
    canonical_tool_arguments,
    decode_tool_arguments,
    tool_arguments_digest,
    tool_arguments_summary,
)


_IDEMPOTENCY_DOMAIN = b"maverick.runtime.tool-idempotency.v1\x00"
_TRANSITIONS: dict[ToolInvocationState, frozenset[ToolInvocationState]] = {
    "proposed": frozenset({"validating", "cancelled"}),
    "validating": frozenset({"denied", "validated", "cancelled"}),
    "validated": frozenset({"awaiting_confirmation", "authorized", "denied", "cancelled"}),
    "awaiting_confirmation": frozenset({"denied", "expired", "cancelled", "authorized"}),
    "authorized": frozenset({"executing", "cancelled"}),
    "executing": frozenset({"succeeded", "failed", "cancelled", "execution_unknown", "authorized"}),
    "denied": frozenset(),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
    "execution_unknown": frozenset(),
}

class RuntimeToolLedger:
    """Persist every decision before execution and fence all updates by revision."""
    def __init__(
        self,
        *,
        store: RuntimeStore,
        private_payload_store: RuntimeToolPrivatePayloadStore,
        digest_key: bytes,
    ) -> None:
        if len(digest_key) < 32:
            raise RuntimeToolError("tool_digest_key_invalid")
        self.store = store
        self.private_payload_store = private_payload_store
        self._digest_key = bytes(digest_key)
    def propose(
        self,
        *,
        workspace_id: str,
        session_id: str,
        turn_id: str,
        provider_tool_call_id: str,
        arguments: dict[str, object] | bytes,
        policy_revision: str,
        authority_digest: str,
        tool_handle: str | None = None,
        provider_safe_name: str = "",
        provider_request_id: str = "",
        provider_event_ordinal: int = 0,
        provider_call_index: int = 0,
        effect_class: ToolEffectClass = "unclassified",
        safe_to_retry: bool = False,
        now: datetime | None = None,
    ) -> tuple[ToolInvocationRecord, bool]:
        """Insert before validation; exact provider retries deduplicate."""
        timestamp = now or datetime.now(tz=UTC)
        if (
            not all(
                isinstance(value, str) and value.strip()
                for value in (
                    workspace_id,
                    session_id,
                    turn_id,
                    provider_tool_call_id,
                    provider_safe_name or tool_handle or "",
                    policy_revision,
                    authority_digest,
                )
            )
            or not isinstance(provider_event_ordinal, int)
            or isinstance(provider_event_ordinal, bool)
            or provider_event_ordinal < 0
            or not isinstance(provider_call_index, int)
            or isinstance(provider_call_index, bool)
            or provider_call_index < 0
        ):
            raise RuntimeToolError("tool_proposal_identity_invalid")
        if isinstance(arguments, dict):
            try:
                canonical = canonical_tool_arguments(arguments)
            except RuntimeToolError:
                canonical = repr(arguments).encode("utf-8", errors="replace")
                if not canonical or len(canonical) > MAX_TOOL_PRIVATE_PAYLOAD_BYTES:
                    raise RuntimeToolError("tool_arguments_invalid")
                arguments_summary = {
                    "root_type": "malformed_json",
                    "serialized_bytes": len(canonical),
                }
            else:
                arguments_summary = tool_arguments_summary(
                    arguments,
                    serialized_bytes=len(canonical),
                )
        elif isinstance(arguments, bytes) and arguments:
            canonical = bytes(arguments)
            arguments_summary = {
                "root_type": "malformed_json",
                "serialized_bytes": len(canonical),
            }
        else:
            raise RuntimeToolError("tool_arguments_invalid")
        digest = tool_arguments_digest(digest_key=self._digest_key, canonical_arguments=canonical)
        invocation_id = str(
            uuid5(NAMESPACE_URL, f"maverick:tool:{workspace_id}:{session_id}:{turn_id}:{provider_tool_call_id}")
        )
        private_ref = _tool_arguments_private_ref(invocation_id)
        existing = self.store.find_tool_invocation_by_provider_call(
            session_id=session_id,
            turn_id=turn_id,
            provider_tool_call_id=provider_tool_call_id,
        )
        if existing is not None:
            self._require_exact_replay(
                existing,
                workspace_id,
                provider_safe_name or tool_handle or "",
                tool_handle,
                digest,
            )
            self._persist_arguments(existing, canonical)
            return existing, False
        idempotency_key = hmac.new(
            self._digest_key,
            _IDEMPOTENCY_DOMAIN + invocation_id.encode("utf-8") + digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        proposal_id = invocation_id
        record = ToolInvocationRecord(
            invocation_id=invocation_id,
            workspace_id=workspace_id,
            session_id=session_id,
            turn_id=turn_id,
            provider_tool_call_id=provider_tool_call_id,
            resolved_tool_handle=tool_handle,
            arguments_private_ref=private_ref,
            arguments_summary=arguments_summary,
            arguments_digest=digest,
            idempotency_key=idempotency_key,
            effect_class=effect_class,
            state="proposed",
            policy_revision=policy_revision,
            authority_digest=authority_digest,
            confirmation_grant_id=None,
            result_private_ref=None,
            result_summary=None,
            failure_reason=None,
            revision=0,
            created_at=timestamp,
            updated_at=timestamp,
            proposal_id=proposal_id,
            provider_safe_name=provider_safe_name or tool_handle or "",
            provider_request_id=provider_request_id,
            provider_event_ordinal=provider_event_ordinal,
            provider_call_index=provider_call_index,
            resolution_status=("resolved" if tool_handle else "unresolved"),
            safe_to_retry=safe_to_retry,
        )
        try:
            persisted = self.store.initialize_tool_invocation(record)
        except Exception:
            raced = self.store.find_tool_invocation_by_provider_call(
                session_id=session_id,
                turn_id=turn_id,
                provider_tool_call_id=provider_tool_call_id,
            )
            if raced is None:
                raise
            self._require_exact_replay(
                raced,
                workspace_id,
                provider_safe_name or tool_handle or "",
                tool_handle,
                digest,
            )
            self._persist_arguments(raced, canonical)
            return raced, False
        self._persist_arguments(persisted, canonical)
        return persisted, True

    def resolve(
        self,
        record: ToolInvocationRecord,
        *,
        tool_handle: str,
        effect_class: ToolEffectClass,
        safe_to_retry: bool,
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        """Attach a live catalog resolution after preliminary persistence."""
        if record.resolved_tool_handle is not None:
            if (
                record.resolved_tool_handle != tool_handle
                or record.effect_class != effect_class
            ):
                raise RuntimeToolError("tool_provider_call_replay_mismatch")
            return record
        return self._replace(
            record,
            resolved_tool_handle=tool_handle,
            effect_class=effect_class,
            safe_to_retry=safe_to_retry,
            resolution_status="resolved",
            now=now,
        )

    def deny(
        self,
        record: ToolInvocationRecord,
        *,
        resolution_status: ToolResolutionStatus,
        failure_reason: str,
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        """Persist a denial result before pairing; raw arguments remain private."""
        if resolution_status not in {
            "unknown_tool",
            "revoked",
            "not_authorized",
            "schema_denied",
            "budget_denied",
            "parallel_denied",
        }:
            raise RuntimeToolError("tool_disposition_invalid")
        if record.state == "proposed":
            record = self.transition(record, "validating", now=now)
        if record.state not in {"validating", "validated"}:
            if record.state == "denied" and record.resolution_status == resolution_status:
                return record
            raise RuntimeToolError("tool_disposition_invalid")
        payload = canonical_tool_arguments({"error": failure_reason})
        private_ref = self.private_payload_store.put(
            workspace_id=record.workspace_id,
            session_id=record.session_id,
            payload=payload,
        )
        try:
            return self.transition(
                record,
                "denied",
                failure_reason=failure_reason,
                result_private_ref=private_ref,
                result_summary={
                    "root_type": "object",
                    "field_count": 1,
                    "serialized_bytes": len(payload),
                    "is_error": True,
                },
                resolution_status=resolution_status,
                now=now,
            )
        except Exception:
            self.private_payload_store.delete(
                workspace_id=record.workspace_id,
                session_id=record.session_id,
                private_ref=private_ref,
            )
            raise

    def transition(
        self,
        record: ToolInvocationRecord,
        state: ToolInvocationState,
        *,
        failure_reason: str | None = None,
        result_private_ref: str | None = None,
        result_summary: dict[str, object] | None = None,
        result_classification: CanonicalSourceClassification | None = None,
        resolution_status: ToolResolutionStatus | None = None,
        deterministic_error_result: bool = False,
        execution_lease_id: str | None = None,
        execution_lease_expires_at: datetime | None = None,
        require_active_execution_lease_id: str | None = None,
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        if state not in _TRANSITIONS[record.state]:
            raise RuntimeToolError("tool_state_transition_invalid", f"{record.state}->{state}")
        if deterministic_error_result and (
            state not in {"failed", "execution_unknown"}
            or not failure_reason
            or result_private_ref is not None
        ):
            raise RuntimeToolError("tool_result_invalid")
        if state == "executing" and not (
            (execution_lease_id is None and execution_lease_expires_at is None)
            or (
                isinstance(execution_lease_id, str)
                and bool(execution_lease_id.strip())
                and isinstance(execution_lease_expires_at, datetime)
                and execution_lease_expires_at.tzinfo is not None
            )
        ):
            raise RuntimeToolError("tool_execution_lease_invalid")
        if state != "executing" and (
            execution_lease_id is not None
            or execution_lease_expires_at is not None
        ):
            raise RuntimeToolError("tool_execution_lease_invalid")
        if require_active_execution_lease_id is not None:
            if (
                not isinstance(require_active_execution_lease_id, str)
                or not require_active_execution_lease_id.strip()
                or state != "succeeded"
                or record.state != "executing"
                or record.execution_lease_id
                != require_active_execution_lease_id
                or not isinstance(record.execution_lease_expires_at, datetime)
                or record.execution_lease_expires_at.tzinfo is None
            ):
                raise RuntimeToolError("tool_execution_lease_invalid")
        timestamp = now or datetime.now(tz=UTC)
        effective_resolution = resolution_status or _resolution_for_state(
            state,
            record.resolution_status,
        )
        disposition_id = record.disposition_id
        if disposition_id is None and state in {
            "authorized",
            "denied",
            "cancelled",
            "expired",
            "execution_unknown",
        }:
            disposition_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"maverick:tool-disposition:{record.invocation_id}:"
                    f"{effective_resolution}",
                )
            )
        result_id = record.result_id
        if result_id is None and (
            result_private_ref is not None or deterministic_error_result
        ):
            result_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"maverick:tool-result:{record.invocation_id}",
                )
            )
        next_execution_lease_id = record.execution_lease_id
        next_execution_lease_expires_at = record.execution_lease_expires_at
        if state == "executing":
            next_execution_lease_id = execution_lease_id
            next_execution_lease_expires_at = execution_lease_expires_at
        elif state == "authorized" and record.state == "executing":
            next_execution_lease_id = None
            next_execution_lease_expires_at = None
        updated = replace(
            record,
            state=state,
            failure_reason=failure_reason,
            result_private_ref=result_private_ref,
            result_summary=result_summary,
            result_data_class=(
                result_classification.data_class
                if result_classification is not None
                else record.result_data_class
            ),
            result_trust_level=(
                result_classification.trust_level
                if result_classification is not None
                else record.result_trust_level
            ),
            result_provenance=(
                result_classification.provenance
                if result_classification is not None
                else record.result_provenance
            ),
            result_source_ref=(
                result_classification.source_ref
                if result_classification is not None
                else record.result_source_ref
            ),
            result_source_revision=(
                result_classification.source_revision
                if result_classification is not None
                else record.result_source_revision
            ),
            result_source_digest=(
                result_classification.source_digest
                if result_classification is not None
                else record.result_source_digest
            ),
            result_resource_identity=(
                result_classification.resource_identity
                if result_classification is not None
                else record.result_resource_identity
            ),
            result_classification_revision=(
                result_classification.classification_revision
                if result_classification is not None
                else record.result_classification_revision
            ),
            resolution_status=effective_resolution,
            disposition_id=disposition_id,
            effect_boundary_at=(
                timestamp if state == "executing" else record.effect_boundary_at
            ),
            result_persisted_at=(
                timestamp
                if result_private_ref is not None or deterministic_error_result
                else record.result_persisted_at
            ),
            result_id=result_id,
            execution_lease_id=next_execution_lease_id,
            execution_lease_expires_at=next_execution_lease_expires_at,
            revision=record.revision + 1,
            updated_at=timestamp,
        )
        try:
            if require_active_execution_lease_id is not None:
                return self.store.update_tool_invocation_if_execution_lease_active(
                    updated,
                    expected_revision=record.revision,
                    execution_lease_id=require_active_execution_lease_id,
                )
            return self.store.update_tool_invocation(updated, expected_revision=record.revision)
        except RuntimeToolExecutionLeaseExpiredError as error:
            raise RuntimeToolError(
                "agent_finalization_time_reserve_reached"
            ) from error
        except Exception as error:
            raise RuntimeToolRevisionError("tool_invocation_revision_conflict") from error

    def attach_terminal_result(
        self,
        record: ToolInvocationRecord,
        *,
        failure_reason: str | None = None,
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        """Idempotently materialize a reconstructible error result after a crash."""
        if record.result_private_ref is not None:
            return record
        if record.state not in {
            "denied",
            "failed",
            "cancelled",
            "expired",
            "execution_unknown",
        }:
            raise RuntimeToolError("tool_result_unavailable")
        reason = failure_reason or record.failure_reason or f"tool_{record.state}"
        payload = canonical_tool_arguments({"error": reason})
        private_ref = self.private_payload_store.put(
            workspace_id=record.workspace_id,
            session_id=record.session_id,
            payload=payload,
        )
        try:
            return self._replace(
                record,
                result_private_ref=private_ref,
                result_summary={
                    "root_type": "object",
                    "field_count": 1,
                    "serialized_bytes": len(payload),
                    "is_error": True,
                },
                result_persisted_at=now or datetime.now(tz=UTC),
                result_id=(
                    record.result_id
                    or str(
                        uuid5(
                            NAMESPACE_URL,
                            f"maverick:tool-result:{record.invocation_id}",
                        )
                    )
                ),
                now=now,
            )
        except Exception:
            self.private_payload_store.delete(
                workspace_id=record.workspace_id,
                session_id=record.session_id,
                private_ref=private_ref,
            )
            raise

    def confirm(
        self,
        *,
        invocation_id: str,
        decision: str,
        arguments_digest: str,
        expected_invocation_revision: int,
        confirming_actor_id: str,
        policy_revision: str,
        ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS,
        now: datetime | None = None,
    ) -> tuple[ToolInvocationRecord, ToolConfirmationGrant]:
        return confirm_tool_invocation(
            self,
            invocation_id=invocation_id,
            decision=decision,
            arguments_digest=arguments_digest,
            expected_invocation_revision=expected_invocation_revision,
            confirming_actor_id=confirming_actor_id,
            policy_revision=policy_revision,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def _replace(
        self,
        record: ToolInvocationRecord,
        *,
        now: datetime | None = None,
        **updates: object,
    ) -> ToolInvocationRecord:
        updated = replace(
            record,
            **updates,
            revision=record.revision + 1,
            updated_at=now or datetime.now(tz=UTC),
        )
        try:
            return self.store.update_tool_invocation(
                updated,
                expected_revision=record.revision,
            )
        except Exception as error:
            raise RuntimeToolRevisionError("tool_invocation_revision_conflict") from error

    def _persist_arguments(
        self,
        record: ToolInvocationRecord,
        canonical: bytes,
    ) -> None:
        """Complete the deterministic private-payload half after ledger insert."""
        persisted_ref = self.private_payload_store.put(
            workspace_id=record.workspace_id,
            session_id=record.session_id,
            payload=canonical,
            private_ref=record.arguments_private_ref,
        )
        if persisted_ref != record.arguments_private_ref:
            raise RuntimeToolError("tool_private_payload_identity_conflict")

    def authorize(
        self,
        *,
        invocation_id: str,
        grant_id: str,
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        return authorize_tool_invocation(
            self,
            invocation_id=invocation_id,
            grant_id=grant_id,
            now=now,
        )

    def bind_confirmation_grant(
        self,
        record: ToolInvocationRecord,
        *,
        grant_id: str,
        now: datetime,
    ) -> ToolInvocationRecord:
        """CAS-bind the sole authoritative grant while remaining paused."""
        if record.state != "awaiting_confirmation" or record.confirmation_grant_id is not None:
            raise RuntimeToolError("tool_confirmation_already_decided")
        updated = replace(
            record,
            confirmation_grant_id=grant_id,
            revision=record.revision + 1,
            updated_at=now,
        )
        try:
            return self.store.update_tool_invocation(updated, expected_revision=record.revision)
        except Exception as error:
            raise RuntimeToolRevisionError("tool_invocation_revision_conflict") from error

    def recover_executing(
        self, record: ToolInvocationRecord, *, safe_to_retry: bool, now: datetime | None = None
    ) -> ToolInvocationRecord:
        if record.state != "executing":
            return record
        if record.effect_class == "read" and safe_to_retry:
            return self.transition(record, "authorized", now=now)
        unknown = self.transition(
            record,
            "execution_unknown",
            failure_reason="tool_execution_outcome_unknown",
            now=now,
        )
        return self.attach_terminal_result(unknown, now=now)

    def cancel_before_effect(
        self,
        record: ToolInvocationRecord,
        *,
        reason_code: str = "tool_recovery_cancelled_before_effect",
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        """Materialize a denial result when recovery proves no effect began."""
        if record.effect_boundary_at is not None or record.state == "executing":
            raise RuntimeToolError("tool_execution_outcome_unknown")
        if record.state in {"succeeded", "failed", "denied", "cancelled", "expired"}:
            return self.attach_terminal_result(record, now=now)
        if record.state == "execution_unknown":
            return self.attach_terminal_result(record, now=now)
        cancelled = self.transition(
            record,
            "cancelled",
            failure_reason=reason_code,
            now=now,
        )
        return self.attach_terminal_result(cancelled, now=now)

    def load_arguments(self, record: ToolInvocationRecord) -> dict[str, object]:
        """Read private arguments only after verifying their confirmation digest."""
        payload = self.private_payload_store.read(
            workspace_id=record.workspace_id,
            session_id=record.session_id,
            private_ref=record.arguments_private_ref,
        )
        digest = tool_arguments_digest(digest_key=self._digest_key, canonical_arguments=payload)
        if not hmac.compare_digest(digest, record.arguments_digest):
            raise RuntimeToolError("tool_private_payload_integrity_failed")
        return decode_tool_arguments(payload)

    def load_result(self, record: ToolInvocationRecord) -> dict[str, object]:
        """Resolve one persisted result or denial from Core private storage."""
        if not record.result_private_ref:
            raise RuntimeToolError("tool_result_unavailable")
        payload = self.private_payload_store.read(
            workspace_id=record.workspace_id,
            session_id=record.session_id,
            private_ref=record.result_private_ref,
        )
        return decode_tool_arguments(payload)

    def delete_session_private_payloads(self, *, workspace_id: str, session_id: str) -> int:
        """Delete opaque argument/result payloads before ledger retention cleanup."""
        deleted = 0
        for record in self.store.list_tool_invocations(session_id=session_id):
            for private_ref in (record.arguments_private_ref, record.result_private_ref):
                if private_ref and self.private_payload_store.delete(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    private_ref=private_ref,
                ):
                    deleted += 1
        return deleted

    @staticmethod
    def _require_exact_replay(
        record: ToolInvocationRecord,
        workspace_id: str,
        provider_safe_name: str,
        tool_handle: str | None,
        digest: str,
    ) -> None:
        if (
            record.workspace_id != workspace_id
            or record.provider_safe_name != provider_safe_name
            or (
                tool_handle is not None
                and record.resolved_tool_handle != tool_handle
            )
            or not hmac.compare_digest(record.arguments_digest, digest)
        ):
            raise RuntimeToolError("tool_provider_call_replay_mismatch")


def _resolution_for_state(
    state: ToolInvocationState,
    current: ToolResolutionStatus,
) -> ToolResolutionStatus:
    return {
        "awaiting_confirmation": "awaiting_confirmation",
        "authorized": "authorized",
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "execution_unknown": "execution_unknown",
    }.get(state, current)  # type: ignore[return-value]


def _tool_arguments_private_ref(invocation_id: str) -> str:
    token = hashlib.sha256(
        b"maverick.tool-arguments-ref.v1\x00" + invocation_id.encode("utf-8")
    ).hexdigest()[:32]
    return f"tool-private:v1:{token}"
