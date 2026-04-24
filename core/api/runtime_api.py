"""Generic runtime HTTP API for hosted Maverick v3 apps."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import parse_qs
from uuid import uuid4

from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.runtime_cleanup import cleanup_runtime_session
from core.api.session_api import RequestSession, require_session
from core.providers.service import resolve_provider_for_runtime_session
from core.providers.codex_app_server import interrupt_codex_app_server_turn
from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeTurnNotFoundError
from core.runtime.service import (
    create_runtime_session,
    reconcile_runtime_session_policy,
    record_runtime_event,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.turn_submission import submit_runtime_turn, submit_runtime_turn_async


def _session_payload(session: RuntimeSessionRecord, *, provider_id: str | None = None) -> dict[str, object]:
    payload = asdict(session)
    if provider_id is not None:
        payload["provider_id"] = provider_id
    return payload


def _reconciled_session(state: PlatformState, session: RuntimeSessionRecord, *, start_path) -> RuntimeSessionRecord:
    return reconcile_runtime_session_policy(
        state.runtime_store,
        session,
        governance=state.workspace_store.get_governance(session.workspace_id),
        platform_allows_full_access=session.workspace_id == "default",
        start_path=start_path,
    )


def _turn_payload(turn: RuntimeTurnRecord) -> dict[str, object]:
    return asdict(turn)


def _event_payload(event: RuntimeEventRecord) -> dict[str, object]:
    return asdict(event)


def _list_session_payloads(state: PlatformState, *, workspace_id: str, start_path) -> list[dict[str, object]]:
    sessions = state.runtime_store.list_sessions(workspace_id)
    reconciled = [_reconciled_session(state, session, start_path=start_path) for session in sessions]
    return [_session_payload(session, provider_id=resolve_provider_for_runtime_session(state.provider_store, session=session)[0].provider_id) for session in reconciled]


def _create_session(state: PlatformState, context: RequestSession, body: dict, *, agent_id: str, start_path) -> RuntimeSessionRecord:
    session = create_runtime_session(
        state.runtime_store,
        session_id=str(uuid4()),
        workspace_id=context.workspace_id,
        agent_id=agent_id,
        requested_mode=body.get("requested_mode"),
        system_prompt=str(body.get("system_prompt") or "").strip() or None,
        skill_ids=body.get("skill_ids") if isinstance(body.get("skill_ids"), list) else [],
        source_app_id=str(body.get("source_app_id") or "").strip() or None,
        governance=state.workspace_store.get_governance(context.workspace_id),
        platform_allows_full_access=context.workspace_id == "default",
        start_path=start_path,
        observability_store=state.observability_store,
    )
    return transition_runtime_session(
        state.runtime_store,
        session_id=session.session_id,
        target_status="running",
        observability_store=state.observability_store,
        start_path=start_path,
    )


def _handle_session_collection(state: PlatformState, context: RequestSession, method: str, body: dict, start_response: StartResponse, *, start_path):
    if method == "GET":
        return json_response(start_response, {"items": _list_session_payloads(state, workspace_id=context.workspace_id, start_path=start_path)})
    if method == "POST":
        agent_id = str(body.get("agent_id") or "").strip()
        if not agent_id:
            return json_response(start_response, {"error": "agent_id_required"}, status="400 Bad Request")
        session = _create_session(state, context, body, agent_id=agent_id, start_path=start_path)
        provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
        return json_response(start_response, _session_payload(session, provider_id=provider.provider_id), status="201 Created")
    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _handle_session_item(state: PlatformState, context: RequestSession, session_id: str, start_response: StartResponse, *, start_path):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    session = _reconciled_session(state, session, start_path=start_path)
    provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    return json_response(start_response, _session_payload(session, provider_id=provider.provider_id))


def _bounded_positive_int(value: str | None, *, maximum: int) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return min(parsed, maximum)


def _handle_session_events(state: PlatformState, context: RequestSession, session_id: str, start_response: StartResponse, *, start_path, query_string: str = ""):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    _reconciled_session(state, session, start_path=start_path)
    events = state.runtime_store.list_events(session_id)
    query = parse_qs(query_string, keep_blank_values=False)
    limit = _bounded_positive_int(query.get("limit", [None])[0], maximum=5000)
    if limit is not None:
        events = events[-limit:]
    return json_response(
        start_response,
        {"items": [_event_payload(event) for event in events]},
    )


def _handle_session_turns(state: PlatformState, context: RequestSession, session_id: str, method: str, body: dict, start_response: StartResponse, *, start_path):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    session = _reconciled_session(state, session, start_path=start_path)
    if method == "GET":
        return json_response(start_response, {"items": [_turn_payload(turn) for turn in state.runtime_store.list_turns(session_id)]})
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    client_message_id = str(body.get("client_message_id") or "").strip() or None
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    attachment_items = [item for item in attachments if isinstance(item, dict)]
    app_references = body.get("app_references") if isinstance(body.get("app_references"), list) else []
    app_reference_items = [
        reference
        for item in app_references
        if isinstance(item, dict)
        for reference in [_app_reference_payload(item)]
        if reference["app_id"]
    ]
    input_text = str(body.get("input_text") or body.get("message") or "").strip()
    if not input_text and not attachment_items:
        return json_response(start_response, {"error": "empty_runtime_input"}, status="400 Bad Request")
    async_requested = bool(body.get("async"))
    if async_requested:
        turn, events = submit_runtime_turn_async(
            state,
            session=session,
            input_text=input_text,
            client_message_id=client_message_id,
            attachments=attachment_items,
            app_references=app_reference_items,
        )
        status = "202 Accepted"
    else:
        turn, events = submit_runtime_turn(
            state,
            session=session,
            input_text=input_text,
            client_message_id=client_message_id,
            attachments=attachment_items,
            app_references=app_reference_items,
        )
        status = status_line(201)
    return json_response(
        start_response,
        {
            "session": _session_payload(session, provider_id=resolve_provider_for_runtime_session(state.provider_store, session=session)[0].provider_id),
            "turn": _turn_payload(turn),
            "events": [_event_payload(event) for event in events],
        },
        status=status,
    )


def _app_reference_payload(item: dict) -> dict[str, str]:
    app_id = str(item.get("app_id") or "").strip()
    label = str(item.get("label") or "").strip()
    payload = {"type": "app", "app_id": app_id}
    if label:
        payload["label"] = label
    return payload


def _handle_session_cleanup(
    state: PlatformState,
    context: RequestSession,
    session_id: str,
    method: str,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
):
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    reason = str(body.get("reason") or "").strip() or "runtime_session_cleaned"
    result = cleanup_runtime_session(
        state,
        session_id=session_id,
        reason=reason,
        start_path=start_path,
    )
    return json_response(start_response, result)


def _handle_turn_item(state: PlatformState, context: RequestSession, turn_id: str, start_response: StartResponse):
    try:
        turn = state.runtime_store.get_turn(turn_id)
    except RuntimeTurnNotFoundError:
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    if turn.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    return json_response(start_response, _turn_payload(turn))


def _handle_turn_interrupt(state: PlatformState, context: RequestSession, turn_id: str, start_response: StartResponse):
    try:
        turn = state.runtime_store.get_turn(turn_id)
    except RuntimeTurnNotFoundError:
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    if turn.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    if turn.status not in {"queued", "active"}:
        return json_response(start_response, {"turn": _turn_payload(turn), "interrupted": False})
    provider_interrupted = interrupt_codex_app_server_turn(turn.session_id)
    updated = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="cancelled", failure_reason="Interrupted by user.")
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=updated.session_id,
        turn_id=updated.turn_id,
        plane="turn",
        event_type="runtime.turn.cancelled",
        payload={"reason": "interrupted_by_user"},
        event_bus=state.runtime_event_bus,
    )
    return json_response(start_response, {"turn": _turn_payload(updated), "event": _event_payload(event), "interrupted": True, "provider_interrupted": provider_interrupted})


def handle_runtime_api(state: PlatformState, environ: dict, start_response: StartResponse, *, start_path) -> list[bytes] | None:
    """Handle generic runtime routes for apps and shell clients."""
    path = environ.get("PATH_INFO", "/")
    if not path.startswith("/api/runtime/"):
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    method = environ.get("REQUEST_METHOD", "GET").upper()
    query_string = environ.get("QUERY_STRING", "")
    body = read_json_body(environ) if method in {"POST", "PATCH", "PUT"} else {}

    if path == "/api/runtime/sessions":
        return _handle_session_collection(state, context, method, body, start_response, start_path=start_path)

    parts = [part for part in path.removeprefix("/api/runtime/").split("/") if part]
    if len(parts) == 2 and parts[0] == "sessions" and method == "GET":
        return _handle_session_item(state, context, parts[1], start_response, start_path=start_path)
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "events" and method == "GET":
        return _handle_session_events(state, context, parts[1], start_response, start_path=start_path, query_string=query_string)
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "turns":
        return _handle_session_turns(state, context, parts[1], method, body, start_response, start_path=start_path)
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "cleanup":
        return _handle_session_cleanup(state, context, parts[1], method, body, start_response, start_path=start_path)
    if len(parts) == 2 and parts[0] == "turns" and method == "GET":
        return _handle_turn_item(state, context, parts[1], start_response)
    if len(parts) == 3 and parts[0] == "turns" and parts[2] == "interrupt" and method == "POST":
        return _handle_turn_interrupt(state, context, parts[1], start_response)
    return json_response(start_response, {"error": "runtime_route_not_found"}, status="404 Not Found")
