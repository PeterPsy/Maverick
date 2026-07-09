"""Generic runtime HTTP API for hosted Maverick apps."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
import time
from urllib.parse import parse_qs
from uuid import uuid4

from core.api.app_reference_payloads import materialize_runtime_app_references, validate_runtime_app_references
from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.provider_api import workspace_provider_status
from core.api.runtime_cleanup import cleanup_runtime_session
from core.api.session_api import RequestSession, require_session
from core.apps.errors import AppHostingError
from core.apps.runtime_event_hooks import dispatch_source_app_runtime_event
from core.authorization.errors import AuthorizationError
from core.authorization.service import authorize_runtime_session_create, require_runtime_session_operation
from core.inter_agent.errors import InterAgentRunNotFoundError
from core.inter_agent.service import InterAgentService, TERMINAL_RUN_STATUSES
from core.inter_agent.surfaces import inter_agent_payload
from core.observability.service import append_platform_log
from core.observability.startup_performance import startup_timer
from core.providers.errors import ProviderError
from core.providers.service import resolve_provider_for_runtime_session
from core.runtime.errors import RuntimeSessionHiddenError, RuntimeSessionNotFoundError, RuntimeThreadNotFoundError, RuntimeTurnNotFoundError
from core.runtime.client_message_claims import RuntimeClientMessageClaim, RuntimeClientMessageClaimConflictError
from core.runtime.runtime_threads import (
    clear_runtime_threads_complete,
    create_runtime_thread,
    delete_runtime_thread_complete,
    find_runtime_thread_by_session,
    list_runtime_threads,
    mark_runtime_thread_completed_response_read,
    thread_detail_payload,
    thread_summary_payload,
    update_runtime_thread,
)
from core.runtime.thread_catalog_events import set_thread_availability
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE
from core.runtime.service import (
    create_runtime_session,
    reconcile_runtime_session_policy,
    record_runtime_event,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord, runtime_session_allows_user_thread
from core.runtime.plain_hosted_text import (
    HOSTED_TEXT_RUNTIME_PROVIDER_ID,
    plain_hosted_chat_attachment_limit_error,
    queue_provider_id_for_session,
    runtime_session_is_plain_hosted_chat,
)
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.turn_submission import (
    interrupt_runtime_provider_turn,
    prewarm_runtime_session_async,
    release_idle_runtime_processes,
    submit_runtime_turn,
    submit_runtime_turn_async,
)
from core.runtime.turn_submission_service_queue import (
    RuntimeTurnSubmissionTiming,
    record_turn_post_queue_response_metric,
    runtime_turn_submission_timing,
)
from core.skills.runtime_catalog import runtime_skill_catalog_app_id_for_request


IDEMPOTENT_CLAIM_WAIT_SECONDS = 5.0
PREPARED_SESSION_TTL_SECONDS = 30 * 60
RUNTIME_THREAD_PAGE_DEFAULT_LIMIT = 50
RUNTIME_THREAD_PAGE_MAX_LIMIT = 100


@dataclass(frozen=True)
class RuntimeTurnSubmissionDraft:
    timing: RuntimeTurnSubmissionTiming | None
    client_message_id: str | None
    attachment_items: list[dict[str, object]]
    input_text: str
    app_reference_items: list[dict[str, object]]
    async_requested: bool


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


def _runtime_thread_page(
    state: PlatformState,
    *,
    workspace_id: str,
    viewer_user_id: str | None = None,
    limit: int = RUNTIME_THREAD_PAGE_DEFAULT_LIMIT,
    query: str | None = None,
    cursor: str | None = None,
) -> dict[str, object]:
    with startup_timer("runtime.threads.rest_payload", workspace_id=workspace_id) as timing:
        threads = list_runtime_threads(state.runtime_store, workspace_id=workspace_id)
        normalized_query = (query or "").strip()
        total_thread_count = len(threads)
        if normalized_query:
            threads = [thread for thread in threads if _thread_matches_query(thread, normalized_query)]
        normalized_cursor = (cursor or "").strip()
        cursor_found = True
        if normalized_cursor:
            cursor_index = next((index for index, thread in enumerate(threads) if thread.thread_id == normalized_cursor), None)
            cursor_found = cursor_index is not None
            threads = threads[cursor_index + 1 :] if cursor_index is not None else []
        bounded_limit = max(1, min(int(limit or RUNTIME_THREAD_PAGE_DEFAULT_LIMIT), RUNTIME_THREAD_PAGE_MAX_LIMIT))
        page_threads = threads[:bounded_limit]
        items = [
            thread_summary_payload(
                thread,
                viewer_user_id=viewer_user_id,
            )
            for thread in page_threads
        ]
        payload = {
            "workspace_id": workspace_id,
            "threads": items,
            "threads_page": {
                "limit": bounded_limit,
                "has_more": len(threads) > bounded_limit,
                "cursor": page_threads[-1].thread_id if len(threads) > bounded_limit and page_threads else None,
                "sort": "recency_desc",
                "query": normalized_query or None,
                "cursor_found": cursor_found,
                "total": total_thread_count,
                "filtered_total": len(threads),
            },
        }
        timing["thread_count"] = len(items)
        timing["filtered_thread_count"] = len(threads)
        timing["total_thread_count"] = total_thread_count
        timing["cursor"] = bool(normalized_cursor)
        timing["cursor_found"] = cursor_found
        return payload


def _threads_payload(state: PlatformState, *, workspace_id: str, viewer_user_id: str | None = None) -> dict[str, object]:
    return _runtime_thread_page(state, workspace_id=workspace_id, viewer_user_id=viewer_user_id)


def _thread_matches_query(thread, query: str) -> bool:
    tokens = [token for token in query.casefold().split() if token]
    if not tokens:
        return True
    haystack = " ".join(
        str(value or "")
        for value in [
            thread.thread_id,
            thread.runtime_session_id,
            thread.title,
            thread.agent_label,
            thread.agent_type_id,
            thread.agent_role_id,
            thread.source_app_id,
        ]
    ).casefold()
    return all(token in haystack for token in tokens)


def _thread_mutation_payload(
    state: PlatformState,
    thread,
    *,
    viewer_user_id: str | None,
    action: str = "updated",
) -> dict[str, object]:
    detail = _thread_detail_payload_with_runtime(state, thread, viewer_user_id=viewer_user_id)
    summary = thread_summary_payload(thread, viewer_user_id=viewer_user_id)
    return {
        "thread": detail,
        "changed_thread": summary,
        "action": action,
        "page_hint": {"sort": "recency_desc"},
    }


def _thread_detail_payload_with_runtime(
    state: PlatformState,
    thread,
    *,
    session: RuntimeSessionRecord | None = None,
    viewer_user_id: str | None = None,
) -> dict[str, object]:
    payload = thread_detail_payload(thread, viewer_user_id=viewer_user_id)
    runtime_session = session
    if runtime_session is None and getattr(thread, "runtime_session_id", ""):
        try:
            runtime_session = state.runtime_store.get_session(thread.runtime_session_id)
        except (RuntimeSessionNotFoundError, ValueError):
            runtime_session = None
    if runtime_session is None:
        return payload
    payload["runtime_mode"] = runtime_session.runtime_mode
    payload["provider_id"] = _resolved_provider_id(state, runtime_session)
    payload["hosted_provider_id"] = runtime_session.hosted_provider_id
    payload["hosted_model_id"] = runtime_session.hosted_model_id
    return payload


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
    }
    if thread is not None:
        payload["thread"] = thread_summary_payload(thread)
        payload["thread_id"] = thread.thread_id
    if deleted_thread_ids is not None:
        payload["deleted_thread_ids"] = deleted_thread_ids
    if deleted_runtime_session_ids is not None:
        payload["deleted_runtime_session_ids"] = deleted_runtime_session_ids
    state.runtime_thread_event_bus.publish(workspace_id=workspace_id, event=payload)


def _list_session_payloads(state: PlatformState, *, workspace_id: str, start_path) -> list[dict[str, object]]:
    sessions = state.runtime_store.list_sessions(workspace_id)
    reconciled = [_reconciled_session(state, session, start_path=start_path) for session in sessions]
    return [
        _session_payload(session, provider_id=_resolved_provider_id(state, session))
        for session in reconciled
        if runtime_session_allows_user_thread(session)
    ]


def _resolved_provider_id(state: PlatformState, session: RuntimeSessionRecord) -> str | None:
    if session.provider_id:
        return session.provider_id
    if runtime_session_is_plain_hosted_chat(session):
        return HOSTED_TEXT_RUNTIME_PROVIDER_ID
    try:
        provider, _selection = resolve_provider_for_runtime_session(state.provider_store, session=session)
    except ProviderError:
        return None
    return provider.provider_id


def _response_provider_id(session: RuntimeSessionRecord, events: list[RuntimeEventRecord] | None = None) -> str | None:
    if session.provider_id:
        return session.provider_id
    for event in events or []:
        provider_id = event.payload.get("provider_id") if isinstance(event.payload, dict) else None
        if isinstance(provider_id, str) and provider_id.strip():
            return provider_id.strip()
    return queue_provider_id_for_session(session)


def _turn_for_client_message(
    state: PlatformState,
    *,
    workspace_id: str,
    client_message_id: str | None,
    session_id: str | None = None,
) -> RuntimeTurnRecord | None:
    normalized_client_message_id = client_message_id.strip() if isinstance(client_message_id, str) else ""
    if not normalized_client_message_id:
        return None
    find_turn = getattr(state.runtime_store, "find_turn_by_client_message_id", None)
    if not callable(find_turn):
        return None
    return find_turn(
        workspace_id=workspace_id,
        session_id=session_id,
        client_message_id=normalized_client_message_id,
    )


def _claim_client_message_for_new_session(
    state: PlatformState,
    *,
    workspace_id: str,
    client_message_id: str | None,
) -> tuple[RuntimeClientMessageClaim | None, bool]:
    normalized_client_message_id = client_message_id.strip() if isinstance(client_message_id, str) else ""
    if not normalized_client_message_id:
        return None, True
    claim_client_message_id = getattr(state.runtime_store, "claim_client_message_id", None)
    if not callable(claim_client_message_id):
        return None, True
    return claim_client_message_id(
        workspace_id=workspace_id,
        client_message_id=normalized_client_message_id,
        session_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


def _release_client_message_claim(state: PlatformState, claim: RuntimeClientMessageClaim | None) -> None:
    if claim is None:
        return
    release_claim = getattr(state.runtime_store, "release_client_message_claim", None)
    if not callable(release_claim):
        return
    with suppress(Exception):
        release_claim(
            workspace_id=claim.workspace_id,
            client_message_id=claim.client_message_id,
            session_id=claim.session_id,
            turn_id=claim.turn_id,
        )


def _release_client_message_claim_if_turn_absent(
    state: PlatformState,
    claim: RuntimeClientMessageClaim | None,
) -> None:
    if claim is None:
        return
    if _turn_exists(state, claim.turn_id) is not None:
        return
    _release_client_message_claim(state, claim)


def _record_timing_duration(
    timing: RuntimeTurnSubmissionTiming | None,
    name: str,
    started_perf_counter: float,
) -> None:
    if timing is not None:
        timing.record_duration_ms(name, started_perf_counter)


def _prewarm_new_runtime_session(state: PlatformState, session: RuntimeSessionRecord) -> None:
    with suppress(Exception):
        prewarm_runtime_session_async(state, session=session)


def _mark_client_message_claim_queued(state: PlatformState, claim: RuntimeClientMessageClaim | None) -> None:
    if claim is None:
        return
    mark_claim = getattr(state.runtime_store, "mark_client_message_claim_queued", None)
    if not callable(mark_claim):
        return
    with suppress(Exception):
        mark_claim(
            workspace_id=claim.workspace_id,
            client_message_id=claim.client_message_id,
            session_id=claim.session_id,
            turn_id=claim.turn_id,
        )


def _same_client_message_claim(left: RuntimeClientMessageClaim | None, right: RuntimeClientMessageClaim | None) -> bool:
    return (
        left is not None
        and right is not None
        and left.workspace_id == right.workspace_id
        and left.client_message_id == right.client_message_id
        and left.session_id == right.session_id
        and left.turn_id == right.turn_id
    )


def _wait_for_claimed_turn(state: PlatformState, claim: RuntimeClientMessageClaim) -> RuntimeTurnRecord | None:
    deadline = time.monotonic() + IDEMPOTENT_CLAIM_WAIT_SECONDS
    while True:
        try:
            turn = state.runtime_store.get_turn(claim.turn_id)
        except RuntimeTurnNotFoundError:
            turn = None
        if (
            turn is not None
            and turn.workspace_id == claim.workspace_id
            and turn.session_id == claim.session_id
            and turn.client_message_id == claim.client_message_id
        ):
            return turn
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.01)


def _turn_exists(state: PlatformState, turn_id: str) -> RuntimeTurnRecord | None:
    try:
        return state.runtime_store.get_turn(turn_id)
    except RuntimeTurnNotFoundError:
        return None


def _pending_client_message_claim_response(
    state: PlatformState,
    context: RequestSession,
    claim: RuntimeClientMessageClaim,
    start_response: StartResponse,
) -> list[bytes]:
    payload: dict[str, object] = {
        "idempotency": {
            "status": "pending",
            "client_message_id": claim.client_message_id,
            "session_id": claim.session_id,
            "turn_id": claim.turn_id,
        }
    }
    with suppress(Exception):
        session = state.runtime_store.get_session(claim.session_id)
        if session.workspace_id == context.workspace_id and runtime_session_allows_user_thread(session):
            payload["session"] = _session_payload(session, provider_id=_response_provider_id(session))
    return json_response(start_response, payload, status="202 Accepted")


def _turn_response_events(state: PlatformState, turn: RuntimeTurnRecord) -> list[RuntimeEventRecord]:
    return [
        event
        for event in state.runtime_store.list_events(turn.session_id)
        if event.turn_id == turn.turn_id and event.event_type == "runtime.turn.queued"
    ][:1]


def _runtime_turn_response_payload(
    state: PlatformState,
    context: RequestSession,
    *,
    session: RuntimeSessionRecord,
    turn: RuntimeTurnRecord,
    events: list[RuntimeEventRecord],
) -> dict[str, object]:
    thread = find_runtime_thread_by_session(
        state.runtime_store,
        workspace_id=session.workspace_id,
        runtime_session_id=session.session_id,
    )
    payload = {
        "session": _session_payload(session, provider_id=_response_provider_id(session, events)),
        "turn": _turn_payload(turn),
        "events": [_event_payload(event) for event in events],
    }
    if thread is not None:
        payload["thread"] = _thread_detail_payload_with_runtime(state, thread, viewer_user_id=context.user.user_id)
    return payload


def _idempotent_runtime_turn_response(
    state: PlatformState,
    context: RequestSession,
    turn: RuntimeTurnRecord,
    start_response: StartResponse,
) -> list[bytes]:
    try:
        session = state.runtime_store.get_session(turn.session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    except ValueError:
        return _hidden_runtime_session_response(start_response, runtime_session_id=turn.session_id, thread_visibility="invalid")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
    return json_response(
        start_response,
        _runtime_turn_response_payload(
            state,
            context,
            session=session,
            turn=turn,
            events=_turn_response_events(state, turn),
        ),
        status="200 OK",
    )


def _hidden_runtime_session_response(
    start_response: StartResponse,
    session: RuntimeSessionRecord | None = None,
    *,
    runtime_session_id: str = "",
    thread_visibility: str = "hidden",
) -> list[bytes]:
    if session is not None:
        runtime_session_id = session.session_id
        thread_visibility = session.thread_visibility
    return json_response(
        start_response,
        {
            "error": "runtime_session_hidden",
            "runtime_session_id": runtime_session_id,
            "thread_visibility": thread_visibility,
        },
        status="409 Conflict",
    )


def _thread_references_hidden_session(state: PlatformState, thread) -> bool:
    runtime_session_id = str(getattr(thread, "runtime_session_id", "") or "").strip()
    if not runtime_session_id:
        return False
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return False
    except ValueError:
        return True
    return not runtime_session_allows_user_thread(session)


def _provider_unavailable_response(state: PlatformState, workspace_id: str, error: Exception) -> dict[str, object]:
    status = workspace_provider_status(state, workspace_id=workspace_id)
    return {
        "error": "provider_unavailable",
        "blocked_reason": status.get("blocked_reason") or "provider_unavailable",
        "detail": str(error),
        "provider_status": status,
    }


def _body_text_or_session(body: dict, key: str, session: RuntimeSessionRecord, attribute: str) -> str:
    value = body.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    session_value = getattr(session, attribute, "")
    if isinstance(session_value, str):
        return session_value.strip()
    return ""


def _create_thread_for_session(
    state: PlatformState,
    *,
    context: RequestSession,
    session: RuntimeSessionRecord,
    body: dict,
    action: str = "created",
):
    requested_title = _body_text_or_session(body, "title", session, "thread_title")
    thread_title = requested_title or DEFAULT_THREAD_TITLE
    thread = create_runtime_thread(
        state.runtime_store,
        workspace_id=context.workspace_id,
        thread_id=session.session_id,
        runtime_session_id=session.session_id,
        title=thread_title,
        title_source="placeholder" if not requested_title or requested_title == DEFAULT_THREAD_TITLE else "manual",
        agent_label=_body_text_or_session(body, "agent_label", session, "agent_label") or session.agent_id,
        agent_type_id=_body_text_or_session(body, "agent_type_id", session, "agent_type_id"),
        agent_role_id=_body_text_or_session(body, "agent_role_id", session, "agent_role_id"),
        source_app_id=session.source_app_id or session.agent_id,
        system_prompt=session.system_prompt or "",
        project_id=_body_text_or_session(body, "project_id", session, "project_id") or None,
        now=session.started_at or session.updated_at,
    )
    _publish_thread_change(state, workspace_id=context.workspace_id, action=action, thread=thread)
    return thread


def _cleanup_expired_prepared_sessions(state: PlatformState, *, context: RequestSession) -> None:
    cutoff = datetime.now(tz=UTC) - timedelta(seconds=PREPARED_SESSION_TTL_SECONDS)
    for session in state.runtime_store.list_sessions(context.workspace_id):
        if (
            session.session_kind != "chat_root"
            or session.thread_visibility != "hidden"
            or session.owner_user_id != context.user.user_id
            or session.updated_at >= cutoff
        ):
            continue
        with suppress(Exception):
            if state.runtime_store.list_turns(session.session_id):
                continue
            cleanup_runtime_session(
                state,
                session_id=session.session_id,
                reason="prepared_session_expired",
                start_path=state.repository_root,
                publish_thread_events=False,
                allow_hidden_prepared_chat_cleanup=True,
            )


def _prepared_session_can_be_promoted(session: RuntimeSessionRecord, context: RequestSession) -> bool:
    return (
        session.session_kind == "chat_root"
        and session.thread_visibility == "hidden"
        and session.workspace_id == context.workspace_id
        and session.owner_user_id == context.user.user_id
    )


def _promote_prepared_session_for_turn(
    state: PlatformState,
    context: RequestSession,
    session: RuntimeSessionRecord,
    body: dict,
) -> RuntimeSessionRecord:
    visible = state.runtime_store.save_session(replace(session, thread_visibility="user", updated_at=datetime.now(tz=UTC)))
    try:
        state.runtime_store.get_thread(visible.session_id)
        action = "updated"
    except RuntimeThreadNotFoundError:
        action = "created"
    _create_thread_for_session(state, context=context, session=visible, body=body, action=action)
    return visible


def _log_runtime_api_timing(
    state: PlatformState,
    context: RequestSession,
    *,
    route: str,
    method: str,
    elapsed_ms: float,
    runtime_session_id: str = "",
) -> None:
    with suppress(Exception):
        append_platform_log(
            log_plane="runtime",
            message="Runtime API timing",
            payload={
                "component": "runtime_api",
                "route": route,
                "method": method,
                "elapsed_ms": round(elapsed_ms, 3),
            },
            workspace_id=context.workspace_id,
            runtime_session_id=runtime_session_id or None,
            start_path=state.repository_root,
        )


def _timed_runtime_api_response(
    state: PlatformState,
    context: RequestSession,
    *,
    route: str,
    method: str,
    runtime_session_id: str = "",
    handler,
) -> list[bytes]:
    started_at = time.perf_counter()
    try:
        return handler()
    finally:
        _log_runtime_api_timing(
            state,
            context,
            route=route,
            method=method,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
            runtime_session_id=runtime_session_id,
        )


def _create_session(
    state: PlatformState,
    context: RequestSession,
    body: dict,
    *,
    agent_id: str,
    start_path,
    session_id: str | None = None,
    prepare_only: bool = False,
) -> RuntimeSessionRecord:
    authorize_runtime_session_create(
        workspace_store=state.workspace_store,
        runtime_store=state.runtime_store,
        user=context.user,
        workspace_id=context.workspace_id,
    )
    source_app_id = str(body.get("source_app_id") or "").strip() or None
    session = create_runtime_session(
        state.runtime_store,
        session_id=session_id or str(uuid4()),
        workspace_id=context.workspace_id,
        agent_id=agent_id,
        requested_mode=body.get("requested_mode"),
        runtime_mode=body.get("runtime_mode"),
        hosted_provider_id=body.get("hosted_provider_id"),
        hosted_model_id=body.get("hosted_model_id"),
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
        thread_title=str(body.get("title") or "").strip(),
        agent_label=str(body.get("agent_label") or "").strip(),
        agent_type_id=str(body.get("agent_type_id") or "").strip(),
        agent_role_id=str(body.get("agent_role_id") or "").strip(),
        project_id=str(body.get("project_id") or "").strip() or None,
        owner_user_id=context.user.user_id,
        created_by_user_id=context.user.user_id,
        thread_visibility="hidden" if prepare_only else "user",
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
    if not prepare_only:
        _create_thread_for_session(state, context=context, session=session, body=body)
    return session


def _handle_session_collection(
    state: PlatformState,
    context: RequestSession,
    method: str,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
    received_perf_counter: float | None = None,
):
    if method == "GET":
        return json_response(start_response, {"items": _list_session_payloads(state, workspace_id=context.workspace_id, start_path=start_path)})
    if method == "POST":
        agent_id = str(body.get("agent_id") or "").strip()
        if not agent_id:
            return json_response(start_response, {"error": "agent_id_required"}, status="400 Bad Request")
        routing_profile_error = _routing_profile_error(body)
        if routing_profile_error is not None:
            return json_response(start_response, {"error": routing_profile_error}, status="400 Bad Request")
        client_message_id = str(body.get("client_message_id") or "").strip() or None
        client_message_claim: RuntimeClientMessageClaim | None = None
        client_message_claim_created = True
        turn_requested = _runtime_turn_requested(body)
        prepare_only = bool(body.get("prepare_only"))
        if prepare_only and turn_requested:
            return json_response(start_response, {"error": "prepare_only_turn_not_allowed"}, status="400 Bad Request")
        if prepare_only:
            _cleanup_expired_prepared_sessions(state, context=context)
        submission_timing = runtime_turn_submission_timing(received_perf_counter) if turn_requested else None
        if turn_requested:
            claim_started_at = time.perf_counter()
            client_message_claim, client_message_claim_created = _claim_client_message_for_new_session(
                state,
                workspace_id=context.workspace_id,
                client_message_id=client_message_id,
            )
            _record_timing_duration(submission_timing, "claim_ms", claim_started_at)
            if client_message_claim is not None and not client_message_claim_created:
                existing_turn = _wait_for_claimed_turn(state, client_message_claim)
                if existing_turn is not None:
                    return _idempotent_runtime_turn_response(state, context, existing_turn, start_response)
                return _pending_client_message_claim_response(state, context, client_message_claim, start_response)
        try:
            session_create_started_at = time.perf_counter()
            session = _create_session(
                state,
                context,
                body,
                agent_id=agent_id,
                start_path=start_path,
                session_id=client_message_claim.session_id if client_message_claim is not None else None,
                prepare_only=prepare_only,
            )
            _record_timing_duration(submission_timing, "session_create_ms", session_create_started_at)
        except AuthorizationError as error:
            _release_client_message_claim(state, client_message_claim if client_message_claim_created else None)
            status = "429 Too Many Requests" if error.reason == "max_agent_instances_reached" else "403 Forbidden"
            return json_response(start_response, {"error": error.reason}, status=status)
        except AppHostingError as error:
            _release_client_message_claim(state, client_message_claim if client_message_claim_created else None)
            return json_response(
                start_response,
                {"error": "runtime_skill_catalog_unavailable", "detail": str(error)},
                status="400 Bad Request",
            )
        _prewarm_new_runtime_session(state, session)
        if turn_requested:
            try:
                return _submit_runtime_turn_response(
                    state,
                    context,
                    session,
                    body,
                    start_response,
                    start_path=start_path,
                    reserved_turn_id=client_message_claim.turn_id if client_message_claim is not None else None,
                    received_perf_counter=received_perf_counter,
                    submission_timing=submission_timing,
                    release_claim_on_failure=client_message_claim if client_message_claim_created else None,
                )
            except Exception:
                _release_client_message_claim_if_turn_absent(
                    state,
                    client_message_claim if client_message_claim_created else None,
                )
                raise
        return json_response(start_response, _session_payload(session, provider_id=_resolved_provider_id(state, session)), status="201 Created")
    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _handle_thread_collection(state: PlatformState, context: RequestSession, method: str, body: dict, start_response: StartResponse, *, query_string: str = ""):
    if method == "GET":
        query = parse_qs(query_string, keep_blank_values=False)
        limit = _bounded_positive_int(query.get("limit", [None])[0], maximum=RUNTIME_THREAD_PAGE_MAX_LIMIT)
        search_query = str(query.get("query", query.get("q", [""]))[0] or "").strip()
        cursor = str(query.get("cursor", [""])[0] or "").strip()
        return json_response(
            start_response,
            _runtime_thread_page(
                state,
                workspace_id=context.workspace_id,
                viewer_user_id=context.user.user_id,
                limit=limit or RUNTIME_THREAD_PAGE_DEFAULT_LIMIT,
                query=search_query or None,
                cursor=cursor or None,
            ),
        )
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    runtime_session_id = str(body.get("runtime_session_id") or "").strip()
    if not runtime_session_id:
        return json_response(start_response, {"error": "runtime_session_id_required"}, status="400 Bad Request")
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    except ValueError:
        return _hidden_runtime_session_response(start_response, runtime_session_id=runtime_session_id, thread_visibility="invalid")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
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
    try:
        thread = create_runtime_thread(
            state.runtime_store,
            workspace_id=context.workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=requested_title,
            title_source=title_source,
            agent_label=_body_text_or_session(body, "agent_label", session, "agent_label") or session.agent_id,
            agent_type_id=_body_text_or_session(body, "agent_type_id", session, "agent_type_id"),
            agent_role_id=_body_text_or_session(body, "agent_role_id", session, "agent_role_id"),
            source_app_id=str(body.get("source_app_id") or "").strip() or session.source_app_id or session.agent_id,
            system_prompt=str(body.get("system_prompt") or "").strip() or session.system_prompt or "",
            project_id=_body_text_or_session(body, "project_id", session, "project_id") or None,
            now=session.started_at or session.updated_at,
        )
    except RuntimeSessionHiddenError:
        return _hidden_runtime_session_response(start_response, session)
    _publish_thread_change(state, workspace_id=context.workspace_id, action="updated" if existing else "created", thread=thread)
    return json_response(
        start_response,
        _thread_mutation_payload(
            state,
            thread,
            viewer_user_id=context.user.user_id,
            action="updated" if existing else "created",
        ),
        status="201 Created",
    )


def _thread_cleanup_forbidden_reason(state: PlatformState, context: RequestSession, *, runtime_session_id: str) -> str | None:
    if not runtime_session_id:
        return None
    try:
        session = state.runtime_store.get_session(runtime_session_id)
    except RuntimeSessionNotFoundError:
        return None
    except ValueError:
        return "runtime_thread_not_found"
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
        except ValueError:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if session.workspace_id != context.workspace_id:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if not runtime_session_allows_user_thread(session):
            return _hidden_runtime_session_response(start_response, session)
        thread = create_runtime_thread(
            state.runtime_store,
            workspace_id=context.workspace_id,
            thread_id=session.session_id,
            runtime_session_id=session.session_id,
            title=DEFAULT_THREAD_TITLE,
            title_source="placeholder",
            agent_label=session.agent_label or session.agent_id,
            agent_type_id=session.agent_type_id,
            agent_role_id=session.agent_role_id,
            source_app_id=session.source_app_id or session.agent_id,
            system_prompt=session.system_prompt or "",
            project_id=session.project_id,
            now=session.started_at or session.updated_at,
        )
        _publish_thread_change(state, workspace_id=context.workspace_id, action="created", thread=thread)
    if thread.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
    if _thread_references_hidden_session(state, thread):
        return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
    if method == "GET":
        return json_response(
            start_response,
            {"thread": _thread_detail_payload_with_runtime(state, thread, viewer_user_id=context.user.user_id)},
        )
    if method == "PATCH":
        try:
            updated = update_runtime_thread(
                state.runtime_store,
                thread_id=thread_id,
                workspace_id=context.workspace_id,
                updates=body,
            )
        except RuntimeSessionHiddenError:
            runtime_session_id = str(body.get("runtime_session_id") or "").strip()
            try:
                session = state.runtime_store.get_session(runtime_session_id)
            except RuntimeSessionNotFoundError:
                return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
            except ValueError:
                return _hidden_runtime_session_response(start_response, runtime_session_id=runtime_session_id, thread_visibility="invalid")
            return _hidden_runtime_session_response(start_response, session)
        if updated is None:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        _publish_thread_change(state, workspace_id=context.workspace_id, action="updated", thread=updated)
        return json_response(
            start_response,
            _thread_mutation_payload(state, updated, viewer_user_id=context.user.user_id, action="updated"),
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
            "deleted_thread_id": deleted.thread_id,
            "removed_thread_id": deleted.thread_id,
            "deleted_runtime_session_id": deleted.runtime_session_id,
            "action": "deleted",
            "page_hint": {"sort": "recency_desc"},
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
        except ValueError:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if session.workspace_id != context.workspace_id:
            return json_response(start_response, {"error": "runtime_thread_not_found"}, status="404 Not Found")
        if not runtime_session_allows_user_thread(session):
            return _hidden_runtime_session_response(start_response, session)
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
    if _thread_references_hidden_session(state, thread):
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
        _thread_mutation_payload(state, updated, viewer_user_id=context.user.user_id, action="updated"),
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
    threads = list_runtime_threads(state.runtime_store, workspace_id=context.workspace_id)
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
            "deleted_thread_ids": [thread.thread_id for thread in deleted_threads],
            "deleted_runtime_session_ids": [thread.runtime_session_id for thread in deleted_threads if thread.runtime_session_id],
            "runtime_cleanup_results": cleanup_results,
            "action": "cleared",
            "page_hint": {"sort": "recency_desc"},
        },
    )


def _handle_session_item(state: PlatformState, context: RequestSession, session_id: str, start_response: StartResponse, *, start_path):
    try:
        session = state.runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
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
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
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


def _handle_session_turns(
    state: PlatformState,
    context: RequestSession,
    session_id: str,
    method: str,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
    received_perf_counter: float | None = None,
):
    try:
        session = state.runtime_store.get_session(session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        if method == "POST" and _runtime_turn_requested(body) and _prepared_session_can_be_promoted(session, context):
            try:
                require_runtime_session_operation(
                    workspace_store=state.workspace_store,
                    user=context.user,
                    session=session,
                    operation="turn_submit",
                )
            except AuthorizationError as error:
                return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
            submission_timing = runtime_turn_submission_timing(received_perf_counter)
            draft, validation_response = _prepare_runtime_turn_submission(
                state,
                context,
                session,
                body,
                start_response,
                start_path=start_path,
                timing=submission_timing,
            )
            if validation_response is not None:
                return validation_response
            if draft is None:
                return json_response(start_response, {"error": "empty_runtime_input"}, status="400 Bad Request")
            session = _promote_prepared_session_for_turn(state, context, session, body)
            session = _reconciled_session(state, session, start_path=start_path)
            return _queue_runtime_turn_response(
                state,
                context,
                session,
                draft,
                start_response,
                start_path=start_path,
                received_perf_counter=received_perf_counter,
            )
        else:
            return _hidden_runtime_session_response(start_response, session)
    session = _reconciled_session(state, session, start_path=start_path)
    if method == "GET":
        return json_response(start_response, {"items": [_turn_payload(turn) for turn in state.runtime_store.list_turns(session_id)]})
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    try:
        require_runtime_session_operation(
            workspace_store=state.workspace_store,
            user=context.user,
            session=session,
            operation="turn_submit",
        )
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    return _submit_runtime_turn_response(
        state,
        context,
        session,
        body,
        start_response,
        start_path=start_path,
        received_perf_counter=received_perf_counter,
    )


def _runtime_turn_requested(body: dict) -> bool:
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    return bool(str(body.get("input_text") or body.get("message") or "").strip() or attachments)


def _routing_profile_error(body: dict) -> str | None:
    if "routing_profile" not in body:
        return None
    routing_profile = str(body.get("routing_profile") or "").strip()
    if routing_profile in {"", "fast_model"}:
        return None
    return "unsupported_routing_profile"


def _submit_runtime_turn_response(
    state: PlatformState,
    context: RequestSession,
    session: RuntimeSessionRecord,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
    reserved_turn_id: str | None = None,
    received_perf_counter: float | None = None,
    submission_timing: RuntimeTurnSubmissionTiming | None = None,
    release_claim_on_failure: RuntimeClientMessageClaim | None = None,
):
    timing = submission_timing or runtime_turn_submission_timing(received_perf_counter)
    draft, validation_response = _prepare_runtime_turn_submission(
        state,
        context,
        session,
        body,
        start_response,
        start_path=start_path,
        timing=timing,
        release_claim_on_failure=release_claim_on_failure,
    )
    if validation_response is not None:
        return validation_response
    if draft is None:
        _release_client_message_claim(state, release_claim_on_failure)
        return json_response(start_response, {"error": "empty_runtime_input"}, status="400 Bad Request")
    return _queue_runtime_turn_response(
        state,
        context,
        session,
        draft,
        start_response,
        start_path=start_path,
        reserved_turn_id=reserved_turn_id,
        received_perf_counter=received_perf_counter,
        release_claim_on_failure=release_claim_on_failure,
    )


def _prepare_runtime_turn_submission(
    state: PlatformState,
    context: RequestSession,
    session: RuntimeSessionRecord,
    body: dict,
    start_response: StartResponse,
    *,
    start_path,
    timing: RuntimeTurnSubmissionTiming | None,
    release_claim_on_failure: RuntimeClientMessageClaim | None = None,
) -> tuple[RuntimeTurnSubmissionDraft | None, list[bytes] | None]:
    routing_profile_error = _routing_profile_error(body)
    if routing_profile_error is not None:
        _release_client_message_claim(state, release_claim_on_failure)
        return None, json_response(start_response, {"error": routing_profile_error}, status="400 Bad Request")
    client_message_id = str(body.get("client_message_id") or "").strip() or None
    existing_turn = _turn_for_client_message(
        state,
        workspace_id=session.workspace_id,
        session_id=session.session_id,
        client_message_id=client_message_id,
    )
    if existing_turn is not None:
        return None, _idempotent_runtime_turn_response(state, context, existing_turn, start_response)
    attachments = body.get("attachments") if isinstance(body.get("attachments"), list) else []
    attachment_items = [item for item in attachments if isinstance(item, dict)]
    input_text = str(body.get("input_text") or body.get("message") or "").strip()
    if not input_text and not attachment_items:
        _release_client_message_claim(state, release_claim_on_failure)
        return None, json_response(start_response, {"error": "empty_runtime_input"}, status="400 Bad Request")
    app_references = body.get("app_references") if isinstance(body.get("app_references"), list) else []
    if runtime_session_is_plain_hosted_chat(session):
        if session.skill_ids:
            _release_client_message_claim(state, release_claim_on_failure)
            return None, json_response(start_response, {"error": "plain_hosted_chat_blocks_skills"}, status="400 Bad Request")
        if app_references:
            _release_client_message_claim(state, release_claim_on_failure)
            return None, json_response(start_response, {"error": "plain_hosted_chat_blocks_app_references"}, status="400 Bad Request")
        attachment_limit_error = plain_hosted_chat_attachment_limit_error(attachment_items)
        if attachment_limit_error is not None:
            _release_client_message_claim(state, release_claim_on_failure)
            return None, json_response(start_response, {"error": attachment_limit_error}, status="400 Bad Request")
    reference_validate_started_at = time.perf_counter()
    app_reference_items = validate_runtime_app_references(
        state,
        context=context,
        references=[item for item in app_references if isinstance(item, dict)],
        start_path=start_path,
    )
    _record_timing_duration(timing, "reference_validate_ms", reference_validate_started_at)
    return RuntimeTurnSubmissionDraft(
        timing=timing,
        client_message_id=client_message_id,
        attachment_items=attachment_items,
        input_text=input_text,
        app_reference_items=app_reference_items,
        async_requested=bool(body.get("async")),
    ), None


def _queue_runtime_turn_response(
    state: PlatformState,
    context: RequestSession,
    session: RuntimeSessionRecord,
    draft: RuntimeTurnSubmissionDraft,
    start_response: StartResponse,
    *,
    start_path,
    reserved_turn_id: str | None = None,
    received_perf_counter: float | None = None,
    release_claim_on_failure: RuntimeClientMessageClaim | None = None,
):
    timing = draft.timing
    client_message_id = draft.client_message_id
    attachment_items = draft.attachment_items
    input_text = draft.input_text
    app_reference_items = draft.app_reference_items
    async_requested = draft.async_requested

    def materialize_app_references(references: list[dict[str, object]]) -> list[dict[str, object]]:
        return materialize_runtime_app_references(
            state,
            context=context,
            references=references,
            start_path=start_path,
        )

    def notify_source_app_queued(queued_turn: RuntimeTurnRecord, _events: list[RuntimeEventRecord]) -> None:
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
                app_reference_materializer=materialize_app_references if app_reference_items else None,
                on_queued=notify_source_app_queued,
                turn_id=reserved_turn_id,
                received_perf_counter=received_perf_counter,
                submission_timing=timing,
                client_message_claim=release_claim_on_failure,
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
                app_reference_materializer=materialize_app_references if app_reference_items else None,
                on_queued=notify_source_app_queued,
                turn_id=reserved_turn_id,
                received_perf_counter=received_perf_counter,
                submission_timing=timing,
                client_message_claim=release_claim_on_failure,
            )
            status = status_line(201)
    except RuntimeClientMessageClaimConflictError as error:
        current_claim = error.current_claim
        if current_claim is not None and not _same_client_message_claim(current_claim, release_claim_on_failure):
            existing_turn = _wait_for_claimed_turn(state, current_claim)
            if existing_turn is not None:
                return _idempotent_runtime_turn_response(state, context, existing_turn, start_response)
            return _pending_client_message_claim_response(state, context, current_claim, start_response)
        _release_client_message_claim_if_turn_absent(state, release_claim_on_failure)
        return json_response(start_response, {"error": "client_message_claim_expired"}, status="409 Conflict")
    except ProviderError as error:
        if reserved_turn_id is None or _turn_exists(state, reserved_turn_id) is None:
            _release_client_message_claim(state, release_claim_on_failure)
        return json_response(
            start_response,
            _provider_unavailable_response(state, session.workspace_id, error),
            status="409 Conflict",
        )
    if reserved_turn_id is None or turn.turn_id == reserved_turn_id:
        _mark_client_message_claim_queued(state, release_claim_on_failure)
    response_session = state.runtime_store.get_session(session.session_id)
    post_queue_event = record_turn_post_queue_response_metric(
        state,
        session=response_session,
        turn=turn,
        submission_timing=timing,
    )
    if post_queue_event is not None:
        events = [*events, post_queue_event]
    return json_response(
        start_response,
        _runtime_turn_response_payload(
            state,
            context,
            session=response_session,
            turn=turn,
            events=events,
        ),
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
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if session.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
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
    try:
        session = state.runtime_store.get_session(turn.session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
    return json_response(start_response, _turn_payload(turn))


def _handle_turn_interrupt(
    state: PlatformState,
    context: RequestSession,
    turn_id: str,
    start_response: StartResponse,
    *,
    start_path,
):
    try:
        turn = state.runtime_store.get_turn(turn_id)
    except RuntimeTurnNotFoundError:
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    if turn.workspace_id != context.workspace_id:
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    try:
        session = state.runtime_store.get_session(turn.session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return json_response(start_response, {"error": "runtime_turn_not_found"}, status="404 Not Found")
    if not runtime_session_allows_user_thread(session):
        return _hidden_runtime_session_response(start_response, session)
    try:
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
    inter_agent_cleanup = _cancel_inter_agent_runs_for_root_turn(
        state,
        workspace_id=context.workspace_id,
        turn=updated,
        reason="root_runtime_turn_interrupted",
        start_path=start_path,
    )
    payload = {
        "turn": _turn_payload(updated),
        "event": _event_payload(event),
        "interrupted": True,
        "provider_interrupted": provider_interrupted,
    }
    if inter_agent_cleanup:
        payload["inter_agent_cleanup"] = inter_agent_cleanup
    return json_response(start_response, payload)


def _cancel_inter_agent_runs_for_root_turn(
    state: PlatformState,
    *,
    workspace_id: str,
    turn: RuntimeTurnRecord,
    reason: str,
    start_path,
) -> list[dict[str, object]]:
    run_id = _inter_agent_run_id_for_root_turn(state, turn)
    if not run_id:
        return []
    try:
        run = state.inter_agent_store.get_run(run_id, workspace_id=workspace_id)
    except InterAgentRunNotFoundError:
        return []
    if run.root_runtime_session_id != turn.session_id or run.status in TERMINAL_RUN_STATUSES:
        return []
    service = InterAgentService(state.inter_agent_store)
    result = service.close_run(
        workspace_id=workspace_id,
        run_id=run.run_id,
        cleanup_runtime_session=lambda session_id, cleanup_reason: cleanup_runtime_session(
            state,
            session_id=session_id,
            reason=cleanup_reason,
            start_path=start_path,
            publish_thread_events=False,
            allow_hidden_inter_agent_cleanup=True,
        ),
        reason=reason,
        terminal_status="cancelled",
        delete_records=False,
    )
    return [inter_agent_payload({"run_id": run.run_id, **result})]


def _inter_agent_run_id_for_root_turn(state: PlatformState, turn: RuntimeTurnRecord) -> str:
    for event in state.runtime_store.list_events(turn.session_id):
        if event.turn_id != turn.turn_id:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        run_id = str(payload.get("inter_agent_run_id") or "").strip()
        if run_id:
            return run_id
    return ""


def handle_runtime_api(state: PlatformState, environ: dict, start_response: StartResponse, *, start_path) -> list[bytes] | None:
    """Handle generic runtime routes for apps and shell clients."""
    path = environ.get("PATH_INFO", "/")
    if not path.startswith("/api/runtime/"):
        return None
    received_perf_counter = time.perf_counter()
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    method = environ.get("REQUEST_METHOD", "GET").upper()
    query_string = environ.get("QUERY_STRING", "")
    body = read_json_body(environ) if method in {"POST", "PATCH", "PUT", "DELETE"} else {}

    if path == "/api/runtime/threads":
        return _handle_thread_collection(state, context, method, body, start_response, query_string=query_string)
    if path == "/api/runtime/threads/clear":
        return _handle_thread_clear(state, context, method, body, start_response, start_path=start_path)
    if path == "/api/runtime/sessions":
        return _timed_runtime_api_response(
            state,
            context,
            route="/api/runtime/sessions",
            method=method,
            handler=lambda: _handle_session_collection(
                state,
                context,
                method,
                body,
                start_response,
                start_path=start_path,
                received_perf_counter=received_perf_counter,
            ),
        )

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
        return _timed_runtime_api_response(
            state,
            context,
            route="/api/runtime/sessions/:id/turns",
            method=method,
            runtime_session_id=parts[1],
            handler=lambda: _handle_session_turns(
                state,
                context,
                parts[1],
                method,
                body,
                start_response,
                start_path=start_path,
                received_perf_counter=received_perf_counter,
            ),
        )
    if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "cleanup":
        return _handle_session_cleanup(state, context, parts[1], method, body, start_response, start_path=start_path)
    if len(parts) == 2 and parts[0] == "turns" and method == "GET":
        return _handle_turn_item(state, context, parts[1], start_response)
    if len(parts) == 3 and parts[0] == "turns" and parts[2] == "interrupt" and method == "POST":
        return _handle_turn_interrupt(state, context, parts[1], start_response, start_path=start_path)
    return json_response(start_response, {"error": "runtime_route_not_found"}, status="404 Not Found")
