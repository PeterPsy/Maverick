"""Workspace HTTP API for the hosted platform shell."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.apps.builtin_apps import register_and_install_builtin_apps
from core.observability.service import record_platform_audit, record_platform_event
from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError
from core.workspaces.service import create_workspace, ensure_workspace_layout, set_active_workspace_for_user


def workspace_payload(state: PlatformState, workspace_id: str) -> dict[str, object]:
    """Return one workspace with governance and quota metadata."""
    workspace = state.workspace_store.get_workspace(workspace_id)
    governance = state.workspace_store.get_governance(workspace_id)
    quota = state.workspace_store.get_quota(workspace_id)
    return {
        **asdict(workspace),
        "governance": asdict(governance),
        "quota": asdict(quota),
    }


def _list_user_workspaces(state: PlatformState, context: RequestSession) -> list[dict[str, object]]:
    memberships = state.workspace_store.list_memberships_for_user(context.user.user_id)
    return [
        {
            **workspace_payload(state, membership.workspace_id),
            "membership": asdict(membership),
            "is_active": membership.workspace_id == context.workspace_id,
        }
        for membership in memberships
        if membership.status == "active"
    ]


def handle_workspace_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle workspace routes, returning None when the path is not owned here."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path not in {"/api/workspaces", "/api/workspaces/active"}:
        return None

    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if path == "/api/workspaces" and method == "GET":
        return json_response(
            start_response,
            {"items": _list_user_workspaces(state, context), "active_workspace_id": context.workspace_id},
        )
    if path == "/api/workspaces" and method == "POST":
        if context.user.platform_role != "admin":
            return json_response(start_response, {"error": "admin_required"}, status="403 Forbidden")
        body = read_json_body(environ)
        name = str(body.get("name") or "").strip()
        if not name:
            return json_response(start_response, {"error": "workspace_name_required"}, status="400 Bad Request")
        workspace = create_workspace(
            state.workspace_store,
            name=name,
            description=body.get("description") if isinstance(body.get("description"), str) else None,
            created_by_user_id=context.user.user_id,
            creator_role="admin",
        )
        ensure_workspace_layout(workspace.workspace_id, start_path=start_path)
        register_and_install_builtin_apps(
            state.app_store,
            state.workspace_store,
            workspace_id=workspace.workspace_id,
            start_path=start_path,
            observability_store=state.observability_store,
        )
        record_platform_audit(
            state.observability_store,
            action="workspace.create",
            status="succeeded",
            source_domain="workspaces",
            detail=f"Created workspace `{workspace.workspace_id}`.",
            workspace_id=workspace.workspace_id,
            payload={"workspace_id": workspace.workspace_id, "created_by_user_id": context.user.user_id},
        )
        record_platform_event(
            state.observability_store,
            event_type="workspace.created",
            event_plane="platform",
            source_domain="workspaces",
            workspace_id=workspace.workspace_id,
            payload={"workspace_id": workspace.workspace_id, "created_by_user_id": context.user.user_id},
        )
        return json_response(start_response, workspace_payload(state, workspace.workspace_id), status="201 Created")

    if path == "/api/workspaces/active" and method == "POST":
        body = read_json_body(environ)
        workspace_id = str(body.get("workspace_id") or "").strip()
        try:
            state.workspace_store.get_workspace(workspace_id)
            membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=workspace_id)
        except (WorkspaceNotFoundError, WorkspaceMembershipError):
            return json_response(start_response, {"error": "workspace_not_available"}, status="404 Not Found")
        if membership.status != "active":
            return json_response(start_response, {"error": "workspace_not_available"}, status="403 Forbidden")
        set_active_workspace_for_user(state.workspace_store, user_id=context.user.user_id, workspace_id=workspace_id)
        return json_response(start_response, {"active_workspace_id": workspace_id})

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
