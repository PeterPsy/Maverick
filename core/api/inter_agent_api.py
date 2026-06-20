"""HTTP API for core-owned inter-agent runtime operations."""

from __future__ import annotations

from threading import Thread
from urllib.parse import parse_qs
from uuid import uuid4

from core.api.app_reference_payloads import materialize_runtime_app_references
from core.api.app_registry import enabled_app_items
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.runtime_cleanup import cleanup_runtime_session
from core.api.session_api import RequestSession, require_session
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError
from core.apps.runtime_requests import invoke_dependency_backend_request
from core.authorization.errors import AuthorizationError
from core.inter_agent.authorization import (
    authorize_inter_agent_approval_resolution,
    authorized_inter_agent_event_visibility,
    authorize_inter_agent_participant_spawn,
    authorize_inter_agent_root_session_use,
    authorize_inter_agent_run_sensitive_view,
    authorize_inter_agent_run_operation,
    authorize_inter_agent_run_view,
)
from core.inter_agent.errors import (
    InterAgentApprovalNotFoundError,
    InterAgentBudgetExceededError,
    InterAgentEventNotFoundError,
    InterAgentOperationError,
    InterAgentParticipantNotFoundError,
    InterAgentRunNotFoundError,
    InterAgentValidationError,
)
from core.inter_agent.events import validate_visibility_plane
from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import DEFAULT_INTER_AGENT_EVENT_LIMIT, MAX_INTER_AGENT_EVENT_LIMIT
from core.inter_agent.surfaces import (
    artifact_items_payload,
    event_page_payload,
    execution_result_payload,
    inter_agent_payload,
    run_detail_payload,
    run_spec_from_payload,
)
from core.providers.errors import ProviderError
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.service import queue_runtime_turn, record_runtime_event, transition_runtime_turn
from core.runtime.thread_catalog_events import (
    mark_thread_response_completed,
    mark_thread_user_message_queued,
    set_thread_availability,
)
from core.runtime.thread_title_jobs import schedule_runtime_thread_title_generation, thread_title_input_hash
from core.skills.runtime_catalog import (
    selected_runtime_skill_catalog_app_id_for_source_app,
    validate_runtime_skill_catalog_provider_app_id,
)
from core.workspaces.errors import WorkspaceMembershipError


