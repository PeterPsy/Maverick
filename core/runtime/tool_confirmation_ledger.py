"""One-shot confirmation transitions for the runtime tool ledger."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hmac
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from core.runtime.store import RuntimeStore
from core.runtime.tool_errors import RuntimeToolError, RuntimeToolRevisionError
from core.runtime.tool_models import (
    ToolConfirmationGrant,
    ToolConfirmationState,
    ToolInvocationRecord,
    ToolInvocationState,
)


DEFAULT_CONFIRMATION_TTL_SECONDS = 300


class ToolConfirmationLedgerContext(Protocol):
    store: RuntimeStore

    def transition(
        self,
        record: ToolInvocationRecord,
        state: ToolInvocationState,
        *,
        failure_reason: str | None = None,
        now: datetime | None = None,
    ) -> ToolInvocationRecord: ...

    def bind_confirmation_grant(
        self,
        record: ToolInvocationRecord,
        *,
        grant_id: str,
        now: datetime,
    ) -> ToolInvocationRecord: ...


def confirm_tool_invocation(
    ledger: ToolConfirmationLedgerContext,
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
    """Persist an actor-bound idempotent approval or denial."""
    timestamp = now or datetime.now(tz=UTC)
    record = ledger.store.get_tool_invocation(invocation_id)
    existing = _matching_grant(ledger.store, record, confirming_actor_id, arguments_digest, decision)
    if existing is not None:
        if existing.state == "active" and existing.expires_at <= timestamp:
            _update_grant(ledger.store, existing, "expired", timestamp)
            if record.state == "awaiting_confirmation":
                ledger.transition(
                    record,
                    "expired",
                    failure_reason="tool_confirmation_expired",
                    now=timestamp,
                )
            raise RuntimeToolError("tool_confirmation_expired")
        if existing.state == "expired":
            raise RuntimeToolError("tool_confirmation_expired")
        if record.confirmation_grant_id == existing.grant_id:
            return record, existing
        if record.confirmation_grant_id is not None:
            raise RuntimeToolError("tool_confirmation_already_decided")
        record = ledger.bind_confirmation_grant(
            record, grant_id=existing.grant_id, now=timestamp
        )
        if decision == "deny":
            record = ledger.transition(
                record, "denied", failure_reason="tool_confirmation_denied", now=timestamp
            )
        return record, existing
    if record.revision != expected_invocation_revision:
        raise RuntimeToolRevisionError("tool_invocation_revision_conflict")
    if record.state != "awaiting_confirmation":
        raise RuntimeToolError("tool_confirmation_not_pending")
    if record.confirmation_grant_id is not None:
        raise RuntimeToolError("tool_confirmation_already_decided")
    if not hmac.compare_digest(record.arguments_digest, arguments_digest):
        raise RuntimeToolError("tool_confirmation_digest_mismatch")
    if decision not in {"approve", "deny"}:
        raise RuntimeToolError("tool_confirmation_decision_invalid")
    if ttl_seconds <= 0 or ttl_seconds > 3600:
        raise RuntimeToolError("tool_confirmation_ttl_invalid")
    state: ToolConfirmationState = "active" if decision == "approve" else "denied"
    grant = ToolConfirmationGrant(
        grant_id=str(uuid5(NAMESPACE_URL, f"maverick:grant:{invocation_id}:{confirming_actor_id}:{decision}")),
        workspace_id=record.workspace_id,
        session_id=record.session_id,
        turn_id=record.turn_id,
        invocation_id=record.invocation_id,
        tool_handle=record.resolved_tool_handle,
        arguments_digest=record.arguments_digest,
        confirming_actor_id=confirming_actor_id,
        policy_revision=policy_revision,
        expires_at=timestamp + timedelta(seconds=ttl_seconds),
        state=state,
        revision=0,
        created_at=timestamp,
        updated_at=timestamp,
    )
    try:
        grant = ledger.store.initialize_tool_confirmation_grant(grant)
    except Exception:
        raced = _matching_grant(
            ledger.store, record, confirming_actor_id, arguments_digest, decision
        )
        if raced is None:
            raise
        grant = raced
    try:
        record = ledger.bind_confirmation_grant(
            record, grant_id=grant.grant_id, now=timestamp
        )
    except RuntimeToolRevisionError:
        current = ledger.store.get_tool_invocation(record.invocation_id)
        if current.confirmation_grant_id != grant.grant_id:
            try:
                _update_grant(ledger.store, grant, "revoked", timestamp)
            except RuntimeToolRevisionError:
                pass
            raise RuntimeToolError("tool_confirmation_already_decided")
        record = current
    if decision == "deny":
        record = ledger.transition(
            record, "denied", failure_reason="tool_confirmation_denied", now=timestamp
        )
    return record, grant


def authorize_tool_invocation(
    ledger: ToolConfirmationLedgerContext,
    *,
    invocation_id: str,
    grant_id: str,
    now: datetime | None = None,
) -> ToolInvocationRecord:
    """Consume a grant once and durably authorize only its bound invocation."""
    timestamp = now or datetime.now(tz=UTC)
    record = ledger.store.get_tool_invocation(invocation_id)
    grant = ledger.store.get_tool_confirmation_grant(grant_id)
    _require_grant_binding(record, grant)
    if record.state in {
        "authorized",
        "executing",
        "succeeded",
        "failed",
        "cancelled",
        "execution_unknown",
    } and grant.state == "consumed":
        return record
    if record.state != "awaiting_confirmation" or grant.state not in {"active", "consumed"}:
        raise RuntimeToolError("tool_confirmation_invalid")
    if grant.expires_at <= timestamp:
        if grant.state == "active":
            _update_grant(ledger.store, grant, "expired", timestamp)
        return ledger.transition(
            record, "expired", failure_reason="tool_confirmation_expired", now=timestamp
        )
    if grant.state == "active":
        _update_grant(ledger.store, grant, "consumed", timestamp)
    return ledger.transition(record, "authorized", now=timestamp)


def _update_grant(
    store: RuntimeStore,
    grant: ToolConfirmationGrant,
    state: ToolConfirmationState,
    now: datetime,
) -> ToolConfirmationGrant:
    updated = replace(grant, state=state, revision=grant.revision + 1, updated_at=now)
    try:
        return store.update_tool_confirmation_grant(updated, expected_revision=grant.revision)
    except Exception as error:
        raise RuntimeToolRevisionError("tool_confirmation_revision_conflict") from error


def _matching_grant(
    store: RuntimeStore,
    record: ToolInvocationRecord,
    actor_id: str,
    digest: str,
    decision: str,
) -> ToolConfirmationGrant | None:
    wanted = {"approve": {"active", "consumed", "expired"}, "deny": {"denied"}}.get(
        decision, set()
    )
    return next(
        (
            item
            for item in store.list_tool_confirmation_grants(invocation_id=record.invocation_id)
            if item.confirming_actor_id == actor_id
            and hmac.compare_digest(item.arguments_digest, digest)
            and item.state in wanted
        ),
        None,
    )


def _require_grant_binding(
    record: ToolInvocationRecord, grant: ToolConfirmationGrant
) -> None:
    if (
        record.confirmation_grant_id != grant.grant_id
        or grant.invocation_id != record.invocation_id
        or grant.session_id != record.session_id
        or grant.turn_id != record.turn_id
        or grant.workspace_id != record.workspace_id
        or grant.tool_handle != record.resolved_tool_handle
        or not hmac.compare_digest(grant.arguments_digest, record.arguments_digest)
    ):
        raise RuntimeToolError("tool_confirmation_binding_mismatch")
