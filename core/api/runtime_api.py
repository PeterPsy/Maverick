"""Generic runtime HTTP API for hosted Maverick apps."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import parse_qs
from uuid import uuid4

from core.api.app_reference_payloads import materialize_runtime_app_references
from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.provider_api import workspace_provider_status
from core.api.runtime_cleanup import cleanup_runtime_session
from core.api.session_api import RequestSession, require_session
from core.apps.errors import AppHostingError
from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.authorization.errors import AuthorizationError
from core.authorization.service import authorize_runtime_session_create, require_runtime_session_operation
from core.providers.errors import ProviderError
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeThreadNotFoundError, RuntimeTurnNotFoundError
from core.runtime.runtime_threads import (
    clear_runtime_threads_complete,
    create_runtime_thread,
    delete_runtime_thread_complete,
    ensure_runtime_threads_for_sessions,
    find_runtime_thread_by_session,
    mark_runtime_thread_completed_response_read,
    thread_payload,
    update_runtime_thread,
)
from core.runtime.thread_catalog_events import mark_thread_user_message_queued, set_thread_availability
from core.runtime.thread_title_jobs import schedule_runtime_thread_title_generation, thread_title_input_hash
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE
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
from core.runtime.turn_submission import (
    interrupt_runtime_provider_turn,
    release_idle_runtime_processes,
    submit_runtime_turn,
    submit_runtime_turn_async,
)
from core.skills.runtime_catalog import runtime_skill_catalog_app_id_for_request


def _session_payload(session: RuntimeSessionRecord, *, provider_id: str | None = None) -> dict[str, object]:
    payload = asdict(session)
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


def _threads_payload(state: PlatformState, *, workspace_id: str, viewer_user_id: str | None = None) -> dict[str, object]:
    sessions = state.runtime_store.list_sessions(workspace_id)
    threads = ensure_runtime_threads_for_sessions(
        state.runtime_store,
        workspace_id=workspace_id,
        sessions=sessions,
    )
    return {"threads": [thread_payload(thread, viewer_user_id=viewer_user_id) for thread in threads]}


def _publish_thread_change(
    state: PlatformState,
    *,
    workspace_id: str,
    action: str,
    thread=None,
    deleted_thread_ids: list[str] | None = None,
    deleted_runtime_session_ids: list[str] | None = None,
) -> None:
    payload = {
        "action": action,
        **_threads_payload(state, workspace_id=workspace_id),
    }
    if thread is not None:
        payload["thread"] = thread_payload(thread)
        payload["thread_id"] = thread.thread_id
    if deleted_thread_ids is not None:
        payload["deleted_thread_ids"] = deleted_thread_ids
    if deleted_runtime_session_ids is not None:
        payload["deleted_runtime_session_ids"] = deleted_runtime_session_ids
    state.runtime_thread_event_bus.publish(workspace_id=workspace_id, event=payload)


def _list_session_payloads(state: PlatformState, *, workspace_id: str, start_path) -> list[dict[str, object]]:
    sessions = state.runtime_store.list_sessions(workspace_id)
    reconciled = [_reconciled_session(state, session, start_path=start_path) for session in sessions]
    return [_session_payload(session, provider_id=_resolved_provider_id(state, session)) for session in reconciled]


def _resolved_provider_id(state: PlatformState, session: RuntimeSessionRecord) -> str | None:
    if session.provider_id:
        return session.provider_id
    try:
        provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    except ProviderError:
        return None
    return provider.provider_id


def _provider_unavailable_response(state: PlatformState, workspace_id: str, error: Exception) -> dict[str, object]:
    status = workspace_provider_status(state, workspace_id=workspace_id)
    return {
        "error": "provider_unavailable",
        "blocked_reason": status.get("blocked_reason") or "provider_unavailable",
        "detail": str(error),
        "provider_status": status,
    }


def _create_session(state: PlatformState, context: RequestSession, body: dict, *, agent_id: str, start_path) -> RuntimeSessionRecord:
    authorize_runtime_session_create(
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        user=context.user,
        workspace_id=context.workspace_id,
    )
    source_app_id = str(body.get("source_app_id") or "").strip() or None
    session = create_runtime_session(
        state.runtime_store,
        session_id=str(uuid4()),
        workspace_id=context.workspace_id,
        agent_id=agent_id,
        requested_mode=body.get("requested_mode"),
        system_prompt=str(body.get("system_prompt") or "").strip() or None,
        skill_ids=body.get("skill_ids") if isinstance(body.get("skill_ids"), list) else [],
        skill_catalog_app_id=runtime_skill_catalog_app_id_for_request(
            state.app_store,
            workspace_id=context.workspace_id,
            source_app_id=source_app_id,
            explicit_app_id=str(body.get("skill_catalog_app_id") or "").strip() or None,
            user=context.user,
            workspace_store=state.workspace_store,
            start_path=start_path,
            allow_missing_source_app=True,
        ),
        source_app_id=source_app_id,
        owner_user_id=context.user.user_id,
        created_by_user_id=context.user.user_id,
        grants=[],
        governance=state.workspace_store.get_governance(context.workspace_id),
        platform_allows_full_access=context.workspace_id == "default",
        start_path=start_path,
        observability_store=state.observability_store,
    )
    session = transition_runtime_session(
        state.runtime_store,
        session_id=session.session_id,
        target_status="running",
        observability_store=state.observability_store,
        start_path=start_path,
    )
    requested_title = str(body.get("title") or "").strip()
    thread_title = requested_title or DEFAULT_THREAD_TITLE
    thread = create_runtime_thread(
        state.runtime_store,
        workspace_id=context.workspace_id,
        thread_id=session.session_id,
        runtime_session_id=session.session_id,
        title=thread_title,
        title_source="placeholder" if not requested_title or requested_title == DEFAULT_THREAD_TITLE else "manual",
        agent_label=session.agent_id,
        agent_type_id=str(body.get("agent_type_id") or "").strip(),
        agent_role_id=str(body.get("agent_role_id") or "").strip(),
        source_app_id=session.source_app_id or session.agent_id,
        system_prompt=session.system_prompt or "",
        project_id=str(body.get("project_id") or "").strip() or None,
        now=session.started_at or session.updated_at,
    )
    _publish_thread_change(state, workspace_id=context.workspace_id, action="created", thread=thread)
    return session


def _handle_session_collection(state: PlatformState, context: RequestSession, method: str, body: dict, start_response: StartResponse, *, start_path):
    if method == "GET":
        return json_response(start_response, {"items": _list_session_payloads(state, workspace_id=context.workspace_id, start_path=start_path)})
    if method == "POST":
        agent_id = str(body.get("agent_id") or "").strip()
        if not agent_id:
            return json_response(start_response, {"error": "agent_id_required"}, status="400 Bad Request")
        try:
            session = _create_session(state, context, body, agent_id=agent_id, start_path=start_path)
        except AuthorizationError as error:
            status = "429 Too Many Requests" if error.reason == "max_agent_instances_reached" else "403 Forbidden"
            return json_response(start_response, {"error": error.reason}, status=status)
        except AppHostingError as error:
            return json_response(
                start_response,
                {"error": "runtime_skill_catalog_unavailable", "detail": str(error)},
                status="400 Bad Request",
            )
        if _runtime_turn_requested(body):
            return _submit_runtime_turn_response(state, context, session, body, start_response, start_path=start_path)
        return json_response(start_response, _session_payload(session, provider_id=_resolved_provider_id(state, session)), status="201 Created")
    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _handle_thread_collection(state: PlatformState, context: RequestSession, method: str, body: dict, start_response: StartResponse):
    if method == "GET":
        return json_response(start_response, _threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id))
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    runtime_session_id = str(body.get("runtime_session_id") or "").strip()
    if not runtime_session_id:
        return json_response(start_response, {"error": "runtime_session_id_required"}, status="400 Bad Request")
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    existing = None
    try:
        existing = state.runtime_store.get_thread(session.session_id)
    except RuntimeThreadNotFoundError:
        existing = None
    requested_title = str(body.get("title") or "").strip()
    title_source = ""
    if requested_title and existing is None:
        title_source = "placeholder" if requested_title == DEFAULT_THREAD_TITLE else "manual"
    elif existing is None:
        requested_title = DEFAULT_THREAD_TITLE
        title_source = "placeholder"
    thread = create_runtime_thread(
        state.runtime_store,
        workspace_id=context.workspace_id,
        thread_id=session.session_id,
        runtime_session_id=session.session_id,
        title=requested_title,
        title_source=title_source,
        agent_label=str(body.get("agent_label") or "").strip() or session.agent_id,
        agent_type_id=str(body.get("agent_type_id") or "").strip(),
        agent_role_id=str(body.get("agent_role_id") or "").strip(),
        source_app_id=str(body.get("source_app_id") or "").strip() or session.source_app_id or session.agent_id,
        system_prompt=str(body.get("system_prompt") or "").strip() or session.system_prompt or "",
        project_id=str(body.get("project_id") or "").strip() or None,
        now=session.started_at or session.updated_at,
    )
    _publish_thread_change(state, workspace_id=context.workspace_id, action="updated" if existing else "created", thread=thread)
    return json_response(
        start_response,
        {"thread": thread_payload(thread, viewer_user_id=context.user.user_id), **_threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id)},
        status="201 Created",
    )


def _thread_cleanup_forbidden_reason(state: PlatformState, context: RequestSession, *, runtime_session_id: str) -> str | None:
    if not runtime_session_id:
        return None
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return None
    if session.workspace_id != context.workspace_id:
        return "runtime_thread_not_found"
    try:
        require_runtime_session_operation(
            workspace_store=state.workspace_store,
            user=context.user,
            session=session,
            operation="cleanup",
        )
    except AuthorizationError as error:
        return error.reason
    return None


def _handle_thread_item(
    state: PlatformState,
    context: RequestSession,
    thread_id: str,
    method: str,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
):
    try:
        thread = state.runtime_store.get_thread(thread_id)
    except RuntimeThreadNotFoundError:
        try:
            session = state.runtime_store.get_session(thread_id)
        except RuntimeSessionNotFoundError:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if session.workspace_id != context.workspace_id:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        thread = create_runtime_thread(
            state.runtime_store,
            workspace_id=context.workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=DEFAULT_THREAD_TITLE,
            title_source="placeholder",
            agent_label=session.agent_id,
            source_app_id=session.source_app_id or session.agent_id,
            system_prompt=session.system_prompt or "",
            now=session.started_at or session.updated_at,
        )
        _publish_thread_change(state, workspace_id=context.workspace_id, action="created", thread=thread)
    if thread.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
    if method == "GET":
        return json_response(
            start_response,
            {"thread": thread_payload(thread, viewer_user_id=context.user.user_id), **_threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id)},
        )
    if method == "PATCH":
        updated = update_runtime_thread(
            state.runtime_store,
            thread_id=thread_id,
            workspace_id=context.workspace_id,
            updates=body,
        )
        if updated is None:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        _publish_thread_change(state, workspace_id=context.workspace_id, action="updated", thread=updated)
        return json_response(
            start_response,
            {"thread": thread_payload(updated, viewer_user_id=context.user.user_id), **_threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id)},
        )
    if method == "DELETE":
        forbidden_reason = _thread_cleanup_forbidden_reason(
            state,
            context,
            runtime_session_id=thread.runtime_session_id,
        )
        if forbidden_reason == "runtime_thread_not_found":
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if forbidden_reason is not None:
            return json_response(start_response, {"error": forbidden_reason}, status="403 Forbidden")
        reason = str(body.get("reason") or "runtime_thread_deleted").strip()

        def cleanup(session_id: str, cleanup_reason: str) -> dict[str, object]:
            return cleanup_runtime_session(state, session_id=session_id, reason=cleanup_reason, start_path=start_path, publish_thread_events=False)

        deleted, cleanup_result = delete_runtime_thread_complete(
            state.runtime_store,
            thread_id=thread_id,
            workspace_id=context.workspace_id,
            cleanup_runtime=cleanup,
            reason=reason,
        )
        if deleted is None:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        _publish_thread_change(
            state,
            workspace_id=context.workspace_id,
            action="deleted",
            deleted_thread_ids=[deleted.thread_id],
            deleted_runtime_session_ids=[deleted.runtime_session_id] if deleted.runtime_session_id else [],
        )
        payload = {
            **_threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id),
            "deleted_thread_id": deleted.thread_id,
            "deleted_runtime_session_id": deleted.runtime_session_id,
        }
        if cleanup_result is not None:
            payload["runtime_cleanup"] = cleanup_result
        return json_response(start_response, payload)
    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _handle_thread_read(
    state: PlatformState,
    context: RequestSession,
    thread_id: str,
    method: str,
    start_response: StartResponse,
) -> list[bytes]:
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    try:
        thread = state.runtime_store.get_thread(thread_id)
    except RuntimeThreadNotFoundError:
        try:
            session = state.runtime_store.get_session(thread_id)
        except RuntimeSessionNotFoundError:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if session.workspace_id != context.workspace_id:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        thread = create_runtime_thread(
            state.runtime_store,
            workspace_id=context.workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=DEFAULT_THREAD_TITLE,
            title_source="placeholder",
            agent_label=session.agent_id,
            source_app_id=session.source_app_id or session.agent_id,
            system_prompt=session.system_prompt or "",
            now=session.started_at or session.updated_at,
        )
        _publish_thread_change(state, workspace_id=context.workspace_id, action="created", thread=thread)
    if thread.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
    updated = mark_runtime_thread_completed_response_read(
        state.runtime_store,
        thread_id=thread.thread_id,
        workspace_id=context.workspace_id,
        user_id=context.user.user_id,
    )
    if updated is None:
        return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
    _publish_thread_change(state, workspace_id=context.workspace_id, action="updated", thread=updated)
    return json_response(
        start_response,
        {"thread": thread_payload(updated, viewer_user_id=context.user.user_id), **_threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id)},
    )


def _handle_thread_clear(
    state: PlatformState,
    context: RequestSession,
    method: str,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
):
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    threads = ensure_runtime_threads_for_sessions(
        state.runtime_store,
        workspace_id=context.workspace_id,
        sessions=state.runtime_store.list_sessions(context.workspace_id),
    )
    for thread in threads:
        forbidden_reason = _thread_cleanup_forbidden_reason(
            state,
            context,
            runtime_session_id=thread.runtime_session_id,
        )
        if forbidden_reason == "runtime_thread_not_found":
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if forbidden_reason is not None:
            return json_response(start_response, {"error": forbidden_reason}, status="403 Forbidden")
    reason = str(body.get("reason") or "runtime_threads_cleared").strip()

    def cleanup(session_id: str, cleanup_reason: str) -> dict[str, object]:
        return cleanup_runtime_session(state, session_id=session_id, reason=cleanup_reason, start_path=start_path, publish_thread_events=False)

    deleted_threads, cleanup_results = clear_runtime_threads_complete(
        state.runtime_store,
        workspace_id=context.workspace_id,
        cleanup_runtime=cleanup,
        reason=reason,
    )
    _publish_thread_change(
        state,
        workspace_id=context.workspace_id,
        action="cleared",
        deleted_thread_ids=[thread.thread_id for thread in deleted_threads],
        deleted_runtime_session_ids=[thread.runtime_session_id for thread in deleted_threads if thread.runtime_session_id],
    )
    return json_response(
        start_response,
        {
            **_threads_payload(state, workspace_id=context.workspace_id, viewer_user_id=context.user.user_id),
            "deleted_thread_ids": [thread.thread_id for thread in deleted_threads],
            "deleted_runtime_session_ids": [thread.runtime_session_id for thread in deleted_threads if thread.runtime_session_id],
            "runtime_cleanup_results": cleanup_results,
        },
    )


def _handle_session_item(state: PlatformState, context: RequestSession, session_id: str, start_response: StartResponse, *, start_path):
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    session = _reconciled_session(state, session, start_path=start_path)
    return json_response(start_response, _session_payload(session, provider_id=_resolved_provider_id(state, session)))


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
    query = parse_qs(query_string, keep_blank_values=False)
    limit = _bounded_positive_int(query.get("limit", [None])[0], maximum=5000)
    events = (
        state.runtime_store.list_recent_events(session_id, limit=limit)
        if limit is not None
        else state.runtime_store.list_events(session_id)
    )
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
    return _submit_runtime_turn_response(state, context, session, body, start_response, start_path=start_path)


def _runtime_turn_requested(body: dict) -> bool:
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    return bool(str(body.get("input_text") or body.get("message") or "").strip() or attachments)


def _submit_runtime_turn_response(
    state: PlatformState,
    context: RequestSession,
    session: RuntimeSessionRecord,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
):
    client_message_id = str(body.get("client_message_id") or "").strip() or None
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    attachment_items = [item for item in attachments if isinstance(item, dict)]
    input_text = str(body.get("input_text") or body.get("message") or "").strip()
    if not input_text and not attachment_items:
        return json_response(start_response, {"error": "empty_runtime_input"}, status="400 Bad Request")
    app_references = body.get("app_references") if isinstance(body.get("app_references"), list) else []
    app_reference_items = materialize_runtime_app_references(
        state,
        context=context,
        references=[item for item in app_references if isinstance(item, dict)],
        start_path=start_path,
    )
    async_requested = bool(body.get("async"))
    title_generation_input_hash = thread_title_input_hash(
        input_text,
        attachments=attachment_items,
        app_references=app_reference_items,
    )

    def notify_source_app_queued(queued_turn: RuntimeTurnRecord, _events: list[RuntimeEventRecord]) -> None:
        thread = mark_thread_user_message_queued(
            state,
            workspace_id=session.workspace_id,
            runtime_session_id=session.session_id,
            input_text=input_text,
            attachments=attachment_items,
            app_references=app_reference_items,
            title_generation_input_hash=title_generation_input_hash,
            now=queued_turn.created_at,
        )
        schedule_runtime_thread_title_generation(
            state,
            thread=thread,
            input_text=input_text,
            attachments=attachment_items,
            app_references=app_reference_items,
        )
        dispatch_source_app_runtime_event(
            state,
            session=session,
            turn=queued_turn,
            event_type="runtime.turn.queued",
            start_path=start_path,
        )

    try:
        if async_requested:
            turn, events = submit_runtime_turn_async(
                state,
                session=session,
                input_text=input_text,
                client_message_id=client_message_id,
                attachments=attachment_items,
                app_references=app_reference_items,
                on_queued=notify_source_app_queued,
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
                on_queued=notify_source_app_queued,
            )
            status = status_line(201)
    except ProviderError as error:
        return json_response(
            start_response,
            _provider_unavailable_response(state, session.workspace_id, error),
            status="409 Conflict",
        )
    thread = find_runtime_thread_by_session(
        state.runtime_store,
        workspace_id=session.workspace_id,
        runtime_session_id=session.session_id,
    )
    payload = {
        "session": _session_payload(session, provider_id=_resolved_provider_id(state, session)),
        "turn": _turn_payload(turn),
        "events": [_event_payload(event) for event in events],
    }
    if thread is not None:
        payload["thread"] = thread_payload(thread, viewer_user_id=context.user.user_id)
    return json_response(
        start_response,
        payload,
        status=status,
    )

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
    try:
        require_runtime_session_operation(
            workspace_store=state.workspace_store,
            user=context.user,
            session=session,
            operation="cleanup",
        )
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
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
    try:
        session = state.runtime_store.get_session(turn.session_id)
        require_runtime_session_operation(
            workspace_store=state.workspace_store,
            user=context.user,
            session=session,
            operation="interrupt",
        )
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    if turn.status not in {"queued", "active"}:
        return json_response(start_response, {"turn": _turn_payload(turn), "interrupted": False})
    provider_id = _resolved_provider_id(state, session)
    provider_interrupted = interrupt_runtime_provider_turn(state, session)
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
    set_thread_availability(
        state,
        workspace_id=updated.workspace_id,
        runtime_session_id=updated.session_id,
        availability="free",
        now=event.created_at,
    )
    release_idle_runtime_processes(state, session_id=updated.session_id, provider_id=provider_id or "unconfigured", reason="turn_interrupted", idle_ttl_seconds=0)
    dispatch_source_app_runtime_event(
        state,
        session=session,
        turn=updated,
        event_type="runtime.turn.failed",
        failure_reason="Interrupted by user.",
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
    body = read_json_body(environ) if method in {"POST", "PATCH", "PUT", "DELETE"} else {}

    if path == "/api/runtime/threads":
        return _handle_thread_collection(state, context, method, body, start_response)
    if path == "/api/runtime/threads/clear":
        return _handle_thread_clear(state, context, method, body, start_response, start_path=start_path)
    if path == "/api/runtime/sessions":
        return _handle_session_collection(state, context, method, body, start_response, start_path=start_path)

    parts = [part for part in path.removeprefix("/api/runtime/").split("/") if part]
    if len(parts) == 3 and parts[0] == "threads" and parts[2] == "read":
        return _handle_thread_read(state, context, parts[1], method, start_response)
    if len(parts) == 2 and parts[0] == "threads":
        return _handle_thread_item(state, context, parts[1], method, body, start_response, start_path=start_path)
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
