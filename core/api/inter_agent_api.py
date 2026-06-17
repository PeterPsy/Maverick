"""HTTP API for core-owned inter-agent runtime operations."""

from __future__ import annotations

from urllib.parse import parse_qs

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.runtime_cleanup import cleanup_runtime_session
from core.api.session_api import RequestSession, require_session
from core.authorization.errors import AuthorizationError
from core.authorization.service import authorize_runtime_session_create
from core.inter_agent.errors import (
    InterAgentBudgetExceededError,
    InterAgentOperationError,
    InterAgentParticipantNotFoundError,
    InterAgentRunNotFoundError,
    InterAgentValidationError,
)
from core.inter_agent.events import validate_visibility_plane
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import DEFAULT_INTER_AGENT_EVENT_LIMIT, MAX_INTER_AGENT_EVENT_LIMIT
from core.inter_agent.surfaces import event_page_payload, inter_agent_payload, run_detail_payload, run_spec_from_payload
from core.providers.errors import ProviderError
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.workspaces.errors import WorkspaceMembershipError


def handle_inter_agent_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path,
) -> list[bytes] | None:
    """Handle core-owned inter-agent HTTP routes."""
    path = str(environ.get("PATH_INFO") or "/")
    if not path.startswith("/api/inter-agent"):
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    body = read_json_body(environ) if method in {"POST", "PATCH", "PUT", "DELETE"} else {}
    service = InterAgentService(state.inter_agent_store)
    try:
        return _handle_inter_agent_route(
            state,
            context,
            service,
            path=path,
            method=method,
            body=body,
            query_string=str(environ.get("QUERY_STRING") or ""),
            start_response=start_response,
            start_path=start_path,
        )
    except InterAgentRunNotFoundError:
        return json_response(start_response, {"error": "inter_agent_run_not_found"}, status="404 Not Found")
    except InterAgentParticipantNotFoundError:
        return json_response(start_response, {"error": "inter_agent_participant_not_found"}, status="404 Not Found")
    except InterAgentBudgetExceededError as error:
        return json_response(
            start_response,
            {"error": "inter_agent_budget_exceeded", "detail": str(error)},
            status="409 Conflict",
        )
    except InterAgentValidationError as error:
        return json_response(start_response, {"error": "inter_agent_validation_failed", "detail": str(error)}, status="400 Bad Request")
    except InterAgentOperationError as error:
        return json_response(start_response, {"error": "inter_agent_operation_failed", "detail": str(error)}, status="409 Conflict")
    except ProviderError as error:
        return json_response(start_response, {"error": "provider_unavailable", "detail": str(error)}, status="409 Conflict")
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")


def _handle_inter_agent_route(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    *,
    path: str,
    method: str,
    body: dict,
    query_string: str,
    start_response: StartResponse,
    start_path,
) -> list[bytes]:
    if path == "/api/inter-agent/runs":
        if method == "POST":
            return _create_run(state, context, service, body, start_response)
        if method == "GET":
            runs = [
                run_detail_payload(state.inter_agent_store, run)
                for run in state.inter_agent_store.list_runs(context.workspace_id)
            ]
            return json_response(start_response, {"items": runs})
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")

    parts = [part for part in path.removeprefix("/api/inter-agent/").split("/") if part]
    if len(parts) < 2 or parts[0] != "runs":
        return json_response(start_response, {"error": "inter_agent_route_not_found"}, status="404 Not Found")
    run_id = parts[1]
    run = state.inter_agent_store.get_run(run_id, workspace_id=context.workspace_id)
    _authorize_run_view(context, run.workspace_id)

    if len(parts) == 2:
        if method == "GET":
            return json_response(start_response, run_detail_payload(state.inter_agent_store, run))
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    action = parts[2]
    if action == "events" and method == "GET":
        query = parse_qs(query_string, keep_blank_values=False)
        visibility = validate_visibility_plane(query.get("visibility_plane", ["summary"])[0])
        page = state.inter_agent_store.list_event_page(
            run.run_id,
            workspace_id=context.workspace_id,
            visibility_plane=visibility,
            after_event_id=_query_text(query, "after_event_id"),
            before_event_id=_query_text(query, "before_event_id"),
            limit=_query_limit(query),
        )
        return json_response(start_response, event_page_payload(page))
    _authorize_run_mutation(state, context, run.created_by_user_id)
    if action == "participants" and method == "POST":
        return _spawn_participant(state, context, service, run.run_id, body, start_response)
    if action == "messages" and method == "POST":
        return _send_message(state, context, service, run.run_id, body, start_response)
    if action == "wait" and method in {"GET", "POST"}:
        timeout = float(body.get("timeout_seconds") or _query_text(parse_qs(query_string), "timeout_seconds") or 0)
        waited = service.wait_for_run(workspace_id=context.workspace_id, run_id=run.run_id, timeout_seconds=timeout)
        return json_response(start_response, run_detail_payload(state.inter_agent_store, waited))
    if action == "interrupt" and method == "POST":
        result = service.interrupt_run(
            state,
            workspace_id=context.workspace_id,
            run_id=run.run_id,
            participant_id=_text(body.get("participant_id")) or None,
            reason=_text(body.get("reason")) or "inter_agent_interrupt",
        )
        return json_response(start_response, inter_agent_payload(result))
    if action == "resume" and method == "POST":
        resumed = service.resume_run(
            workspace_id=context.workspace_id,
            run_id=run.run_id,
            reason=_text(body.get("reason")) or "inter_agent_resume",
        )
        return json_response(start_response, run_detail_payload(state.inter_agent_store, resumed))
    if action == "close" and method == "POST":
        result = service.close_run(
            workspace_id=context.workspace_id,
            run_id=run.run_id,
            cleanup_runtime_session=lambda session_id, reason: cleanup_runtime_session(
                state,
                session_id=session_id,
                reason=reason,
                start_path=start_path,
            ),
            reason=_text(body.get("reason")) or "inter_agent_run_closed",
            terminal_status=_text(body.get("terminal_status")) or "cancelled",
            delete_records=bool(body.get("delete_records")),
        )
        return json_response(start_response, inter_agent_payload(result))
    return json_response(start_response, {"error": "inter_agent_route_not_found"}, status="404 Not Found")