CHAT_APP_ID = "chat"
CHAT_AGENT_PROVIDER_ALIASES = ("agent-catalog", "agent-prompt-materializer")
ACTIVE_APP_CONTEXT_HEADER = "Current shell context:"
ACTIVE_APP_CONTEXT_KEYS = {"active_app_id", "active_app_name", "active_app_description"}


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
    except InterAgentApprovalNotFoundError:
        return json_response(start_response, {"error": "inter_agent_approval_not_found"}, status="404 Not Found")
    except InterAgentEventNotFoundError as error:
        return json_response(
            start_response,
            {"error": "inter_agent_event_not_found", "detail": str(error)},
            status="404 Not Found",
        )
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
            return _create_run(state, context, service, body, start_response, start_path=start_path)
        if method == "GET":
            runs = [
                run_detail_payload(state.inter_agent_store, run)
                for run in state.inter_agent_store.list_runs(context.workspace_id)
                if _can_view_run_detail(state, context, run)
            ]
            return json_response(start_response, {"items": runs})
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")

    parts = [part for part in path.removeprefix("/api/inter-agent/").split("/") if part]
    if len(parts) == 3 and parts[0] == "approvals" and parts[2] == "resolve" and method == "POST":
        return _resolve_approval(state, context, service, parts[1], body, start_response)
    if len(parts) < 2 or parts[0] != "runs":
        return json_response(start_response, {"error": "inter_agent_route_not_found"}, status="404 Not Found")
    run_id = parts[1]
    run = state.inter_agent_store.get_run(run_id, workspace_id=context.workspace_id)
    authorize_inter_agent_run_view(context_workspace_id=context.workspace_id, run_workspace_id=run.workspace_id)

    if len(parts) == 2:
        if method == "GET":
            authorize_inter_agent_run_sensitive_view(
                workspace_store=state.workspace_store,
                context_workspace_id=context.workspace_id,
                caller_kind="http",
                run=run,
                user_id=context.user.user_id,
                platform_role=context.user.platform_role,
                root_session=_root_session_for_run(state, run),
            )
            return json_response(start_response, run_detail_payload(state.inter_agent_store, run))
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    action = parts[2]
    if action == "events" and method == "GET":
        query = parse_qs(query_string, keep_blank_values=False)
        visibility = authorized_inter_agent_event_visibility(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            requested_visibility_plane=validate_visibility_plane(query.get("visibility_plane", ["summary"])[0]),
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
        page = state.inter_agent_store.list_event_page(
            run.run_id,
            workspace_id=context.workspace_id,
            visibility_plane=visibility,
            after_event_id=_query_text(query, "after_event_id"),
            before_event_id=_query_text(query, "before_event_id"),
            limit=_query_limit(query),
        )
        return json_response(start_response, event_page_payload(page))
    if action == "artifacts" and method == "GET":
        query = parse_qs(query_string, keep_blank_values=False)
        visibility = authorized_inter_agent_event_visibility(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            requested_visibility_plane=validate_visibility_plane(query.get("visibility_plane", ["detail"])[0]),
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
        page = state.inter_agent_store.list_event_page(
            run.run_id,
            workspace_id=context.workspace_id,
            visibility_plane=visibility,
            event_types={"inter_agent.artifact.created"},
            after_event_id=_query_text(query, "after_event_id"),
            before_event_id=_query_text(query, "before_event_id"),
            limit=_query_limit(query),
        )
        return json_response(
            start_response,
            {
                **event_page_payload(page),
                "items": artifact_items_payload(page.events),
            },
        )
    if action == "approvals" and method == "GET":
        authorize_inter_agent_run_sensitive_view(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
        service.expire_pending_approvals(run)
        return json_response(
            start_response,
            {
                "items": inter_agent_payload(
                    state.inter_agent_store.list_approvals(run.run_id, workspace_id=context.workspace_id)
                )
            },
        )
    if len(parts) == 5 and action == "participants" and parts[4] == "transcript" and method == "GET":
        authorize_inter_agent_run_sensitive_view(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
        participant = state.inter_agent_store.get_participant(
            parts[3],
            workspace_id=context.workspace_id,
            run_id=run.run_id,
        )
        query = parse_qs(query_string, keep_blank_values=False)
        visibility = authorized_inter_agent_event_visibility(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            requested_visibility_plane="detail",
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
        return json_response(
            start_response,
            _participant_transcript_payload(
                state,
                run,
                participant,
                limit=_query_limit(query),
                visibility_plane=visibility,
            ),
        )
    if action == "participants" and method == "POST":
        return _spawn_participant(state, context, service, run, body, start_response)
    authorize_inter_agent_run_operation(
        workspace_store=state.workspace_store,
        context_workspace_id=context.workspace_id,
        caller_kind="http",
        run=run,
        user_id=context.user.user_id,
        platform_role=context.user.platform_role,
    )
    if action == "messages" and method == "POST":
        return _send_message(state, context, service, run.run_id, body, start_response)
    if action == "execute" and method == "POST":
        return _execute_run(state, context, service, run, body, start_response, start_path=start_path)
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
                allow_hidden_inter_agent_cleanup=True,
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
    *,
    start_path,
) -> list[bytes]:
    root_session_id = _text(body.get("root_runtime_session_id"))
    try:
        root_session = state.runtime_store.get_session(root_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "root_runtime_session_not_found"}, status="404 Not Found")
    if root_session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "root_runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(root_session):
        return json_response(start_response, {"error": "root_runtime_session_hidden"}, status="409 Conflict")
    try:
        authorize_inter_agent_root_session_use(
            workspace_store=state.workspace_store,
            user=context.user,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            root_session=root_session,
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
        )
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    materialized_body, allow_agent_snapshots = _materialize_agent_snapshots_for_payload(
        state,
        context,
        root_session,
        body,
        start_path=start_path,
    )
    spec = run_spec_from_payload(
        materialized_body,
        workspace_id=context.workspace_id,
        created_by_user_id=context.user.user_id,
        source_app_id=root_session.source_app_id or "chat",
        allow_agent_snapshots=allow_agent_snapshots,
    )
    run = service.create_run(spec)
    return json_response(start_response, run_detail_payload(state.inter_agent_store, run), status="201 Created")


def _spawn_participant(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    run,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    owner_user_id = _text(body.get("owner_user_id")) or None
    try:
        root_session = state.runtime_store.get_session(run.root_runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "root_runtime_session_not_found"}, status="404 Not Found")
    authorize_inter_agent_participant_spawn(
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        user=context.user,
        context_workspace_id=context.workspace_id,
        caller_kind="http",
        run=run,
        owner_user_id=owner_user_id,
        user_id=context.user.user_id,
        platform_role=context.user.platform_role,
    )
    authorize_inter_agent_root_session_use(
        workspace_store=state.workspace_store,
        user=context.user,
        context_workspace_id=context.workspace_id,
        caller_kind="http",
        root_session=root_session,
        user_id=context.user.user_id,
        platform_role=context.user.platform_role,
    )
    participant, session, created = service.spawn_participant_runtime_session(
        state.runtime_store,
        workspace_id=context.workspace_id,
        run_id=run.run_id,
        participant_id=_text(body.get("participant_id")),
        child_session_id=_text(body.get("child_session_id")) or None,
        child_agent_id=_text(body.get("child_agent_id")) or None,
        owner_user_id=owner_user_id,
        created_by_user_id=context.user.user_id,
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


def _participant_transcript_payload(state: PlatformState, run, participant, *, limit: int, visibility_plane: str) -> dict:
    """Project one participant into a product-facing transcript without hidden-session metadata."""
    if visibility_plane in {"detail", "debug"}:
        runtime_items, runtime_turn_ids_with_output = _runtime_participant_transcript_items(
            state,
            participant,
            limit=limit,
        )
    else:
        runtime_items, runtime_turn_ids_with_output = [], set()
    event_items, event_truncated = _inter_agent_participant_transcript_items(
        state,
        run,
        participant,
        runtime_turn_ids_with_output=runtime_turn_ids_with_output,
        limit=limit,
        visibility_plane=visibility_plane,
    )
    ordered = sorted(
        [*runtime_items, *event_items],
        key=lambda item: (str(item.get("created_at") or ""), int(item.get("_sequence") or 0), str(item.get("_source") or "")),
    )
    items = [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in ordered[-limit:]
    ]
    for index, item in enumerate(items, start=1):
        item["message_id"] = f"{participant.participant_id}:message:{index}"
    return {
        "run_id": run.run_id,
        "participant": {
            "participant_id": participant.participant_id,
            "label": participant.label,
            "kind": participant.kind,
            "status": participant.status,
        },
        "visibility_plane": visibility_plane,
        "items": items,
        "item_count": len(items),
        "truncated": event_truncated or len(ordered) > len(items),
    }


def _runtime_participant_transcript_items(state: PlatformState, participant, *, limit: int) -> tuple[list[dict], set[str]]:
    session_id = _text(getattr(participant, "runtime_session_id", None))
    if not session_id:
        return [], set()
    try:
        session = state.runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return [], set()
    if session.workspace_id != participant.workspace_id:
        return [], set()
    turns = sorted(state.runtime_store.list_turns(session_id), key=lambda item: (item.created_at, item.turn_id))
    events = sorted(state.runtime_store.list_events(session_id), key=lambda item: (item.created_at, item.event_id))
    events_by_turn: dict[str, list] = {}
    for event in events:
        if event.turn_id:
            events_by_turn.setdefault(event.turn_id, []).append(event)
    items: list[dict] = []
    turn_ids_with_output: set[str] = set()
    for turn in turns[-limit:]:
        if turn.input_text:
            items.append(
                _safe_transcript_item(
                    kind="input",
                    role="user",
                    text=turn.input_text,
                    created_at=turn.created_at,
                    status=turn.status,
                    source=f"runtime-turn-input:{turn.turn_id}",
                )
            )
        output_text = _runtime_turn_output_text(events_by_turn.get(turn.turn_id, []))
        if output_text:
            turn_ids_with_output.add(turn.turn_id)
            items.append(
                _safe_transcript_item(
                    kind="output",
                    role="participant",
                    text=output_text,
                    created_at=turn.completed_at or turn.updated_at,
                    status=turn.status,
                    source=f"runtime-turn-output:{turn.turn_id}",
                )
            )
        elif turn.failure_reason:
            items.append(
                _safe_transcript_item(
                    kind="status",
                    role="system",
                    text=turn.failure_reason,
                    created_at=turn.updated_at,
                    status=turn.status,
                    source=f"runtime-turn-failure:{turn.turn_id}",
                )
            )
    return items, turn_ids_with_output


def _inter_agent_participant_transcript_items(
    state: PlatformState,
    run,
    participant,
    *,
    runtime_turn_ids_with_output: set[str],
    limit: int,
    visibility_plane: str,
) -> tuple[list[dict], bool]:
    items: list[dict] = []
    before_event_id: str | None = None
    target_count = limit + 1
    page_limit = min(MAX_INTER_AGENT_EVENT_LIMIT, max(limit * 3, DEFAULT_INTER_AGENT_EVENT_LIMIT))
    transcript_event_types = {
        "inter_agent.message.sent",
        "inter_agent.task.assigned",
        "inter_agent.task.completed",
        "inter_agent.summary.updated",
        "inter_agent.artifact.created",
        "inter_agent.approval.requested",
        "inter_agent.approval.resolved",
    }
    while len(items) < target_count:
        page = state.inter_agent_store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane=visibility_plane,
            event_types=transcript_event_types,
            before_event_id=before_event_id,
            limit=page_limit,
        )
        for event in page.events:
            if event.participant_id != participant.participant_id:
                continue
            item = _transcript_item_from_inter_agent_event(
                event,
                runtime_turn_ids_with_output=runtime_turn_ids_with_output,
            )
            if item:
                items.append(item)
        if len(items) >= target_count:
            break
        if not page.has_more_before or not page.oldest_event_id:
            break
        before_event_id = page.oldest_event_id
    return items, len(items) > limit


def _transcript_item_from_inter_agent_event(event, *, runtime_turn_ids_with_output: set[str]) -> dict | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event.event_type == "inter_agent.task.assigned":
        text = _text(payload.get("input_text")) or _text(payload.get("task"))
        if not text:
            return None
        return _safe_transcript_item(
            kind="input",
            role="user",
            text=text,
            created_at=event.created_at,
            status=_text(payload.get("status")) or "assigned",
            source=f"inter-agent-input:{event.sequence}",
            sequence=event.sequence,
        )
    if event.event_type == "inter_agent.message.sent":
        text = _text(payload.get("input_text")) or _text(payload.get("message")) or _text(payload.get("content"))
        if not text:
            return None
        return _safe_transcript_item(
            kind="input",
            role="user",
            text=text,
            created_at=event.created_at,
            status=_text(payload.get("status")) or "sent",
            source=f"inter-agent-message:{event.sequence}",
            sequence=event.sequence,
        )
    if event.event_type == "inter_agent.task.completed":
        if _text(event.runtime_turn_id) in runtime_turn_ids_with_output:
            return None
        text = _text(payload.get("output_text")) or _text(payload.get("summary")) or _text(payload.get("error"))
        if not text:
            return None
        return _safe_transcript_item(
            kind="output",
            role="participant",
            text=text,
            created_at=event.created_at,
            status=_text(payload.get("status")) or "completed",
            source=f"inter-agent-output:{event.sequence}",
            sequence=event.sequence,
        )
    if event.event_type == "inter_agent.summary.updated":
        text = _text(payload.get("summary"))
        if not text:
            return None
        return _safe_transcript_item(
            kind="summary",
            role="participant",
            text=text,
            created_at=event.created_at,
            status=_text(payload.get("status")) or "updated",
            source=f"inter-agent-summary:{event.sequence}",
            sequence=event.sequence,
        )
    if event.event_type == "inter_agent.artifact.created":
        artifact_refs = payload.get("artifact_refs")
        if not isinstance(artifact_refs, list):
            artifact_refs = []
        labels = [
            _artifact_ref_label(ref)
            for ref in artifact_refs
            if isinstance(ref, dict) and _artifact_ref_label(ref)
        ]
        text = _text(payload.get("partial_output"))
        if labels:
            text = "\n".join(
                [
                    *(["Created artifacts: " + ", ".join(labels)] if labels else []),
                    *([text] if text else []),
                ]
            )
        if not text:
            return None
        return _safe_transcript_item(
            kind="artifact",
            role="participant",
            text=text,
            created_at=event.created_at,
            status=_text(payload.get("status")) or "created",
            source=f"inter-agent-artifact:{event.sequence}",
            sequence=event.sequence,
        )
    if event.event_type in {"inter_agent.approval.requested", "inter_agent.approval.resolved"}:
        text = _text(payload.get("summary")) or _text(payload.get("status"))
        if not text:
            return None
        return _safe_transcript_item(
            kind="approval",
            role="system",
            text=text,
            created_at=event.created_at,
            status=_text(payload.get("status")) or event.event_type.rsplit(".", 1)[-1],
            source=f"inter-agent-approval:{event.sequence}",
            sequence=event.sequence,
        )
    return None


def _runtime_turn_output_text(events: list) -> str:
    final_events = [event for event in events if event.event_type == "runtime.output.final"]
    for event in reversed(final_events):
        payload = event.payload if isinstance(event.payload, dict) else {}
        text = _text(payload.get("complete_text")) or _text(payload.get("text"))
        if text:
            return text
    deltas: list[str] = []
    for event in events:
        if event.event_type != "runtime.output.delta":
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        text = payload.get("text")
        if isinstance(text, str) and text:
            deltas.append(text)
    return "".join(deltas).strip()


def _safe_transcript_item(
    *,
    kind: str,
    role: str,
    text: str,
    created_at,
    status: str,
    source: str,
    sequence: int = 0,
) -> dict:
    safe_text, truncated = _bounded_transcript_text(text)
    return {
        "message_id": "",
        "kind": kind,
        "role": role,
        "text": safe_text,
        "status": status,
        "created_at": created_at,
        "truncated": truncated,
        "_sequence": sequence,
        "_source": source,
    }


def _bounded_transcript_text(value: str, *, limit: int = 6000) -> tuple[str, bool]:
    text = _text(value)
    if len(text) <= limit:
        return text, False
    return f"{text[:limit].rstrip()}\n[truncated]", True


def _artifact_ref_label(ref: dict) -> str:
    for key in ("label", "name", "filename", "workspace_relative_path", "relative_path", "file_id"):
        value = _text(ref.get(key))
        if value:
            return value
    return ""


def _execute_run(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    run,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
) -> list[bytes]:
    try:
        root_session = state.runtime_store.get_session(run.root_runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "root_runtime_session_not_found"}, status="404 Not Found")
    authorize_inter_agent_root_session_use(
        workspace_store=state.workspace_store,
        user=context.user,
        context_workspace_id=context.workspace_id,
        caller_kind="http",
        root_session=root_session,
        user_id=context.user.user_id,
        platform_role=context.user.platform_role,
    )
    if _run_has_child_runtime_participants(state, run):
        authorize_inter_agent_participant_spawn(
            workspace_store=state.workspace_store,
            runtime_store=state.runtime_store,
            user=context.user,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            owner_user_id=None,
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
        )
    if isinstance(body.get("controlled_participants"), dict):
        raise AuthorizationError("inter_agent_controlled_participants_forbidden")
    input_text = _text(body.get("input_text")) or _text(body.get("message"))
    client_message_id = _text(body.get("client_message_id")) or None
    participant_inputs = body.get("participant_inputs") if isinstance(body.get("participant_inputs"), dict) else None
    project_summaries = _bool(body.get("project_summaries"), default=True)
    async_requested = _bool(body.get("async"), default=False)
    root_projection = None
    if client_message_id:
        root_projection = _record_root_inter_agent_turn_queued(
            state,
            context,
            run,
            body,
            input_text=input_text,
            client_message_id=client_message_id,
            start_path=start_path,
        )
    if async_requested:
        run = service.mark_run_planning(workspace_id=context.workspace_id, run_id=run.run_id)
        payload = run_detail_payload(state.inter_agent_store, run)
        if root_projection is not None:
            payload["root_runtime_turn"] = inter_agent_payload(root_projection["turn"])
            payload["root_runtime_events"] = inter_agent_payload(root_projection["events"])
        _start_inter_agent_execution_worker(
            state,
            service,
            workspace_id=context.workspace_id,
            run_id=run.run_id,
            input_text=input_text,
            participant_inputs=participant_inputs,
            project_summaries=project_summaries,
            root_projection=root_projection,
        )
        return json_response(start_response, payload, status="202 Accepted")
    result, root_projection = _execute_inter_agent_run_with_root_projection(
        state,
        service,
        workspace_id=context.workspace_id,
        run_id=run.run_id,
        input_text=input_text,
        participant_inputs=participant_inputs,
        project_summaries=project_summaries,
        root_projection=root_projection,
        async_runtime_turns=False,
    )
    payload = execution_result_payload(state.inter_agent_store, result)
    if root_projection is not None:
        payload["root_runtime_turn"] = inter_agent_payload(root_projection["turn"])
        payload["root_runtime_events"] = inter_agent_payload(root_projection["events"] + result.root_runtime_events)
    return json_response(start_response, payload)


def _materialize_agent_snapshots_for_payload(
    state: PlatformState,
    context: RequestSession,
    root_session,
    body: dict,
    *,
    start_path,
) -> tuple[dict, bool]:
    participants = body.get("participants") if isinstance(body.get("participants"), list) else []
    if not any(
        isinstance(participant, dict) and isinstance(participant.get("agent_snapshot"), dict)
        for participant in participants
    ):
        return body, False
    provider_app_id = _text(root_session.source_app_id)
    provider_ids = _chat_agent_snapshot_provider_ids(state, context, start_path=start_path)
    if not provider_app_id or provider_app_id not in provider_ids:
        raise InterAgentValidationError("agent_snapshot requires Chat's selected agent provider.")
    active_app_context = _trusted_active_app_context_from_root_session(
        state,
        context,
        root_session,
        start_path=start_path,
    )
    materialized_participants: list[object] = []
    for participant in participants:
        if not isinstance(participant, dict) or not isinstance(participant.get("agent_snapshot"), dict):
            materialized_participants.append(participant)
            continue
        materialized_snapshot = _materialize_agent_snapshot_from_provider(
            state,
            context,
            participant=participant,
            snapshot=participant["agent_snapshot"],
            provider_app_id=provider_app_id,
            active_app_context=active_app_context,
            start_path=start_path,
        )
        materialized_participant = dict(participant)
        materialized_participant["agent_snapshot"] = materialized_snapshot
        materialized_participant["agent_type_id"] = materialized_snapshot["agent_type_id"]
        materialized_participant["label"] = materialized_snapshot["label"]
        materialized_participants.append(materialized_participant)
    return {**body, "participants": materialized_participants}, True


def _materialize_agent_snapshot_from_provider(
    state: PlatformState,
    context: RequestSession,
    *,
    participant: dict,
    snapshot: dict,
    provider_app_id: str,
    active_app_context: dict[str, str] | None,
    start_path,
) -> dict:
    requested_agent_type_id = _requested_agent_type_id_for_snapshot(participant, snapshot)
    explicit_provider_id = _text(snapshot.get("provider_id"))
    if explicit_provider_id and explicit_provider_id != provider_app_id:
        raise InterAgentValidationError(
            "agent_snapshot.provider_id does not match Chat's selected agent provider."
        )
    definition_payload = _invoke_chat_agent_provider_backend(
        state,
        context,
        provider_app_id=provider_app_id,
        dependency_alias="agent-catalog",
        body={"action": "get_agent_definition", "id": requested_agent_type_id},
        start_path=start_path,
    )
    agent_definition = (
        definition_payload.get("agent_definition")
        if isinstance(definition_payload.get("agent_definition"), dict)
        else None
    )
    if not bool(definition_payload.get("exists")) or agent_definition is None:
        raise InterAgentValidationError(
            f"agent_snapshot.agent_type_id `{requested_agent_type_id}` was not found."
        )
    definition_agent_type_id = _text(agent_definition.get("id"))
    if definition_agent_type_id != requested_agent_type_id:
        raise InterAgentValidationError("Agent provider returned a mismatched agent definition.")
    if agent_definition.get("enabled") is False:
        raise InterAgentValidationError(
            f"agent_snapshot.agent_type_id `{requested_agent_type_id}` is disabled."
        )
    prompt_payload = _invoke_chat_agent_provider_backend(
        state,
        context,
        provider_app_id=provider_app_id,
        dependency_alias="agent-prompt-materializer",
        body={"action": "preview_prompt", "agent_type_id": requested_agent_type_id},
        start_path=start_path,
    )
    system_prompt = _system_prompt_with_active_app_context(
        _text(prompt_payload.get("rendered")),
        active_app_context,
    )
    return {
        "agent_type_id": requested_agent_type_id,
        "label": _text(agent_definition.get("name")) or requested_agent_type_id,
        "system_prompt": system_prompt,
        "skill_ids": _string_items(agent_definition.get("skill_ids")),
        "skill_catalog_app_id": _materialized_agent_snapshot_skill_catalog(
            state,
            context,
            provider_app_id=provider_app_id,
            provider_skill_catalog_app_id=(
                _text(agent_definition.get("skill_catalog_app_id"))
                or _text(prompt_payload.get("skill_catalog_app_id"))
            ),
            snapshot=snapshot,
            start_path=start_path,
        ),
        "provider_id": provider_app_id,
        "revision_id": (
            _text(agent_definition.get("revision_id"))
            or _text(agent_definition.get("updated_at"))
            or None
        ),
        "metadata": {
            "source": "chat_dependency_backend",
            "definition_updated_at": _text(agent_definition.get("updated_at")),
        },
    }


def _requested_agent_type_id_for_snapshot(participant: dict, snapshot: dict) -> str:
    participant_agent_type_id = _text(participant.get("agent_type_id"))
    snapshot_agent_type_id = _text(snapshot.get("agent_type_id"))
    if (
        participant_agent_type_id
        and snapshot_agent_type_id
        and participant_agent_type_id != snapshot_agent_type_id
    ):
        raise InterAgentValidationError("agent_snapshot.agent_type_id must match participant.agent_type_id.")
    requested_agent_type_id = snapshot_agent_type_id or participant_agent_type_id
    if not requested_agent_type_id:
        raise InterAgentValidationError("agent_snapshot.agent_type_id is required.")
    return requested_agent_type_id


def _trusted_active_app_context_from_root_session(
    state: PlatformState,
    context: RequestSession,
    root_session,
    *,
    start_path,
) -> dict[str, str] | None:
    active_app_id = _active_app_id_from_system_prompt(_text(root_session.system_prompt))
    if not active_app_id or active_app_id == CHAT_APP_ID:
        return None
    app_item = next(
        (
            item
            for item in enabled_app_items(
                state,
                workspace_id=context.workspace_id,
                start_path=start_path,
                user=context.user,
            )
            if _text(item.get("app_id")) == active_app_id or _text(item.get("mount_app_id")) == active_app_id
        ),
        None,
    )
    if app_item is None:
        return None
    app_id = _text(app_item.get("app_id"))
    if not app_id or app_id == CHAT_APP_ID:
        return None
    return {
        "app_id": app_id,
        "name": _context_line_value(app_item.get("name")) or app_id,
        "description": _context_line_value(app_item.get("description")),
    }


def _active_app_id_from_system_prompt(system_prompt: str) -> str:
    block = _final_active_app_context_block(system_prompt)
    if not block:
        return ""
    fields: dict[str, str] = {}
    for line in block.splitlines()[1:]:
        normalized = line.strip()
        if not normalized:
            continue
        if not normalized.startswith("- "):
            return ""
        key, separator, value = normalized[2:].partition(":")
        if not separator:
            return ""
        normalized_key = key.strip()
        if normalized_key not in ACTIVE_APP_CONTEXT_KEYS:
            return ""
        fields[normalized_key] = value.strip()
    return fields.get("active_app_id", "")


def _final_active_app_context_block(system_prompt: str) -> str:
    prompt = _text(system_prompt)
    if not prompt:
        return ""
    marker = f"\n\n{ACTIVE_APP_CONTEXT_HEADER}"
    marker_index = prompt.rfind(marker)
    if marker_index >= 0:
        return prompt[marker_index + 2 :]
    if prompt.startswith(ACTIVE_APP_CONTEXT_HEADER):
        return prompt
    return ""


def _prompt_without_final_active_app_context_block(system_prompt: str) -> str:
    prompt = _text(system_prompt)
    if not prompt:
        return ""
    marker = f"\n\n{ACTIVE_APP_CONTEXT_HEADER}"
    marker_index = prompt.rfind(marker)
    if marker_index >= 0:
        return prompt[:marker_index]
    if prompt.startswith(ACTIVE_APP_CONTEXT_HEADER):
        return ""
    return prompt


def _system_prompt_with_active_app_context(base_prompt: str, active_app_context: dict[str, str] | None) -> str:
    if not active_app_context:
        return base_prompt
    active_app_id = active_app_context["app_id"]
    prompt_base = _prompt_without_final_active_app_context_block(base_prompt)
    lines = [
        ACTIVE_APP_CONTEXT_HEADER,
        f"- active_app_id: {active_app_id}",
        f"- active_app_name: {active_app_context['name']}",
    ]
    description = _text(active_app_context.get("description"))
    if description:
        lines.append(f"- active_app_description: {description}")
    return "\n\n".join(part for part in (prompt_base.strip(), "\n".join(lines)) if part)


def _context_line_value(value) -> str:
    return " ".join(_text(value).split())


def _invoke_chat_agent_provider_backend(
    state: PlatformState,
    context: RequestSession,
    *,
    provider_app_id: str,
    dependency_alias: str,
    body: dict,
    start_path,
) -> dict:
    try:
        result = invoke_dependency_backend_request(
            state,
            workspace_id=context.workspace_id,
            app_id=CHAT_APP_ID,
            dependency_alias=dependency_alias,
            provider_app_id=provider_app_id,
            body=body,
            user=context.user,
            start_path=start_path,
        )
    except AppHostingError as error:
        raise InterAgentValidationError(str(error)) from error
    payload = result.get("json") if isinstance(result.get("json"), dict) else result
    if not isinstance(payload, dict):
        raise InterAgentValidationError(f"Dependency alias `{dependency_alias}` returned an invalid response.")
    return payload


def _materialized_agent_snapshot_skill_catalog(
    state: PlatformState,
    context: RequestSession,
    *,
    provider_app_id: str,
    provider_skill_catalog_app_id: str,
    snapshot: dict,
    start_path,
) -> str:
    explicit_skill_catalog_app_id = _text(snapshot.get("skill_catalog_app_id"))
    if explicit_skill_catalog_app_id:
        _validate_agent_snapshot_skill_catalog(
            state,
            context,
            explicit_skill_catalog_app_id,
            start_path=start_path,
        )
    materialized_skill_catalog_app_id = _text(provider_skill_catalog_app_id)
    if materialized_skill_catalog_app_id:
        _validate_agent_snapshot_skill_catalog(
            state,
            context,
            materialized_skill_catalog_app_id,
            start_path=start_path,
        )
    selected_skill_catalog_app_id = ""
    try:
        selected_skill_catalog_app_id = _text(
            selected_runtime_skill_catalog_app_id_for_source_app(
                state.app_store,
                workspace_id=context.workspace_id,
                source_app_id=provider_app_id,
                user=context.user,
                workspace_store=state.workspace_store,
                start_path=start_path,
                allow_missing_source_app=True,
            )
        )
    except AppHostingError as error:
        raise InterAgentValidationError(str(error)) from error
    if (
        materialized_skill_catalog_app_id
        and selected_skill_catalog_app_id
        and materialized_skill_catalog_app_id != selected_skill_catalog_app_id
    ):
        raise InterAgentValidationError(
            "Agent provider skill catalog does not match the selected provider skill catalog."
        )
    if (
        materialized_skill_catalog_app_id
        and explicit_skill_catalog_app_id
        and materialized_skill_catalog_app_id != explicit_skill_catalog_app_id
    ):
        raise InterAgentValidationError(
            "agent_snapshot.skill_catalog_app_id does not match the materialized provider skill catalog."
        )
    if (
        selected_skill_catalog_app_id
        and explicit_skill_catalog_app_id
        and selected_skill_catalog_app_id != explicit_skill_catalog_app_id
    ):
        raise InterAgentValidationError(
            "agent_snapshot.skill_catalog_app_id does not match the selected provider skill catalog."
        )
    if materialized_skill_catalog_app_id:
        return materialized_skill_catalog_app_id
    if selected_skill_catalog_app_id:
        return selected_skill_catalog_app_id
    raise InterAgentValidationError(
        "Agent provider must materialize or select a runtime skill catalog."
    )


def _chat_agent_snapshot_provider_ids(
    state: PlatformState,
    context: RequestSession,
    *,
    start_path,
) -> set[str]:
    try:
        dependencies = resolve_app_dependencies(
            state.app_store,
            workspace_id=context.workspace_id,
            consumer_app_id=CHAT_APP_ID,
            user=context.user,
            workspace_store=state.workspace_store,
            start_path=start_path,
        )
    except AppHostingError as error:
        raise InterAgentValidationError(str(error)) from error
    dependency_by_alias = {
        str(item.get("alias") or ""): item
        for item in dependencies.get("dependencies", [])
        if isinstance(item, dict)
    }
    selected_by_alias = [
        _dependency_selected_or_automatic_backend_provider_ids(dependency_by_alias.get(alias))
        for alias in CHAT_AGENT_PROVIDER_ALIASES
    ]
    if len(selected_by_alias) != len(CHAT_AGENT_PROVIDER_ALIASES) or any(not ids for ids in selected_by_alias):
        return set()
    shared = set(selected_by_alias[0])
    for ids in selected_by_alias[1:]:
        shared.intersection_update(ids)
    return shared


def _dependency_selected_or_automatic_backend_provider_ids(dependency: dict | None) -> list[str]:
    if dependency is None:
        return []
    backend_candidate_ids = _dependency_backend_candidate_ids(dependency)
    dependency_status = _text(dependency.get("status"))
    selected = [
        app_id
        for app_id in _string_items(dependency.get("selected_provider_app_ids"))
        if app_id in backend_candidate_ids
    ]
    if selected:
        return selected if dependency_status == "resolved" else []
    if (
        dependency_status == "optional_unset"
        and dependency.get("cardinality") == "one"
        and not _string_items(dependency.get("stale_provider_app_ids"))
        and not _text(dependency.get("blocked_reason"))
    ):
        return backend_candidate_ids
    return []


def _dependency_backend_candidate_ids(dependency: dict) -> list[str]:
    candidates = dependency.get("candidates") if isinstance(dependency.get("candidates"), list) else []
    ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        surfaces = candidate.get("surfaces") if isinstance(candidate.get("surfaces"), list) else []
        app_id = _text(candidate.get("app_id"))
        if app_id and "backend" in {str(surface) for surface in surfaces}:
            ids.append(app_id)
    return ids


def _validate_agent_snapshot_skill_catalog(
    state: PlatformState,
    context: RequestSession,
    skill_catalog_app_id: str,
    *,
    start_path,
) -> None:
    normalized = _text(skill_catalog_app_id)
    if not normalized:
        raise InterAgentValidationError("agent_snapshot.skill_catalog_app_id is required.")
    try:
        validate_runtime_skill_catalog_provider_app_id(
            state.app_store,
            workspace_id=context.workspace_id,
            provider_app_id=normalized,
            user=context.user,
            workspace_store=state.workspace_store,
            start_path=start_path,
        )
    except AppHostingError as error:
        raise InterAgentValidationError(str(error)) from error


def _start_inter_agent_execution_worker(
    state: PlatformState,
    service: InterAgentService,
    *,
    workspace_id: str,
    run_id: str,
    input_text: str,
    participant_inputs: dict[str, object] | None,
    project_summaries: bool,
    root_projection: dict[str, object] | None,
) -> None:
    def worker() -> None:
        try:
            _execute_inter_agent_run_with_root_projection(
                state,
                service,
                workspace_id=workspace_id,
                run_id=run_id,
                input_text=input_text,
                participant_inputs=participant_inputs,
                project_summaries=project_summaries,
                root_projection=root_projection,
                async_runtime_turns=True,
            )
        except Exception:
            return

    Thread(target=worker, name=f"maverick-inter-agent-run-{run_id}", daemon=True).start()


def _execute_inter_agent_run_with_root_projection(
    state: PlatformState,
    service: InterAgentService,
    *,
    workspace_id: str,
    run_id: str,
    input_text: str,
    participant_inputs: dict[str, object] | None,
    project_summaries: bool,
    root_projection: dict[str, object] | None,
    async_runtime_turns: bool,
):
    try:
        if root_projection is not None:
            _mark_root_inter_agent_turn_active(state, workspace_id=workspace_id, root_projection=root_projection)
        result = execute_inter_agent_run(
            service,
            state,
            workspace_id=workspace_id,
            run_id=run_id,
            input_text=input_text,
            participant_inputs=participant_inputs,
            controlled_participants=None,
            allow_synthetic_participants=False,
            project_summaries=project_summaries,
            async_runtime_turns=async_runtime_turns,
        )
        if root_projection is not None:
            _mark_root_inter_agent_turn_completed(
                state,
                workspace_id=workspace_id,
                root_projection=root_projection,
                status=result.run.status,
                final_answer=result.final_answer,
            )
    except Exception as error:
        if root_projection is not None:
            _mark_root_inter_agent_turn_failed(state, workspace_id=workspace_id, root_projection=root_projection, error=error)
        raise
    return result, root_projection


def _mark_root_inter_agent_turn_active(
    state: PlatformState,
    *,
    workspace_id: str,
    root_projection: dict[str, object],
) -> None:
    turn = root_projection["turn"]
    turn_id = turn.turn_id
    current = state.runtime_store.get_turn(turn_id)
    if current.status == "queued":
        current = transition_runtime_turn(
            state.runtime_store,
            turn_id=turn_id,
            target_status="active",
        )
    if current.status != "active":
        raise InterAgentOperationError("Inter-agent root turn is not runnable.")
    root_projection["turn"] = current
    events = root_projection["events"]
    events.append(
        record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=current.session_id,
            turn_id=current.turn_id,
            plane="turn",
            event_type="runtime.turn.started",
            payload={"inter_agent_run_id": _root_projection_run_id(root_projection)},
            event_bus=state.runtime_event_bus,
        )
    )
    set_thread_availability(
        state,
        workspace_id=workspace_id,
        runtime_session_id=current.session_id,
        availability="active",
    )


def _mark_root_inter_agent_turn_completed(
    state: PlatformState,
    *,
    workspace_id: str,
    root_projection: dict[str, object],
    status: str,
    final_answer: str,
) -> None:
    turn = root_projection["turn"]
    current = state.runtime_store.get_turn(turn.turn_id)
    if current.status in {"completed", "failed", "cancelled", "timed-out"}:
        root_projection["turn"] = current
        set_thread_availability(
            state,
            workspace_id=workspace_id,
            runtime_session_id=current.session_id,
            availability="free",
        )
        return
    if status == "cancelled":
        cancelled_turn = transition_runtime_turn(
            state.runtime_store,
            turn_id=current.turn_id,
            target_status="cancelled",
            failure_reason="Inter-agent run cancelled.",
        )
        root_projection["turn"] = cancelled_turn
        cancelled_event = record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=cancelled_turn.session_id,
            turn_id=cancelled_turn.turn_id,
            plane="turn",
            event_type="runtime.turn.cancelled",
            payload={
                "inter_agent_run_id": _root_projection_run_id(root_projection),
                "reason": "inter_agent_run_cancelled",
            },
            event_bus=state.runtime_event_bus,
        )
        root_projection["events"].append(cancelled_event)
        set_thread_availability(
            state,
            workspace_id=workspace_id,
            runtime_session_id=cancelled_turn.session_id,
            availability="free",
            now=cancelled_event.created_at,
        )
        return
    answer = _text(final_answer)
    if answer:
        output_event = record_runtime_event(
            state.runtime_store,
            event_id=str(uuid4()),
            session_id=current.session_id,
            turn_id=current.turn_id,
            plane="turn",
            event_type="runtime.output.final",
            payload={
                "inter_agent_run_id": _root_projection_run_id(root_projection),
                "text": answer,
                "complete_text": answer,
            },
            event_bus=state.runtime_event_bus,
        )
        root_projection["events"].append(output_event)
    completed_turn = transition_runtime_turn(
        state.runtime_store,
        turn_id=current.turn_id,
        target_status="completed",
    )
    root_projection["turn"] = completed_turn
    completed_event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=completed_turn.session_id,
        turn_id=completed_turn.turn_id,
        plane="turn",
        event_type="runtime.turn.completed",
        payload={"inter_agent_run_id": _root_projection_run_id(root_projection), "status": status},
        event_bus=state.runtime_event_bus,
    )
    root_projection["events"].append(completed_event)
    mark_thread_response_completed(
        state,
        workspace_id=workspace_id,
        runtime_session_id=completed_turn.session_id,
        turn_id=completed_turn.turn_id,
        now=completed_event.created_at,
    )


