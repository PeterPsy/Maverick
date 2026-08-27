"""Persisted provider-step gates shared by runtime admission boundaries."""

from __future__ import annotations

from core.runtime.store import RuntimeStore


def provider_step_admission_reason(
    store: RuntimeStore,
    *,
    session_id: str,
    turn_id: str | None = None,
    allow_same_turn_pairing: bool = False,
) -> str | None:
    """Return a stable reason when persisted WAL state cannot admit ordinary work."""
    try:
        records = store.list_provider_step_journals(session_id=session_id)
    except Exception:
        return "provider_state_ambiguous"
    if any(item.commit_status == "recovery_required" for item in records):
        return "runtime_session_recovery_required"
    if any(item.commit_status == "pending" for item in records):
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
        and allow_same_turn_pairing
        and turn_id == undelivered_finals[0].turn_id
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
        return None
    source = ready[0]
    try:
        owner = store.get_turn(source.turn_id)
    except Exception:
        return "provider_pairing_ambiguous"
    if (
        owner.session_id != session_id
        or owner.workspace_id != source.workspace_id
        or owner.status not in {
            "queued",
            "active",
            "waiting_for_tool_confirmation",
        }
    ):
        return "provider_pairing_ambiguous"
    if not allow_same_turn_pairing or turn_id != source.turn_id:
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


__all__ = ["provider_step_admission_reason"]
