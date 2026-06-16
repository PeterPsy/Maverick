"""Settings and recovery HTTP API for the hosted platform shell."""

from __future__ import annotations

from dataclasses import asdict, replace

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.provider_api import workspace_provider_status, workspace_runtime_status
from core.api.runtime_cleanup import RuntimeCleanupError, cleanup_runtime_session
from core.api.session_api import RequestSession, public_user_payload, require_session
from core.api.workspace_api import workspace_payload
from core.authorization.errors import AuthorizationError
from core.authorization.service import (
    require_governance_management,
    require_runtime_session_operation,
)
from core.providers.service import builtin_provider_registry
from core.recovery.service import execute_session_restart, record_provider_health, record_runtime_health, recovery_status
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.workspaces.errors import WorkspaceMembershipError


GOVERNANCE_PATCH_FIELDS = {
    "allow_app_installation",
    "allow_agent_creation",
    "allow_agent_management",
    "allow_custom_apps",
    "allow_full_access_runtime",
}


def platform_settings_payload(state: PlatformState, context: RequestSession) -> dict[str, object]:
    """Return shell-visible platform settings without secrets."""
    runtime_status = workspace_runtime_status(state, workspace_id=context.workspace_id)
    cleanup_scope = _runtime_cleanup_scope(state, context)
    runtime_status["cleanup_allowed"] = cleanup_scope != "none"
    runtime_status["cleanup_scope"] = cleanup_scope
    runtime_status["all_sessions"] = runtime_session_inventory(state, context)
    return {
        "user": public_user_payload(context.user),
        "workspace": workspace_payload(state, context.workspace_id),
        "provider": workspace_provider_status(state, workspace_id=context.workspace_id),
        "runtime": runtime_status,
        "recovery": recovery_status(state.recovery_store, workspace_id=context.workspace_id),
    }


def _runtime_cleanup_scope(state: PlatformState, context: RequestSession) -> str:
    if context.workspace_id == "default":
        return "server" if context.user.platform_role == "admin" else "none"
    if context.user.platform_role == "admin":
        return "workspace"
    try:
        membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=context.workspace_id)
    except WorkspaceMembershipError:
        return "none"
    if membership.status == "active" and membership.role == "admin":
        return "workspace"
    return "none"


def _runtime_cleanup_workspace_ids(state: PlatformState, context: RequestSession) -> set[str]:
    scope = _runtime_cleanup_scope(state, context)
    if scope == "server":
        return {workspace.workspace_id for workspace in state.workspace_store.list_workspaces()}
    if scope == "workspace":
        return {context.workspace_id}
    return set()


def _runtime_session_settings_payload(state: PlatformState, session: RuntimeSessionRecord) -> dict[str, object]:
    try:
        workspace_name = state.workspace_store.get_workspace(session.workspace_id).name
    except Exception:
        workspace_name = session.workspace_id
    return {
        "session_id": session.session_id,
        "workspace_id": session.workspace_id,
        "workspace_name": workspace_name,
        "agent_id": session.agent_id,
        "source_app_id": session.source_app_id,
        "skill_catalog_app_id": session.skill_catalog_app_id,
        "provider_id": session.provider_id,
        "provider_thread_id": session.provider_thread_id,
        "status": session.status,
        "requested_mode": session.requested_mode,
        "effective_mode": session.effective_mode,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
        "last_progress_at": session.last_progress_at,
    }


def runtime_session_inventory(state: PlatformState, context: RequestSession) -> list[dict[str, object]]:
    """Return runtime sessions in the cleanup scope of the current workspace."""
    sessions = _scoped_runtime_sessions(state, context)
    sessions.sort(key=lambda session: (session.workspace_id, session.updated_at, session.session_id), reverse=True)
    return [_runtime_session_settings_payload(state, session) for session in sessions]


def _scoped_runtime_sessions(state: PlatformState, context: RequestSession) -> list[RuntimeSessionRecord]:
    visible_workspace_ids = _runtime_cleanup_workspace_ids(state, context)
    return [
        session
        for session in state.runtime_store.list_all_sessions()
        if session.workspace_id in visible_workspace_ids
    ]


