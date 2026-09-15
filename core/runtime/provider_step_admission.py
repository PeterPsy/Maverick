"""Persisted provider-step gates shared by runtime admission boundaries."""

from __future__ import annotations

from core.runtime.store import RuntimeStore


_LIVE_PAIRING_CONSUMER_STATUSES = frozenset(
    {"queued", "active", "waiting_for_tool_confirmation"}
)


def provider_pairing_lineage_allows(
    store: RuntimeStore,
    *,
    session_id: str,
    consumer_turn_id: str,
    source_turn_id: str,
) -> bool:
    """Validate one persisted same-session pairing ownership transfer."""
    try:
        session = store.get_session(session_id)
        consumer = store.get_turn(consumer_turn_id)
        source = store.get_turn(source_turn_id)
    except Exception:
        return False
    if (
        session is None
        or consumer is None
        or source is None
        or consumer.session_id != session_id
        or source.session_id != session_id
        or consumer.workspace_id != session.workspace_id
        or source.workspace_id != session.workspace_id
    ):
        return False
    if consumer_turn_id == source_turn_id:
        return getattr(consumer, "provider_pairing_source_turn_id", None) in {
            None,
            consumer_turn_id,
        }
    return (
        getattr(consumer, "provider_pairing_source_turn_id", None)
        == source_turn_id
        and source.status == "failed"
    )


def live_provider_pairing_source_turn_id(
    store: RuntimeStore,
    *,
    session_id: str,
    consumer_turn_id: str,
) -> str | None:
    """Resolve the provider pairing owner authorized for one live turn."""
    try:
        consumer = store.get_turn(consumer_turn_id)
    except Exception:
        return None
    if consumer is None or consumer.status not in _LIVE_PAIRING_CONSUMER_STATUSES:
        return None
    source_turn_id = (
        getattr(consumer, "provider_pairing_source_turn_id", None)
        or consumer.turn_id
    )
    if not provider_pairing_lineage_allows(
        store,
        session_id=session_id,
        consumer_turn_id=consumer_turn_id,
        source_turn_id=source_turn_id,
    ):
        return None
    return source_turn_id


def _pairing_transfer_source_is_valid(
    store: RuntimeStore,
    *,
    session_id: str,
    source_turn_id: str,
) -> bool:
    try:
        session = store.get_session(session_id)
        source = store.get_turn(source_turn_id)
    except Exception:
        return False
    return (
        session is not None
        and source is not None
        and source.session_id == session_id
        and source.workspace_id == session.workspace_id
        and source.status == "failed"
    )


def provider_step_admission_reason(
    store: RuntimeStore,
    *,
    session_id: str,
    turn_id: str | None = None,
    allow_same_turn_pairing: bool = False,
    pairing_source_turn_id: str | None = None,
) -> str | None:
    """Return a stable reason when persisted WAL state cannot admit ordinary work."""
    authorized_pairing_turn_id: str | None = None
    if pairing_source_turn_id is not None:
        if not _pairing_transfer_source_is_valid(
            store,
            session_id=session_id,
            source_turn_id=pairing_source_turn_id,
        ):
            return "provider_pairing_ambiguous"
        authorized_pairing_turn_id = pairing_source_turn_id
    elif allow_same_turn_pairing:
        authorized_pairing_turn_id = live_provider_pairing_source_turn_id(
            store,
            session_id=session_id,
            consumer_turn_id=str(turn_id or ""),
        )
        if authorized_pairing_turn_id is None:
            return "provider_pairing_ambiguous"
    try:
        records = store.list_provider_step_journals(session_id=session_id)
    except Exception:
        return "provider_state_ambiguous"
    if any(item.commit_status == "recovery_required" for item in records):
        return "runtime_session_recovery_required"
    pending = [item for item in records if item.commit_status == "pending"]
    if pending and not (
        len(pending) == 1
        and authorized_pairing_turn_id == pending[0].turn_id
    ):
        return "provider_state_ambiguous"
    committed_finals = [
        item
        for item in records
        if item.commit_status == "committed" and item.final_output_validated
    ]
    if any(
        item.final_output_status not in {"ready", "delivered"}
        or item.final_completion_status not in {"ready", "delivered"}
        or not item.final_output_id
        or not item.final_output_private_ref
        or not item.final_output_sha256
        or item.final_output_size_bytes is None
        for item in committed_finals
    ):
        return "provider_state_ambiguous"
    undelivered_finals = [
        item
        for item in committed_finals
        if item.final_output_status != "delivered"
        or item.final_completion_status != "delivered"
    ]
    if undelivered_finals and not (
        len(undelivered_finals) == 1
        and authorized_pairing_turn_id == undelivered_finals[0].turn_id
    ):
        return "provider_state_ambiguous"
    ready = [
        item
        for item in records
        if item.commit_status == "committed" and item.pairing_status == "ready"
    ]
    if len(ready) > 1:
        return "provider_pairing_ambiguous"
    if not ready:
        return (
            "provider_pairing_ambiguous"
            if pairing_source_turn_id is not None
            else None
        )
    source = ready[0]
    if authorized_pairing_turn_id != source.turn_id:
        return "provider_pairing_ambiguous"
    try:
        state = store.get_provider_state(session_id)
    except Exception:
        return "provider_state_ambiguous"
    envelope = state.provider_private_envelope
    staged = source.staged_provider_state
    if (
        envelope is None
        or staged is None
        or envelope.opaque_state_ref != staged.opaque_state_ref
        or envelope.provider_request_id != source.request_id
        or envelope.turn_generation != source.turn_id
    ):
        return "provider_pairing_ambiguous"
    return None


__all__ = [
    "live_provider_pairing_source_turn_id",
    "provider_pairing_lineage_allows",
    "provider_step_admission_reason",
]
