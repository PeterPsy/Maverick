"""Install mutation handlers for the authenticated App Store API."""

from __future__ import annotations

from pathlib import Path

from core.api.app_store_payloads import _server_source_for_install
from core.api.app_store_requests import _catalog_base_url, _safe_app_id_response, _workspace_ids_from_body
from core.api.app_store_visibility import (
    _authorize_app_management_targets,
    _authorize_workspace_local_app_targets,
    _unique_workspace_ids,
)
from core.api.http import StartResponse, json_response, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession
from core.apps.errors import AppHostingError
from core.apps.remote_store import install_remote_store_app
from core.apps.service import install_store_app, install_workspace_local_app
from core.apps.workspace_local_discovery import discover_workspace_local_app_projects
from core.workspaces.errors import WorkspaceNotFoundError


def _app_id_and_workspaces(
    body: dict,
    context: RequestSession,
    start_response: StartResponse,
) -> tuple[str, list[str]] | list[bytes]:
    app_id_or_response = _safe_app_id_response(str(body.get("app_id") or "").strip(), start_response)
    if not isinstance(app_id_or_response, str):
        return app_id_or_response
    return app_id_or_response, _unique_workspace_ids(_workspace_ids_from_body(body, context))


def install_remote(
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
        result = install_remote_store_app(
            state.app_store,
            state.workspace_store,
            catalog_base_url=_catalog_base_url(),
            app_id=app_id,
            version=str(body.get("version") or "").strip() or None,
            workspace_ids=workspace_ids,
            start_path=start_path,
            observability_store=state.observability_store,
        )
    except (AppHostingError, WorkspaceNotFoundError) as error:
        return json_response(start_response, {"error": "install_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(start_response, result, status="201 Created")


def install_server(
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
        source = _server_source_for_install(
            state,
            context,
            app_id=app_id,
            source_id=str(body.get("source_id") or "").strip() or None,
        )
        bindings = []
        for workspace_id in workspace_ids:
            binding = install_store_app(
                state.app_store,
                source_id=source.source_id,
                workspace_id=workspace_id,
                start_path=start_path,
                observability_store=state.observability_store,
            )
            bindings.append(_binding_payload(binding))
    except (AppHostingError, WorkspaceNotFoundError) as error:
        return json_response(start_response, {"error": "install_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(
        start_response,
        {
            "app": {"app_id": source.app_id},
            "workspace_ids": workspace_ids,
            "status": "installed",
            "source_id": source.source_id,
            "source_kind": source.source_kind,
            "items": bindings,
        },
        status="201 Created",
    )


def install_local(
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
    if authorization_error is not None:
        return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")
    try:
        bindings = []
        for workspace_id in workspace_ids:
            discover_workspace_local_app_projects(state.app_store, workspace_id=workspace_id, start_path=start_path)
            binding = install_workspace_local_app(
                state.app_store,
                workspace_id=workspace_id,
                app_id=app_id,
                start_path=start_path,
                observability_store=state.observability_store,
            )
            bindings.append(_binding_payload(binding))
    except (AppHostingError, WorkspaceNotFoundError) as error:
        return json_response(start_response, {"error": "install_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(
        start_response,
        {
            "app": {"app_id": app_id},
            "workspace_ids": workspace_ids,
            "status": "installed",
            "source_kind": "workspace_local_project",
            "items": bindings,
        },
        status="201 Created",
    )


def _binding_payload(binding) -> dict[str, object]:
    return {
        "workspace_id": binding.workspace_id,
        "app_id": binding.app_id,
        "status": binding.status,
        "active_version": binding.active_version,
        "source_kind": binding.source_kind,
        "source_record_id": binding.source_record_id,
    }
