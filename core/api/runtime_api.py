"""Generic runtime HTTP API for hosted Maverick v3 apps."""

from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeTurnNotFoundError
from core.runtime.execution import execute_runtime_turn
from core.runtime.service import (
    create_runtime_session,
    queue_runtime_turn,
    record_runtime_event,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord


def _session_payload(session: RuntimeSessionRecord, *, provider_id: str | None = None) -> dict[str, object]:
    payload = asdict(session)
    if provider_id is not None:
        payload["provider_id"] = provider_id
    return payload


def _turn_payload(turn: RuntimeTurnRecord) -> dict[str, object]:
    return asdict(turn)


def _event_payload(event: RuntimeEventRecord) -> dict[str, object]:
    return asdict(event)


def _list_session_payloads(state: PlatformState, *, workspace_id: str) -> list[dict[str, object]]:
    sessions = state.runtime_store.list_sessions(workspace_id)
    return [_session_payload(session, provider_id=resolve_provider_for_runtime_session(state.provider_store, session=session)[0].provider_id) for session in sessions]


def _create_session(state: PlatformState, context: RequestSession, body: dict, *, start_path) -> RuntimeSessionRecord:
    session = create_runtime_session(
        state.runtime_store,
        session_id=str(uuid4()),
        workspace_id=context.workspace_id,
        agent_id=str(body.get("agent_id") or "chat"),
        requested_mode=body.get("requested_mode"),
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


def _run_turn(state: PlatformState, *, session: RuntimeSessionRecord, input_text: str) -> tuple[RuntimeTurnRecord, list[RuntimeEventRecord]]:
    provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    turn = queue_runtime_turn(state.runtime_store, turn_id=str(uuid4()), session_id=session.session_id, input_text=input_text)
    events: list[RuntimeEventRecord] = []
    events.append(
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"input_text": input_text, "provider_id": provider.provider_id},
        )
    )
    turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
    events.append(
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.turn.started",
            payload={"provider_id": provider.provider_id},
        )
    )
    try:
        result = execute_runtime_turn(session=session, provider=provider, input_text=input_text)
    except Exception as error:
        turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn.turn_id,
            target_status="failed",
            failure_reason=str(error),
        )
        events.append(
            record_runtime_event(
                state.runtime_store,
                event_id=str(uuid4()),
                session_id=session.session_id,
                turn_id=turn.turn_id,
                plane="turn",
                event_type="runtime.turn.failed",
                payload={"error": str(error), "provider_id": provider.provider_id},
            )
        )
        return turn, events

    events.append(
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.output.final",
            payload={"text": result.output_text, "provider_id": provider.provider_id, "exit_code": result.exit_code},
        )
    )
    if result.exit_code == 0:
        turn = transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="completed")
        event_type = "runtime.turn.completed"
    else:
        turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn.turn_id,
            target_status="failed",
            failure_reason=f"Provider exited with code {result.exit_code}.",
        )
        event_type = "runtime.turn.failed"
    events.append(
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type=event_type,
            payload={"provider_id": provider.provider_id, "exit_code": result.exit_code},
        )
    )
    return turn, events


def _handle_session_collection(state: PlatformState, context: RequestSession, method: str, body: dict, start_response: StartResponse, *, start_path):
    if method == "GET":
        return json_response(start_response, {"items": _list_session_payloads(state, workspace_id=context.workspace_id)})
    if method == "POST":
        session = _create_session(state, context, body, start_path=start_path)
        provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
        return json_response(start_response, _session_payload(session, provider_id=provider.provider_id), status="201 Created")
    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _handle_session_item(state: PlatformState, context: RequestSession, session_id: str, start_response: StartResponse):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    return json_response(start_response, _session_payload(session, provider_id=provider.provider_id))


def _handle_session_events(state: PlatformState, context: RequestSession, session_id: str, start_response: StartResponse):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    return json_response(
        start_response,
        {"items": [_event_payload(event) for event in state.runtime_store.list_events(session_id)]},
    )


def _handle_session_turns(state: PlatformState, context: RequestSession, session_id: str, method: str, body: dict, start_response: StartResponse):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if method == "GET":
        return json_response(start_response, {"items": [_turn_payload(turn) for turn in state.runtime_store.list_turns(session_id)]})
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    input_text = str(body.get("input_text") or body.get("message") or "").strip()
    if not input_text:
        return json_response(start_response, {"error": "empty_runtime_input"}, status="400 Bad Request")
    turn, events = _run_turn(state, session=session, input_text=input_text)
    return json_response(
        start_response,
        {
            "session": _session_payload(session, provider_id=resolve_provider_for_runtime_session(state.provider_store, session=session)[0].provider_id),
            "turn": _turn_payload(turn),
            "events": [_event_payload(event) for event in events],
        },
        status=status_line(201),
    )


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
    updated = transition_runtime_turn(state.runtime_store, turn_id=turn_id, target_status="cancelled", failure_reason="Interrupted by user.")
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=updated.session_id,
        turn_id=updated.turn_id,
        plane="turn",
        event_type="runtime.turn.cancelled",
        payload={"reason": "interrupted_by_user"},
    )
    return json_response(start_response, {"turn": _turn_payload(updated), "event": _event_payload(event), "interrupted": True})


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
    body = read_json_body(environ) if method in {"POST", "PATCH", "PUT"} else {}

    if path == "/api/runtime/sessions":
        return _handle_session_collection(state, context, method, body, start_response, start_path=start_path)

    parts = [part for part in path.removeprefix("/api/runtime/").split("/") if part]
    if len(parts) == 2 and parts[0] == "sessions" and method == "GET":
        return _handle_session_item(state, context, parts[1], start_response)
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "events" and method == "GET":
        return _handle_session_events(state, context, parts[1], start_response)
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "turns":
        return _handle_session_turns(state, context, parts[1], method, body, start_response)
    if len(parts) == 2 and parts[0] == "turns" and method == "GET":
        return _handle_turn_item(state, context, parts[1], start_response)
    if len(parts) == 3 and parts[0] == "turns" and parts[2] == "interrupt" and method == "POST":
        return _handle_turn_interrupt(state, context, parts[1], start_response)
    return json_response(start_response, {"error": "runtime_route_not_found"}, status="404 Not Found")
