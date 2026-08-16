"""CAS-backed tool invocation, confirmation and crash-recovery state machine."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import hmac
from uuid import NAMESPACE_URL, uuid5

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
)
from core.runtime.tool_private_payloads import (
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
    "validated": frozenset({"awaiting_confirmation", "authorized", "cancelled"}),
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
        tool_handle: str,
        arguments: dict[str, object],
        effect_class: ToolEffectClass,
        policy_revision: str,
        authority_digest: str,
        now: datetime | None = None,
    ) -> tuple[ToolInvocationRecord, bool]:
        """Insert before validation; exact provider retries deduplicate."""
        timestamp = now or datetime.now(tz=UTC)
        canonical = canonical_tool_arguments(arguments)
        digest = tool_arguments_digest(digest_key=self._digest_key, canonical_arguments=canonical)
        existing = self.store.find_tool_invocation_by_provider_call(
            session_id=session_id,
            turn_id=turn_id,
            provider_tool_call_id=provider_tool_call_id,
        )
        if existing is not None:
            self._require_exact_replay(existing, workspace_id, tool_handle, digest)
            return existing, False
        private_ref = self.private_payload_store.put(
            workspace_id=workspace_id,
            session_id=session_id,
            payload=canonical,
        )
        invocation_id = str(
            uuid5(NAMESPACE_URL, f"maverick:tool:{workspace_id}:{session_id}:{turn_id}:{provider_tool_call_id}")
        )
        idempotency_key = hmac.new(
            self._digest_key,
            _IDEMPOTENCY_DOMAIN + invocation_id.encode("utf-8") + digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        record = ToolInvocationRecord(
            invocation_id=invocation_id,
            workspace_id=workspace_id,
            session_id=session_id,
            turn_id=turn_id,
            provider_tool_call_id=provider_tool_call_id,
            resolved_tool_handle=tool_handle,
            arguments_private_ref=private_ref,
            arguments_summary=tool_arguments_summary(arguments, serialized_bytes=len(canonical)),
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
        )
        try:
            return self.store.initialize_tool_invocation(record), True
        except Exception:
            self.private_payload_store.delete(
                workspace_id=workspace_id, session_id=session_id, private_ref=private_ref
            )
            raced = self.store.find_tool_invocation_by_provider_call(
                session_id=session_id,
                turn_id=turn_id,
                provider_tool_call_id=provider_tool_call_id,
            )
            if raced is None:
                raise
            self._require_exact_replay(raced, workspace_id, tool_handle, digest)
            return raced, False

    def transition(
        self,
        record: ToolInvocationRecord,
        state: ToolInvocationState,
        *,
        failure_reason: str | None = None,
        result_private_ref: str | None = None,
        result_summary: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> ToolInvocationRecord:
        if state not in _TRANSITIONS[record.state]:
            raise RuntimeToolError("tool_state_transition_invalid", f"{record.state}->{state}")
        updated = replace(
            record,
            state=state,
            failure_reason=failure_reason,
            result_private_ref=result_private_ref,
            result_summary=result_summary,
            revision=record.revision + 1,
            updated_at=now or datetime.now(tz=UTC),
        )
        try:
            return self.store.update_tool_invocation(updated, expected_revision=record.revision)
        except Exception as error:
            raise RuntimeToolRevisionError("tool_invocation_revision_conflict") from error

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
        return self.transition(
            record,
            "execution_unknown",
            failure_reason="tool_execution_outcome_unknown",
            now=now,
        )

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
        record: ToolInvocationRecord, workspace_id: str, tool_handle: str, digest: str
    ) -> None:
        if (
            record.workspace_id != workspace_id
            or record.resolved_tool_handle != tool_handle
            or not hmac.compare_digest(record.arguments_digest, digest)
        ):
            raise RuntimeToolError("tool_provider_call_replay_mismatch")
