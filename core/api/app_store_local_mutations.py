"""Workspace-local mutation handlers for the authenticated App Store API."""

from __future__ import annotations

from pathlib import Path

from core.api.app_store_installations import _app_id_and_workspaces
from core.api.app_store_visibility import _authorize_app_management_targets, _authorize_platform_admin, _authorize_workspace_local_app_targets
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.apps.errors import AppHostingError
from core.apps.paths import workspace_app_source_root
from core.apps.service import (
    delete_workspace_local_app_project,
    promote_workspace_local_app_project,
    register_workspace_local_app_project_from_contract,
    uninstall_workspace_app,
)
from core.apps.workspace_local_discovery import discover_workspace_local_app_projects
from core.workspaces.errors import WorkspaceNotFoundError


def register_local(
    state: PlatformState,
    context: RequestSession,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes]:
    body = read_json_body(environ)
    parsed = _app_id_and_workspaces(body, context, start_response)
    if not isinstance(parsed, tuple):
        return parsed
    app_id, workspace_ids = parsed
    authorization_error = _authorize_workspace_local_app_targets(state, context, workspace_ids)
    if len(workspace_ids) != 1:
        return json_response(start_response, {"error": "single_workspace_required"}, status="400 Bad Request")
    if authorization_error is not None:
        return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
    project_root = workspace_app_source_root(workspace_id=workspace_ids[0], app_id=app_id, start_path=start_path)
    try:
        project = register_workspace_local_app_project_from_contract(
            state.app_store,
            workspace_id=workspace_ids[0],
            project_root=str(project_root),
            owner_user_id=context.user.user_id,
            owner_username=context.user.username,
        )
    except (AppHostingError, WorkspaceNotFoundError) as error:
        return json_response(start_response, {"error": "register_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(
        start_response,
        {
            "workspace_id": project.workspace_id,
            "project_id": project.project_id,
            "app_id": project.app_id,
            "name": project.name,
            "version": project.version,
            "project_root": project.project_root,
            "status": "registered",
            "source_kind": "workspace_local_project",
        },
        status="201 Created",
    )


def promote_local(
    state: PlatformState,
    context: RequestSession,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes]:
    body = read_json_body(environ)
    parsed = _app_id_and_workspaces(body, context, start_response)
    if not isinstance(parsed, tuple):
        return parsed
    app_id, workspace_ids = parsed
    promotion_mode = str(body.get("promotion_mode") or "forkable").strip().lower()
    authorization_error = _authorize_platform_admin(context)
    if len(workspace_ids) != 1:
        return json_response(start_response, {"error": "single_workspace_required"}, status="400 Bad Request")
    if authorization_error is not None:
        return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
    if promotion_mode not in {"sealed", "forkable"}:
        return json_response(start_response, {"error": "invalid_promotion_mode"}, status="400 Bad Request")
    try:
        result = promote_workspace_local_app_project(
            state.app_store,
            workspace_id=workspace_ids[0],
            app_id=app_id,
            promotion_mode=promotion_mode,
            start_path=start_path,
            actor_user_id=context.user.user_id,
            actor_username=context.user.username,
        )
    except (AppHostingError, WorkspaceNotFoundError) as error:
        return json_response(start_response, {"error": "promotion_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(start_response, result, status="201 Created")


def delete_local(
    state: PlatformState,
    context: RequestSession,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes]:
    body = read_json_body(environ)
    parsed = _app_id_and_workspaces(body, context, start_response)
    if not isinstance(parsed, tuple):
        return parsed
    app_id, workspace_ids = parsed
    authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
    if authorization_error is not None:
        return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
    try:
        items = []
        for workspace_id in workspace_ids:
            discover_workspace_local_app_projects(state.app_store, workspace_id=workspace_id, start_path=start_path)
            items.append(
                delete_workspace_local_app_project(
                    state.app_store,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    start_path=start_path,
                    observability_store=state.observability_store,
                )
            )
    except (AppHostingError, WorkspaceNotFoundError) as error:
        return json_response(start_response, {"error": "delete_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(
        start_response,
        {
            "app": {"app_id": app_id},
            "workspace_ids": workspace_ids,
            "status": "deleted",
            "items": items,
        },
    )


def uninstall(
    state: PlatformState,
    context: RequestSession,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes]:
    body = read_json_body(environ)
    parsed = _app_id_and_workspaces(body, context, start_response)
    if not isinstance(parsed, tuple):
        return parsed
    app_id, workspace_ids = parsed
    authorization_error = _authorize_app_management_targets(state, context, workspace_ids)
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
        return json_response(start_response, {"error": "uninstall_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(
        start_response,
        {
            "app": {"app_id": app_id},
            "workspace_ids": workspace_ids,
            "status": "uninstalled",
        },
    )