def _runtime_cleanup_forbidden(state: PlatformState, context: RequestSession) -> tuple[int, dict[str, object]] | None:
    if _runtime_cleanup_scope(state, context) != "none":
        return None
    return 403, {"error": "runtime_cleanup_forbidden"}


def _patch_workspace_governance(state: PlatformState, context: RequestSession, body: dict) -> dict[str, object]:
    try:
        require_governance_management(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
    except AuthorizationError as error:
        return {"error": error.reason}
    governance = state.workspace_store.get_governance(context.workspace_id)
    patch = {
        key: bool(body[key])
        for key in GOVERNANCE_PATCH_FIELDS
        if key in body
    }
    updated = replace(governance, **patch) if patch else governance
    saved = state.workspace_store.save_governance(updated)
    return {"workspace_id": context.workspace_id, "governance": asdict(saved)}


def _record_workspace_health(state: PlatformState, context: RequestSession, body: dict) -> dict[str, object]:
    target_kind = str(body.get("target_kind") or "provider")
    if target_kind == "runtime":
        session_id = str(body.get("session_id") or "")
        try:
            session = state.runtime_store.get_session(session_id)
        except (RuntimeSessionNotFoundError, ValueError):
            return {"error": "runtime_session_not_found"}
        return {"result": asdict(record_runtime_health(state.recovery_store, session=session))}
    provider_id = str(body.get("provider_id") or "")
    if not provider_id:
        provider_status = workspace_provider_status(state, workspace_id=context.workspace_id)
        active_provider = provider_status.get("active_provider")
        if not isinstance(active_provider, dict):
            return {
                "error": "provider_unavailable",
                "blocked_reason": provider_status.get("blocked_reason") or "provider_unavailable",
                "provider_status": provider_status,
            }
        provider_id = str(active_provider["provider_id"])
    result = record_provider_health(
        state.recovery_store,
        provider_registry=builtin_provider_registry(),
        provider_id=provider_id,
        workspace_id=context.workspace_id,
        observability_store=state.observability_store,
    )
    return {"result": asdict(result)}


def _clear_visible_runtime_sessions(state: PlatformState, context: RequestSession, body: dict) -> tuple[int, dict[str, object]]:
    forbidden = _runtime_cleanup_forbidden(state, context)
    if forbidden is not None:
        return forbidden
    requested_ids = body.get("session_ids")
    requested_session_ids = {
        str(session_id).strip()
        for session_id in requested_ids
        if str(session_id).strip()
    } if isinstance(requested_ids, list) else set()
    session_id = str(body.get("session_id") or "").strip()
    if session_id:
        requested_session_ids.add(session_id)
    sessions = _scoped_runtime_sessions(state, context)
    if requested_session_ids:
        sessions = [session for session in sessions if session.session_id in requested_session_ids]
    if requested_session_ids and not sessions and len(requested_session_ids) == 1:
        return 404, {"error": "runtime_session_not_found"}
    reason = str(body.get("reason") or "settings_runtime_sessions_cleared")
    deleted_totals = {"sessions": 0, "turns": 0, "events": 0, "processes": 0, "states": 0}
    terminated_processes = 0
    cancelled_turns = 0
    deleted_threads = 0
    deleted_thread_ids: list[str] = []
    runtime_roots_deleted = 0
    results = []
    for session in sessions:
        try:
            cleanup = cleanup_runtime_session(
                state,
                session_id=session.session_id,
                reason=reason,
                start_path=state.repository_root,
            )
        except RuntimeCleanupError as error:
            return 500, {"error": str(error)}
        deleted = cleanup.get("deleted") if isinstance(cleanup.get("deleted"), dict) else {}
        for key, value in deleted.items():
            deleted_totals[key] = deleted_totals.get(key, 0) + int(value or 0)
        terminated_processes += int(cleanup.get("terminated_processes") or 0)
        cancelled_turns += int(cleanup.get("cancelled_turns") or 0)
        deleted_threads += int(cleanup.get("deleted_threads") or 0)
        deleted_thread_ids.extend(
            thread_id
            for thread_id in cleanup.get("deleted_thread_ids", [])
            if isinstance(thread_id, str) and thread_id
        )
        runtime_roots_deleted += 1 if cleanup.get("runtime_root_deleted") else 0
        results.append(
            {
                "session_id": session.session_id,
                "workspace_id": session.workspace_id,
                "deleted": deleted,
                "deleted_threads": int(cleanup.get("deleted_threads") or 0),
                "runtime_root_deleted": bool(cleanup.get("runtime_root_deleted")),
            }
        )
    return 200, {
        "cleared_sessions": len(results),
        "terminated_processes": terminated_processes,
        "cancelled_turns": cancelled_turns,
        "deleted_threads": deleted_threads,
        "deleted_thread_ids": deleted_thread_ids,
        "runtime_roots_deleted": runtime_roots_deleted,
        "deleted": deleted_totals,
        "results": results,
        "sessions": runtime_session_inventory(state, context),
    }


def handle_settings_api(state: PlatformState, environ: dict, start_response: StartResponse) -> list[bytes] | None:
    """Handle platform settings and recovery routes."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    owned_paths = {
        "/api/settings/platform",
        "/api/settings/workspace",
        "/api/settings/runtime-sessions",
        "/api/settings/runtime-sessions/clear",
        "/api/recovery/status",
        "/api/recovery/health",
        "/api/recovery/restart-runtime",
    }
    if path not in owned_paths:
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if path == "/api/settings/platform" and method == "GET":
        return json_response(start_response, platform_settings_payload(state, context))
    if path == "/api/settings/runtime-sessions" and method == "GET":
        return json_response(
            start_response,
            {
                "items": runtime_session_inventory(state, context),
                "cleanup_allowed": _runtime_cleanup_scope(state, context) != "none",
                "cleanup_scope": _runtime_cleanup_scope(state, context),
            },
        )
    if path == "/api/settings/runtime-sessions/clear" and method == "POST":
        status_code, payload = _clear_visible_runtime_sessions(state, context, read_json_body(environ))
        if status_code == 200:
            status = "200 OK"
        elif status_code == 403:
            status = "403 Forbidden"
        elif status_code == 404:
            status = "404 Not Found"
        else:
            status = "500 Internal Server Error" if status_code == 500 else "400 Bad Request"
        return json_response(start_response, payload, status=status)
    if path == "/api/settings/workspace" and method == "PATCH":
        payload = _patch_workspace_governance(state, context, read_json_body(environ))
        status = "403 Forbidden" if "error" in payload else "200 OK"
        return json_response(start_response, payload, status=status)
    if path == "/api/recovery/status" and method == "GET":
        return json_response(start_response, recovery_status(state.recovery_store, workspace_id=context.workspace_id))
    if path == "/api/recovery/health" and method == "POST":
        payload = _record_workspace_health(state, context, read_json_body(environ))
        status = "404 Not Found" if "error" in payload else "200 OK"
        return json_response(start_response, payload, status=status)
    if path == "/api/recovery/restart-runtime" and method == "POST":
        body = read_json_body(environ)
        session_id = str(body.get("session_id") or "")
        try:
            session = state.runtime_store.get_session(session_id)
        except (RuntimeSessionNotFoundError, ValueError):
            return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
        try:
            if session.workspace_id != context.workspace_id:
                return json_response(start_response, {"error": "runtime_session_not_found"}, status="404 Not Found")
            require_runtime_session_operation(
                workspace_store=state.workspace_store,
                user=context.user,
                session=session,
                operation="restart",
            )
            intent, session = execute_session_restart(
                state.recovery_store,
                runtime_store=state.runtime_store,
                session_id=session_id,
                reason=str(body.get("reason") or "operator requested restart"),
                observability_store=state.observability_store,
            )
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        return json_response(start_response, {"intent": asdict(intent), "session": asdict(session)})

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
