"""Authenticated runtime tool confirmation and resume contract."""

from __future__ import annotations

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from core.api.http import StartResponse, json_response
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_runtime_session_operation
from core.runtime.errors import (
    RuntimeProviderStateError,
    RuntimeSessionNotFoundError,
    RuntimeTransitionError,
    RuntimeTurnNotFoundError,
)
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.service import record_runtime_event, transition_runtime_turn
from core.runtime.tool_errors import RuntimeToolError, RuntimeToolRevisionError
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    feature_enabled,
)


def handle_runtime_tool_confirmation(
    state: PlatformState,
    context: RequestSession,
    *,
    turn_id: str,
    invocation_id: str,
    method: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    """Read or decide one exact invocation without exposing grant authority."""
    if not feature_enabled(MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION):
        return json_response(
            start_response,
            {"error": "agentic_tool_confirmation_disabled"},
            status="409 Conflict",
        )
    authorized = _authorized_invocation(
        state,
        context,
        turn_id=turn_id,
        invocation_id=invocation_id,
        start_response=start_response,
    )
    if isinstance(authorized, list):
        return authorized
    turn, invocation = authorized
    ledger = state.runtime_tool_ledger
    if ledger is None:
        return json_response(
            start_response,
            {"error": "runtime_tool_orchestration_unavailable"},
            status="409 Conflict",
        )
    if method == "GET":
        return json_response(
            start_response,
            _confirmation_payload(
                ledger,
                turn,
                invocation,
                confirmation_deadline_at=_confirmation_deadline(state, turn),
            ),
        )
    if method != "POST":
        return json_response(
            start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed"
        )
    decision = body.get("decision")
    arguments_digest = body.get("arguments_digest")
    expected_revision = body.get("expected_invocation_revision")
    if (
        decision not in {"approve", "deny"}
        or not isinstance(arguments_digest, str)
        or not arguments_digest
        or not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
    ):
        return json_response(
            start_response,
            {"error": "tool_confirmation_request_invalid"},
            status="400 Bad Request",
        )
    try:
        invocation, grant = ledger.confirm(
            invocation_id=invocation_id,
            decision=decision,
            arguments_digest=arguments_digest,
            expected_invocation_revision=expected_revision,
            confirming_actor_id=context.user.user_id,
            policy_revision=invocation.policy_revision,
        )
        event = record_runtime_event(
            state.runtime_store,
            event_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"maverick:tool-confirmation:{grant.grant_id}:{decision}",
                )
            ),
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type=f"runtime.tool_call.confirmation_{'approved' if decision == 'approve' else 'denied'}",
            payload={
                "invocation_id": invocation.invocation_id,
                "tool_handle": invocation.resolved_tool_handle,
                "effect_class": invocation.effect_class,
                "arguments_digest": invocation.arguments_digest,
                "invocation_revision": invocation.revision,
                "confirmation_state": grant.state,
            },
            event_bus=state.runtime_event_bus,
        )
        if turn.status == "waiting_for_tool_confirmation":
            turn = transition_runtime_turn(
                state.runtime_store,
                turn_id=turn.turn_id,
                target_status="active",
            )
    except RuntimeToolRevisionError as error:
        return json_response(start_response, {"error": error.reason_code}, status="409 Conflict")
    except RuntimeToolError as error:
        return json_response(start_response, {"error": error.reason_code}, status="409 Conflict")
    except (RuntimeProviderStateError, RuntimeTransitionError):
        return json_response(
            start_response,
            {"error": "tool_confirmation_state_conflict"},
            status="409 Conflict",
        )
    return json_response(
        start_response,
        {
            **_confirmation_payload(
                ledger,
                turn,
                invocation,
                confirmation_deadline_at=_confirmation_deadline(state, turn),
            ),
            "event": {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "created_at": event.created_at,
            },
        },
    )


def _authorized_invocation(
    state: PlatformState,
    context: RequestSession,
    *,
    turn_id: str,
    invocation_id: str,
    start_response: StartResponse,
):
    try:
        turn = state.runtime_store.get_turn(turn_id)
        session = state.runtime_store.get_session(turn.session_id)
        invocation = state.runtime_store.get_tool_invocation(invocation_id)
    except (RuntimeTurnNotFoundError, RuntimeSessionNotFoundError, RuntimeProviderStateError, ValueError):
        return json_response(
            start_response, {"error": "tool_invocation_not_found"}, status="404 Not Found"
        )
    if (
        turn.workspace_id != context.workspace_id
        or invocation.workspace_id != context.workspace_id
        or invocation.turn_id != turn.turn_id
        or invocation.session_id != turn.session_id
        or not runtime_session_allows_user_thread(session)
    ):
        return json_response(
            start_response, {"error": "tool_invocation_not_found"}, status="404 Not Found"
        )
    try:
        require_runtime_session_operation(
            workspace_store=state.workspace_store,
            user=context.user,
            session=session,
            operation="tool_confirm",
        )
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    return turn, invocation


def _confirmation_payload(
    ledger,
    turn,
    invocation,
    *,
    confirmation_deadline_at=None,
) -> dict[str, object]:
    grants = ledger.store.list_tool_confirmation_grants(invocation_id=invocation.invocation_id)
    grant = max(grants, key=lambda item: item.created_at, default=None)
    return {
        "turn_id": turn.turn_id,
        "turn_status": turn.status,
        "confirmation_deadline_at": confirmation_deadline_at,
        "invocation": {
            "invocation_id": invocation.invocation_id,
            "tool_handle": invocation.resolved_tool_handle,
            "effect_class": invocation.effect_class,
            "arguments_summary": invocation.arguments_summary,
            "arguments_digest": invocation.arguments_digest,
            "state": invocation.state,
            "revision": invocation.revision,
            "policy_revision": invocation.policy_revision,
        },
        "confirmation": (
            None
            if grant is None
            else {
                "state": grant.state,
                "expires_at": grant.expires_at,
                "revision": grant.revision,
            }
        ),
    }


def _confirmation_deadline(state: PlatformState, turn):
    deadlines = []
    try:
        runtime_state = state.runtime_store.get_state(turn.session_id)
    except Exception:
        runtime_state = None
    if runtime_state is not None and runtime_state.watchdog_deadline_at is not None:
        deadlines.append(runtime_state.watchdog_deadline_at)
    try:
        session = state.runtime_store.get_session(turn.session_id)
    except Exception:
        session = None
    binding = None if session is None else session.execution_binding
    if binding is not None:
        max_wall_time_seconds = min(
            binding.profile_policy_ceiling_snapshot.max_wall_time_seconds,
            binding.workspace_policy_ceiling_snapshot.max_wall_time_seconds,
        )
        deadlines.append(
            (turn.started_at or turn.created_at)
            + timedelta(seconds=max_wall_time_seconds)
        )
    return min(deadlines) if deadlines else None
