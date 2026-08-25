"""Provider-neutral admission of chat input into an active runtime turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from core.providers.errors import ProviderError, ProviderLaunchError
from core.providers.service import resolve_runtime_backend_for_session
from core.runtime.client_message_claims import RuntimeClientMessageClaim
from core.runtime.message_admission import runtime_message_admission_handoff
from core.runtime.plain_hosted_text import runtime_session_is_plain_hosted_chat
from core.runtime.provider_input_context import runtime_provider_input_text
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import record_runtime_event
from core.runtime.thread_catalog_events import mark_thread_user_message_queued
from core.skills.service import (
    SkillInvocationError,
    normalize_invoked_skill_ids,
    resolve_invoked_runtime_skills,
)

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


RuntimeMessageSteerStatus = Literal["steered", "fallback", "pending", "delivery_uncertain"]


@dataclass(frozen=True)
class RuntimeMessageSteerAttempt:
    """Core result for one same-turn message-admission attempt."""

    status: RuntimeMessageSteerStatus
    turn: RuntimeTurnRecord | None = None
    events: tuple[RuntimeEventRecord, ...] = ()
    claim: RuntimeClientMessageClaim | None = None
    reason: str | None = None


def attempt_runtime_message_steer(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    materialized_app_references: list[dict[str, object]] | None = None,
    expected_runtime_turn_id: str | None = None,
    invoked_skill_ids: list[str] | None = None,
) -> RuntimeMessageSteerAttempt:
    """Try same-turn input and return a race-safe fallback decision."""
    with runtime_message_admission_handoff(session.session_id):
        return _attempt_runtime_message_steer_locked(
            state,
            session=session,
            input_text=input_text,
            client_message_id=client_message_id,
            attachments=attachments,
            app_references=app_references,
            materialized_app_references=materialized_app_references,
            expected_runtime_turn_id=expected_runtime_turn_id,
            invoked_skill_ids=invoked_skill_ids,
        )


def _attempt_runtime_message_steer_locked(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    input_text: str,
    client_message_id: str | None,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
    materialized_app_references: list[dict[str, object]] | None,
    expected_runtime_turn_id: str | None,
    invoked_skill_ids: list[str] | None,
) -> RuntimeMessageSteerAttempt:
    normalized_client_message_id = str(client_message_id or "").strip()
    if not normalized_client_message_id:
        return RuntimeMessageSteerAttempt(status="fallback", reason="client_message_id_required")

    persisted_attempt = _persisted_message_attempt(
        state,
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        client_message_id=normalized_client_message_id,
    )
    if persisted_attempt is not None:
        return persisted_attempt
    if runtime_session_is_plain_hosted_chat(session):
        return RuntimeMessageSteerAttempt(status="fallback", reason="runtime_mode_does_not_support_same_turn_input")

    active_turn, has_queued_turn = _active_runtime_turn(state, session.session_id)
    if has_queued_turn:
        return RuntimeMessageSteerAttempt(status="fallback", reason="runtime_turn_queue_not_empty")
    if active_turn is None:
        return RuntimeMessageSteerAttempt(status="fallback", reason="runtime_turn_not_active")
    normalized_expected_turn_id = str(expected_runtime_turn_id or "").strip()
    if normalized_expected_turn_id and active_turn.turn_id != normalized_expected_turn_id:
        return RuntimeMessageSteerAttempt(status="fallback", reason="runtime_turn_changed")

    try:
        provider, _selection, runtime_adapter = resolve_runtime_backend_for_session(
            state.provider_store,
            session=session,
        )
    except ProviderError:
        return RuntimeMessageSteerAttempt(status="fallback", reason="provider_unavailable")
    if not provider.capabilities.supports_same_turn_input or not callable(getattr(runtime_adapter, "steer_turn", None)):
        return RuntimeMessageSteerAttempt(status="fallback", reason="provider_does_not_support_same_turn_input")

    expected_provider_turn_id = _provider_turn_id_for_runtime_turn(state, active_turn)
    if not expected_provider_turn_id:
        return RuntimeMessageSteerAttempt(status="fallback", reason="provider_turn_not_accepted")

    try:
        invoked_skills = resolve_invoked_runtime_skills(
            session,
            invoked_skill_ids,
            start_path=getattr(state, "repository_root", None),
        )
        resolved_invoked_skill_ids = [skill.skill_id for skill in invoked_skills]
        normalize_invoked_skill_ids([*active_turn.invoked_skill_ids, *resolved_invoked_skill_ids])
        provider_input = runtime_provider_input_text(
            state,
            session=session,
            input_text=input_text,
            app_references=materialized_app_references,
            attachments=attachments,
        )
    except SkillInvocationError as error:
        return RuntimeMessageSteerAttempt(status="fallback", reason=error.reason_code)
    except Exception:
        return RuntimeMessageSteerAttempt(status="fallback", reason="provider_input_build_failed")

    claim_client_message_id = getattr(state.runtime_store, "claim_client_message_id", None)
    if not callable(claim_client_message_id):
        return RuntimeMessageSteerAttempt(status="fallback", reason="message_admission_store_unavailable")
    claim, claimed = claim_client_message_id(
        workspace_id=session.workspace_id,
        client_message_id=normalized_client_message_id,
        session_id=session.session_id,
        turn_id=active_turn.turn_id,
    )
    if not claimed:
        if claim.session_id != session.session_id:
            return RuntimeMessageSteerAttempt(status="pending", claim=claim, reason="client_message_session_conflict")
        return _existing_claim_attempt(state, claim)

    if not _mark_claim_status(state, claim, "delivery_uncertain"):
        _release_claim(state, claim)
        return RuntimeMessageSteerAttempt(status="fallback", reason="message_admission_store_unavailable")

    try:
        if invoked_skills:
            provider_result = runtime_adapter.steer_turn(
                session.session_id,
                input_text=provider_input,
                client_message_id=normalized_client_message_id,
                expected_provider_turn_id=expected_provider_turn_id,
                invoked_skills=invoked_skills,
                skill_activation_mode=session.skill_activation_mode,
            )
        else:
            provider_result = runtime_adapter.steer_turn(
                session.session_id,
                input_text=provider_input,
                client_message_id=normalized_client_message_id,
                expected_provider_turn_id=expected_provider_turn_id,
                skill_activation_mode=session.skill_activation_mode,
            )
    except ProviderLaunchError:
        _release_claim(state, claim)
        return RuntimeMessageSteerAttempt(status="fallback", reason="provider_input_not_dispatched")
    except Exception:
        return RuntimeMessageSteerAttempt(
            status="delivery_uncertain",
            turn=active_turn,
            claim=claim,
            reason="provider_steer_failed_without_acknowledgement",
        )
    if provider_result.status == "delivery_uncertain":
        _mark_claim_status(state, claim, "delivery_uncertain")
        return RuntimeMessageSteerAttempt(
            status="delivery_uncertain",
            turn=active_turn,
            claim=claim,
            reason=provider_result.reason,
        )
    if provider_result.status != "steered":
        _release_claim(state, claim)
        return RuntimeMessageSteerAttempt(status="fallback", reason=provider_result.reason or provider_result.status)

    if resolved_invoked_skill_ids:
        try:
            active_turn = state.runtime_store.merge_turn_invoked_skill_ids(
                turn_id=active_turn.turn_id,
                invoked_skill_ids=resolved_invoked_skill_ids,
            )
        except Exception:
            _mark_claim_status(state, claim, "delivery_uncertain")
            return RuntimeMessageSteerAttempt(
                status="delivery_uncertain",
                turn=active_turn,
                claim=claim,
                reason="steered_skill_receipt_persistence_failed",
            )

    payload: dict[str, object] = {
        "input_text": input_text,
        "client_message_id": normalized_client_message_id,
        "provider_id": provider.provider_id,
        "provider_turn_id": provider_result.provider_turn_id or expected_provider_turn_id,
        "delivery": "steered",
    }
    if attachments:
        payload["attachments"] = attachments
    if app_references:
        payload["app_references"] = app_references
    if resolved_invoked_skill_ids:
        payload["invoked_skill_ids"] = resolved_invoked_skill_ids
    try:
        event = record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            turn_id=active_turn.turn_id,
            plane="turn",
            event_type="runtime.message.steered",
            payload=payload,
            event_bus=state.runtime_event_bus,
        )
    except Exception:
        _mark_claim_status(state, claim, "delivery_uncertain")
        return RuntimeMessageSteerAttempt(
            status="delivery_uncertain",
            turn=active_turn,
            claim=claim,
            reason="steered_event_persistence_failed",
        )
    _mark_claim_status(state, claim, "steered")
    try:
        mark_thread_user_message_queued(
            state,
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            input_text=input_text,
            attachments=attachments,
            app_references=app_references,
            now=event.created_at,
        )
    except Exception:
        pass
    return RuntimeMessageSteerAttempt(
        status="steered",
        turn=active_turn,
        events=(event,),
        claim=claim,
    )


def _active_runtime_turn(state: PlatformState, session_id: str) -> tuple[RuntimeTurnRecord | None, bool]:
    turns = state.runtime_store.list_turns(session_id)
    active_turns = [turn for turn in turns if turn.status == "active"]
    if not active_turns:
        return None, any(turn.status == "queued" for turn in turns)
    return max(active_turns, key=lambda turn: (turn.updated_at, turn.turn_id)), any(
        turn.status == "queued" for turn in turns
    )


def _provider_turn_id_for_runtime_turn(state: PlatformState, turn: RuntimeTurnRecord) -> str | None:
    for event in reversed(state.runtime_store.list_events(turn.session_id)):
        if event.turn_id != turn.turn_id or event.event_type != "runtime.provider.accepted":
            continue
        provider_turn_id = str(event.payload.get("provider_turn_id") or "").strip()
        if provider_turn_id:
            return provider_turn_id
    return None


def _existing_claim_attempt(state: PlatformState, claim: RuntimeClientMessageClaim) -> RuntimeMessageSteerAttempt:
    try:
        turn = state.runtime_store.get_turn(claim.turn_id)
    except Exception:
        turn = None
    if claim.status == "steered":
        events = tuple(
            event
            for event in state.runtime_store.list_events(claim.session_id)
            if event.turn_id == claim.turn_id
            and event.event_type == "runtime.message.steered"
            and event.payload.get("client_message_id") == claim.client_message_id
        )
        return RuntimeMessageSteerAttempt(status="steered", turn=turn, events=events[:1], claim=claim)
    if claim.status == "delivery_uncertain":
        return RuntimeMessageSteerAttempt(
            status="delivery_uncertain",
            turn=turn,
            claim=claim,
            reason="previous_delivery_uncertain",
        )
    return RuntimeMessageSteerAttempt(status="pending", turn=turn, claim=claim)


def _persisted_message_attempt(
    state: PlatformState,
    *,
    workspace_id: str,
    session_id: str,
    client_message_id: str,
) -> RuntimeMessageSteerAttempt | None:
    for event in reversed(state.runtime_store.list_events(session_id)):
        if (
            event.event_type == "runtime.message.steered"
            and event.payload.get("client_message_id") == client_message_id
        ):
            try:
                turn = state.runtime_store.get_turn(event.turn_id or "")
            except Exception:
                turn = None
            return RuntimeMessageSteerAttempt(status="steered", turn=turn, events=(event,))
    get_claim = getattr(state.runtime_store, "get_client_message_claim", None)
    if not callable(get_claim):
        return None
    claim = get_claim(workspace_id=workspace_id, client_message_id=client_message_id)
    if claim is None or claim.session_id != session_id:
        return None
    if claim.status in {"steered", "delivery_uncertain"}:
        return _existing_claim_attempt(state, claim)
    return None


def _mark_claim_status(state: PlatformState, claim: RuntimeClientMessageClaim, status: str) -> bool:
    mark_status = getattr(state.runtime_store, "mark_client_message_claim_status", None)
    if not callable(mark_status):
        return False
    updated = mark_status(
        workspace_id=claim.workspace_id,
        client_message_id=claim.client_message_id,
        session_id=claim.session_id,
        turn_id=claim.turn_id,
        status=status,
    )
    return updated is not None and updated.status == status


def _release_claim(state: PlatformState, claim: RuntimeClientMessageClaim) -> None:
    release = getattr(state.runtime_store, "release_client_message_claim", None)
    if callable(release):
        release(
            workspace_id=claim.workspace_id,
            client_message_id=claim.client_message_id,
            session_id=claim.session_id,
            turn_id=claim.turn_id,
        )
