"""Authenticated Maverick App Store API surface."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path

from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.apps.errors import AppHostingError
from core.apps.remote_store import fetch_remote_catalog, install_remote_store_app
from core.apps.service import uninstall_workspace_app
from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError


DEFAULT_APP_STORE_URL = "https://maverick-app-store.versy.ai"


def _catalog_base_url() -> str:
    return os.environ.get("MAVERICK_APP_STORE_URL", DEFAULT_APP_STORE_URL).strip().rstrip("/")


def _authorize_app_management_targets(state: PlatformState, context: RequestSession, workspace_ids: list[str]) -> str | None:
    if not workspace_ids:
        return "workspace_required"
    unique_ids = []
    for workspace_id in workspace_ids:
        if workspace_id and workspace_id not in unique_ids:
            unique_ids.append(workspace_id)
    if len(unique_ids) != len(workspace_ids):
        return "duplicate_workspace"
    for workspace_id in unique_ids:
        try:
            workspace = state.workspace_store.get_workspace(workspace_id)
            membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=workspace_id)
            governance = state.workspace_store.get_governance(workspace_id)
        except (WorkspaceNotFoundError, WorkspaceMembershipError):
            return "workspace_not_available"
        if workspace.status != "active" or membership.status != "active":
            return "workspace_not_available"
        if context.user.platform_role != "admin" and membership.role != "admin":
            return "workspace_admin_required"
        if not governance.allow_app_installation:
            return "app_installation_disabled"
    return None


def _unique_workspace_ids(workspace_ids: list[str]) -> list[str]:
    unique_ids = []
    for workspace_id in workspace_ids:
        if workspace_id and workspace_id not in unique_ids:
            unique_ids.append(workspace_id)
    return unique_ids


def _user_workspace_ids(state: PlatformState, context: RequestSession) -> list[str]:
    memberships = state.workspace_store.list_memberships_for_user(context.user.user_id)
    return [
        membership.workspace_id
        for membership in memberships
        if membership.status == "active"
    ]


def _installation_payload(state: PlatformState, workspace_ids: list[str]) -> dict[str, object]:
    items = []
    for workspace_id in workspace_ids:
        for binding in state.app_store.list_workspace_app_bindings(workspace_id):
            items.append(
                {
                    "workspace_id": workspace_id,
                    "app_id": binding.app_id,
                    "status": binding.status,
                    "active_version": binding.active_version,
                    "source_kind": binding.source_kind,
                    "source_record_id": binding.source_record_id,
                }
            )
    return {"items": items}


def _local_apps_payload(state: PlatformState, workspace_ids: list[str]) -> list[dict[str, object]]:
    items = []
    for workspace_id in workspace_ids:
        bindings = {
            binding.app_id: binding
            for binding in state.app_store.list_workspace_app_bindings(workspace_id)
        }
        for project in state.app_store.list_workspace_local_app_projects(workspace_id):
            binding = bindings.get(project.app_id)
            items.append(
                {
                    "workspace_id": workspace_id,
                    "project_id": project.project_id,
                    "app_id": project.app_id,
                    "name": project.name,
                    "version": project.version,
                    "description": project.description,
                    "publisher": project.publisher,
                    "project_root": project.project_root,
                    "distribution": asdict(project.contract.distribution),
                    "installed": binding is not None,
                    "status": binding.status if binding else "uninstalled",
                    "active_version": binding.active_version if binding else None,
                    "binding_source_kind": binding.source_kind if binding else None,
                }
            )
    return items


def _workspace_ids_from_body(body: dict, context: RequestSession) -> list[str]:
    raw_workspace_ids = body.get("workspace_ids")
    if raw_workspace_ids is None:
        return [context.workspace_id]
    if not isinstance(raw_workspace_ids, list):
        return []
    return [str(workspace_id).strip() for workspace_id in raw_workspace_ids if str(workspace_id).strip()]


def handle_app_store_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle authenticated app-store routes, returning None when not owned here."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path not in {
        "/api/app-store/apps",
        "/api/app-store/install",
        "/api/app-store/installations",
        "/api/app-store/uninstall",
    }:
        return None

    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if path == "/api/app-store/apps" and method == "GET":
        try:
            catalog = fetch_remote_catalog(_catalog_base_url())
        except Exception as error:
            return json_response(
                start_response,
                {"error": "catalog_unavailable", "detail": str(error)},
                status=status_line(500),
            )
        return json_response(start_response, catalog)

    if path == "/api/app-store/installations" and method == "GET":
        workspace_ids = _user_workspace_ids(state, context)
        payload = _installation_payload(state, workspace_ids)
        payload["local_apps"] = _local_apps_payload(state, workspace_ids)
        return json_response(start_response, payload)

    if path == "/api/app-store/install" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        version = str(body.get("version") or "").strip() or None
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        try:
            result = install_remote_store_app(
                state.app_store,
                state.workspace_store,
                catalog_base_url=_catalog_base_url(),
                app_id=app_id,
                version=version,
                workspace_ids=workspace_ids,
                start_path=start_path,
                observability_store=state.observability_store,
            )
        except (AppHostingError, WorkspaceNotFoundError) as error:
            return json_response(
                start_response,
                {"error": "install_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(start_response, result, status="201 Created")

    if path == "/api/app-store/uninstall" and method == "POST":
        body = read_json_body(environ)
        app_id = str(body.get("app_id") or "").strip()
        workspace_ids = _unique_workspace_ids(_workspace_ids_from_body(body, context))
        authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
        if not app_id:
            return json_response(start_response, {"error": "app_id_required"}, status="400 Bad Request")
        if authorization_error is not None:
            return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
        try:
            for workspace_id in workspace_ids:
                uninstall_workspace_app(
                    state.app_store,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    observability_store=state.observability_store,
                )
        except AppHostingError as error:
            return json_response(
                start_response,
                {"error": "uninstall_failed", "detail": str(error)},
                status="400 Bad Request",
            )
        return json_response(
            start_response,
            {
                "app": {"app_id": app_id},
                "workspace_ids": workspace_ids,
                "status": "uninstalled",
            },
        )

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