def _mark_root_inter_agent_turn_failed(
    state: PlatformState,
    *,
    workspace_id: str,
    root_projection: dict[str, object],
    error: Exception,
) -> None:
    turn = root_projection["turn"]
    current = state.runtime_store.get_turn(turn.turn_id)
    if current.status in {"completed", "failed", "cancelled", "timed-out"}:
        root_projection["turn"] = current
        set_thread_availability(
            state,
            workspace_id=workspace_id,
            runtime_session_id=current.session_id,
            availability="free",
        )
        return
    failed_turn = transition_runtime_turn(
        state.runtime_store,
        turn_id=current.turn_id,
        target_status="failed",
        failure_reason=str(error),
    )
    root_projection["turn"] = failed_turn
    failed_event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=failed_turn.session_id,
        turn_id=failed_turn.turn_id,
        plane="turn",
        event_type="runtime.turn.failed",
        payload={"inter_agent_run_id": _root_projection_run_id(root_projection), "error": str(error)},
        event_bus=state.runtime_event_bus,
    )
    root_projection["events"].append(failed_event)
    set_thread_availability(
        state,
        workspace_id=workspace_id,
        runtime_session_id=failed_turn.session_id,
        availability="free",
        now=failed_event.created_at,
    )


def _root_projection_run_id(root_projection: dict[str, object]) -> str:
    events = root_projection.get("events") if isinstance(root_projection.get("events"), list) else []
    for event in events:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            run_id = _text(payload.get("inter_agent_run_id"))
            if run_id:
                return run_id
    return ""


