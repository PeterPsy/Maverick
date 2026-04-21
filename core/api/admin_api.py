"""Admin-only HTTP API for identity and workspace access management."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.api.admin_app_management import handle_admin_app_management_api
from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, public_user_payload, require_session
from core.identity.errors import UserNotFoundError
from core.identity.service import UNSET, create_user, delete_user, is_last_active_admin, set_user_password, update_user
from core.observability.service import record_platform_audit, record_platform_event
from core.workspaces.errors import WorkspaceNotFoundError
from core.workspaces.service import ensure_workspace_membership


def _admin_context(state: PlatformState, environ: dict, start_response: StartResponse) -> RequestSession | list[bytes]:
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    if context_or_response.user.platform_role != "admin":
        return json_response(start_response, {"error": "admin_required"}, status="403 Forbidden")
    return context_or_response


def _user_payload(state: PlatformState, user_id: str) -> dict[str, object]:
    user = state.identity_store.get_user(user_id)
    memberships = state.workspace_store.list_memberships_for_user(user_id)
    return {
        **public_user_payload(user),
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "memberships": [asdict(membership) for membership in memberships],
    }


def _workspace_payloads(state: PlatformState) -> list[dict[str, object]]:
    return [
        {
            **asdict(workspace),
            "memberships": [
                asdict(membership)
                for membership in state.workspace_store.list_memberships_for_workspace(workspace.workspace_id)
            ],
        }
        for workspace in state.workspace_store.list_workspaces()
    ]


def _audit_admin_action(
    state: PlatformState,
    *,
    action: str,
    actor_user_id: str,
    target_user_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    detail_target = f" for `{target_user_id}`" if target_user_id else ""
    record_platform_audit(
        state.observability_store,
        action=action,
        status="succeeded",
        source_domain="identity",
        detail=f"Admin `{actor_user_id}` performed `{action}`{detail_target}.",
        payload={"actor_user_id": actor_user_id, **(payload or {})},
    )
    record_platform_event(
        state.observability_store,
        event_type=f"{action}.succeeded",
        event_plane="platform",
        source_domain="identity",
        payload={"actor_user_id": actor_user_id, **(payload or {})},
    )


def _handle_users_collection(
    state: PlatformState,
    context: RequestSession,
    method: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    if method == "GET":
        users = sorted(state.identity_store.list_users(), key=lambda user: user.username)
        return json_response(start_response, {"items": [_user_payload(state, user.user_id) for user in users]})
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    try:
        user = create_user(
            state.identity_store,
            username=str(body.get("username") or ""),
            password=str(body.get("password") or ""),
            email=body.get("email") if isinstance(body.get("email"), str) else None,
            display_name=body.get("display_name") if isinstance(body.get("display_name"), str) else None,
            account_type=body.get("account_type", "standard"),
            platform_role=body.get("platform_role", "member"),
        )
    except ValueError as error:
        return json_response(start_response, {"error": "invalid_user", "detail": str(error)}, status="400 Bad Request")
    _audit_admin_action(
        state,
        action="identity.user.create",
        actor_user_id=context.user.user_id,
        target_user_id=user.user_id,
        payload={"user_id": user.user_id, "username": user.username, "platform_role": user.platform_role},
    )
    return json_response(start_response, _user_payload(state, user.user_id), status="201 Created")


def _handle_user_record(
    state: PlatformState,
    context: RequestSession,
    user_id: str,
    method: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    try:
        user = state.identity_store.get_user(user_id)
    except UserNotFoundError:
        return json_response(start_response, {"error": "user_not_found"}, status="404 Not Found")
    if method == "GET":
        return json_response(start_response, _user_payload(state, user_id))
    if method == "DELETE":
        if user_id == context.user.user_id:
            return json_response(
                start_response,
                {"error": "cannot_delete_current_user"},
                status="400 Bad Request",
            )
        if is_last_active_admin(state.identity_store, user):
            return json_response(
                start_response,
                {"error": "cannot_delete_last_admin"},
                status="400 Bad Request",
            )
        deleted = delete_user(state.identity_store, state.workspace_store, user_id=user_id)
        _audit_admin_action(
            state,
            action="identity.user.delete",
            actor_user_id=context.user.user_id,
            target_user_id=user_id,
            payload={"user_id": user_id, "username": deleted.username, "platform_role": deleted.platform_role},
        )
        return json_response(start_response, {"status": "deleted", "user_id": user_id})
    if method != "PATCH":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    target_platform_role = body["platform_role"] if "platform_role" in body else user.platform_role
    target_is_active = bool(body["is_active"]) if "is_active" in body else user.is_active
    if is_last_active_admin(state.identity_store, user) and (
        target_platform_role != "admin" or not target_is_active
    ):
        return json_response(
            start_response,
            {"error": "cannot_remove_last_admin"},
            status="400 Bad Request",
        )
    try:
        updated = update_user(
            state.identity_store,
            user_id=user_id,
            email=body["email"] if "email" in body else UNSET,
            display_name=body["display_name"] if "display_name" in body else UNSET,
            account_type=body["account_type"] if "account_type" in body else UNSET,
            platform_role=body["platform_role"] if "platform_role" in body else UNSET,
            is_active=body["is_active"] if "is_active" in body else UNSET,
        )
    except ValueError as error:
        return json_response(start_response, {"error": "invalid_user_update", "detail": str(error)}, status="400 Bad Request")
    _audit_admin_action(
        state,
        action="identity.user.update",
        actor_user_id=context.user.user_id,
        target_user_id=user_id,
        payload={"user_id": user_id, "platform_role": updated.platform_role, "is_active": updated.is_active},
    )
    return json_response(start_response, _user_payload(state, user_id))


def _handle_user_password(
    state: PlatformState,
    context: RequestSession,
    user_id: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    try:
        set_user_password(state.identity_store, user_id=user_id, password=str(body.get("password") or ""))
    except UserNotFoundError:
        return json_response(start_response, {"error": "user_not_found"}, status="404 Not Found")
    except ValueError as error:
        return json_response(start_response, {"error": "invalid_password", "detail": str(error)}, status="400 Bad Request")
    _audit_admin_action(
        state,
        action="identity.user.password_reset",
        actor_user_id=context.user.user_id,
        target_user_id=user_id,
        payload={"user_id": user_id},
    )
    return json_response(start_response, {"status": "updated", "user_id": user_id})


def _handle_user_workspaces(
    state: PlatformState,
    context: RequestSession,
    user_id: str,
    body: dict,
    start_response: StartResponse,
) -> list[bytes]:
    try:
        state.identity_store.get_user(user_id)
    except UserNotFoundError:
        return json_response(start_response, {"error": "user_not_found"}, status="404 Not Found")
    memberships = body.get("memberships")
    if not isinstance(memberships, list):
        return json_response(start_response, {"error": "memberships_required"}, status="400 Bad Request")
    for item in memberships:
        if not isinstance(item, dict):
            return json_response(start_response, {"error": "invalid_membership"}, status="400 Bad Request")
        workspace_id = str(item.get("workspace_id") or "").strip()
        role = str(item.get("role") or "member").strip()
        try:
            state.workspace_store.get_workspace(workspace_id)
        except WorkspaceNotFoundError:
            return json_response(start_response, {"error": "workspace_not_found", "workspace_id": workspace_id}, status="404 Not Found")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{workspace_id}:{user_id}",
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )
    _audit_admin_action(
        state,
        action="identity.user.workspace_assign",
        actor_user_id=context.user.user_id,
        target_user_id=user_id,
        payload={"user_id": user_id, "workspace_ids": [item.get("workspace_id") for item in memberships if isinstance(item, dict)]},
    )
    return json_response(start_response, _user_payload(state, user_id))


def handle_admin_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle admin routes, returning None when the path is not owned here."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if not path.startswith("/api/admin/"):
        return None
    context_or_response = _admin_context(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    body = read_json_body(environ) if method in {"POST", "PATCH", "PUT"} else {}

    routed = handle_admin_app_management_api(
        state,
        context,
        environ,
        start_response,
        body=body,
        start_path=start_path,
    )
    if routed is not None:
        return routed

    if path == "/api/admin/users":
        return _handle_users_collection(state, context, method, body, start_response)
    if path == "/api/admin/workspaces" and method == "GET":
        return json_response(start_response, {"items": _workspace_payloads(state)})

    prefix = "/api/admin/users/"
    if path.startswith(prefix):
        suffix = path.removeprefix(prefix).strip("/")
        if suffix.endswith("/password") and method == "POST":
            return _handle_user_password(state, context, suffix.removesuffix("/password").strip("/"), body, start_response)
        if suffix.endswith("/workspaces") and method == "PUT":
            return _handle_user_workspaces(state, context, suffix.removesuffix("/workspaces").strip("/"), body, start_response)
        return _handle_user_record(state, context, suffix, method, body, start_response)

    return json_response(start_response, {"error": "not_found"}, status=status_line(404))