def _create_run(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    spec = run_spec_from_payload(body, workspace_id=context.workspace_id, created_by_user_id=context.user.user_id)
    try:
        root_session = state.runtime_store.get_session(spec.root_runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "root_runtime_session_not_found"}, status="404 Not Found")
    if root_session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "root_runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(root_session):
        return json_response(start_response, {"error": "root_runtime_session_hidden"}, status="409 Conflict")
    run = service.create_run(spec)
    return json_response(start_response, run_detail_payload(state.inter_agent_store, run), status="201 Created")


def _spawn_participant(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    run_id: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    authorize_runtime_session_create(
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        user=context.user,
        workspace_id=context.workspace_id,
    )
    owner_user_id = _text(body.get("owner_user_id")) or None
    if owner_user_id and owner_user_id != context.user.user_id and not _is_workspace_admin(state, context):
        raise AuthorizationError("inter_agent_owner_forbidden")
    participant, session, created = service.spawn_participant_runtime_session(
        state.runtime_store,
        workspace_id=context.workspace_id,
        run_id=run_id,
        participant_id=_text(body.get("participant_id")),
        child_session_id=_text(body.get("child_session_id")) or None,
        child_agent_id=_text(body.get("child_agent_id")) or None,
        system_prompt=_text(body.get("system_prompt")) or None,
        skill_ids=_string_list(body.get("skill_ids")) if "skill_ids" in body else None,
        skill_catalog_app_id=_text(body.get("skill_catalog_app_id")) or None,
        source_app_id=_text(body.get("source_app_id")) or None,
        owner_user_id=owner_user_id,
        created_by_user_id=context.user.user_id,
        grants=_platform_grants(body.get("grants")),
    )
    return json_response(
        start_response,
        {"participant": inter_agent_payload(participant), "runtime_session": inter_agent_payload(session)},
        status="201 Created" if created else "200 OK",
    )


def _send_message(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    run_id: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    participant, turn, events = service.send_runtime_message(
        state,
        workspace_id=context.workspace_id,
        run_id=run_id,
        participant_id=_text(body.get("participant_id")),
        input_text=_text(body.get("input_text")) or _text(body.get("message")),
        client_message_id=_text(body.get("client_message_id")) or None,
        async_requested=bool(body.get("async")),
    )
    return json_response(
        start_response,
        {
            "participant": inter_agent_payload(participant),
            "turn": inter_agent_payload(turn),
            "events": inter_agent_payload(events),
        },
        status="202 Accepted" if body.get("async") else "201 Created",
    )


def _authorize_run_view(context: RequestSession, workspace_id: str) -> None:
    if context.workspace_id != workspace_id:
        raise AuthorizationError("inter_agent_run_not_found")


def _authorize_run_mutation(state: PlatformState, context: RequestSession, created_by_user_id: str) -> None:
    if context.user.platform_role == "admin" or _is_workspace_admin(state, context):
        return
    if created_by_user_id == context.user.user_id:
        return
    raise AuthorizationError("inter_agent_run_operation_forbidden")


def _is_workspace_admin(state: PlatformState, context: RequestSession) -> bool:
    try:
        membership = state.workspace_store.get_membership(
            user_id=context.user.user_id,
            workspace_id=context.workspace_id,
        )
    except WorkspaceMembershipError:
        return False
    return membership.status == "active" and membership.role == "admin"


def _query_text(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return _text(values[-1]) or None


def _query_limit(query: dict[str, list[str]]) -> int:
    value = _query_text(query, "limit")
    if not value:
        return DEFAULT_INTER_AGENT_EVENT_LIMIT
    try:
        return max(1, min(int(value), MAX_INTER_AGENT_EVENT_LIMIT))
    except ValueError:
        return DEFAULT_INTER_AGENT_EVENT_LIMIT


def _platform_grants(value) -> list[dict[str, str | None]] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, dict)]


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value) -> str:
    return str(value or "").strip()