def _approval_resolver_role_ids(state: PlatformState, context: RequestSession, run) -> list[str]:
    roles: list[str] = []
    platform_role = _text(context.user.platform_role)
    if platform_role:
        roles.extend([platform_role, f"platform:{platform_role}"])
    try:
        membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=run.workspace_id)
    except WorkspaceMembershipError:
        membership = None
    if membership is not None and membership.status == "active":
        role = _text(membership.role)
        if role:
            roles.extend([role, f"workspace:{role}"])
    return roles


def _record_root_inter_agent_turn_queued(
    state: PlatformState,
    context: RequestSession,
    run,
    body: dict,
    *,
    input_text: str,
    client_message_id: str,
    start_path,
) -> dict[str, object]:
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    attachment_items = [_serializable_attachment_item(item) for item in attachments if isinstance(item, dict)]
    app_references = body.get("app_references") if isinstance(body.get("app_references"), list) else []
    app_reference_items = materialize_runtime_app_references(
        state,
        context=context,
        references=[item for item in app_references if isinstance(item, dict)],
        start_path=start_path,
    )
    turn = queue_runtime_turn(
        state.runtime_store,
        turn_id=str(uuid4()),
        session_id=run.root_runtime_session_id,
        input_text=input_text,
    )
    payload: dict[str, object] = {
        "input_text": input_text,
        "client_message_id": client_message_id,
        "inter_agent_run_id": run.run_id,
    }
    if attachment_items:
        payload["attachments"] = attachment_items
    if app_reference_items:
        payload["app_references"] = app_reference_items
    event = record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=run.root_runtime_session_id,
        turn_id=turn.turn_id,
        plane="turn",
        event_type="runtime.turn.queued",
        payload=payload,
        event_bus=state.runtime_event_bus,
    )
    title_hash = thread_title_input_hash(
        input_text,
        attachments=attachment_items,
        app_references=app_reference_items,
    )
    thread = mark_thread_user_message_queued(
        state,
        workspace_id=context.workspace_id,
        runtime_session_id=run.root_runtime_session_id,
        input_text=input_text,
        attachments=attachment_items,
        app_references=app_reference_items,
        title_generation_input_hash=title_hash,
        now=event.created_at,
    )
    if thread is not None:
        schedule_runtime_thread_title_generation(
            state,
            thread=thread,
            input_text=input_text,
            attachments=attachment_items,
            app_references=app_reference_items,
        )
    return {"turn": turn, "events": [event]}


def _serializable_attachment_item(item: dict) -> dict[str, object]:
    return {str(key): value for key, value in item.items() if key != "objectUrl"}


def _resolve_approval(
    state: PlatformState,
    context: RequestSession,
    service: InterAgentService,
    approval_id: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    approval = state.inter_agent_store.get_approval(approval_id, workspace_id=context.workspace_id)
    run = state.inter_agent_store.get_run(approval.run_id, workspace_id=context.workspace_id)
    authorize_inter_agent_approval_resolution(
        workspace_store=state.workspace_store,
        context_workspace_id=context.workspace_id,
        caller_kind="http",
        run=run,
        approval=approval,
        user_id=context.user.user_id,
        platform_role=context.user.platform_role,
    )
    resolved = service.resolve_approval(
        workspace_id=context.workspace_id,
        approval_id=approval.approval_id,
        approved=_bool(body.get("approved"), default=False),
        resolved_by_user_id=context.user.user_id,
        resolved_by_role_ids=_approval_resolver_role_ids(state, context, run),
        resolution_reason=_text(body.get("reason")) or None,
    )
    return json_response(start_response, {"approval": inter_agent_payload(resolved)})


def _can_view_run_detail(state: PlatformState, context: RequestSession, run) -> bool:
    try:
        authorize_inter_agent_run_sensitive_view(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
    except AuthorizationError:
        return False
    return True


def _root_session_for_run(state: PlatformState, run):
    try:
        return state.runtime_store.get_session(run.root_runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return None


def _run_has_child_runtime_participants(state: PlatformState, run) -> bool:
    return any(
        participant.execution_mode == "child_runtime_session"
        for participant in state.inter_agent_store.list_participants(run.run_id, workspace_id=run.workspace_id)
    )


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


def _text(value) -> str:
    return str(value or "").strip()


def _string_items(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _bool(value, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)
