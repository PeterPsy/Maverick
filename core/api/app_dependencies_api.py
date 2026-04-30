"""HTTP API for generic cross-app interface dependency resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.api.http import StartResponse, json_response, query_params, read_json_body
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.apps.dependencies import resolve_app_dependencies, save_app_dependency_selection
from core.apps.errors import AppHostingError
from core.authorization.errors import AuthorizationError
from core.authorization.service import require_app_dependency_management
from core.observability.service import record_platform_audit, record_platform_event


def _require_dependency_session(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
) -> RequestSession | list[bytes]:
    return require_session(state, environ, start_response)


def _provider_ids(body: dict[str, Any]) -> list[str]:
    value = body.get("provider_app_ids")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def handle_app_dependencies_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle generic app dependency status and selection routes."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path != "/api/apps/dependencies":
        return None

    context_or_response = _require_dependency_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response

    if method == "GET":
        query = query_params(environ)
        consumer_app_id = str(query.get("consumer_app_id") or "").strip()
        if not consumer_app_id:
            return json_response(start_response, {"error": "consumer_app_id_required"}, status="400 Bad Request")
        try:
            payload = resolve_app_dependencies(
                state.app_store,
                workspace_id=context.workspace_id,
                consumer_app_id=consumer_app_id,
                user=context.user,
                workspace_store=state.workspace_store,
                start_path=start_path,
            )
        except AppHostingError as error:
            return json_response(start_response, {"error": "dependency_resolution_failed", "detail": str(error)}, status="400 Bad Request")
        record_platform_event(
            state.observability_store,
            event_type="apps.dependencies.lookup",
            event_plane="app",
            source_domain="apps.dependencies",
            workspace_id=context.workspace_id,
            app_id=consumer_app_id,
            payload={"status": payload.get("status")},
        )
        return json_response(start_response, payload)

    if method == "POST":
        body = read_json_body(environ)
        consumer_app_id = str(body.get("consumer_app_id") or "").strip()
        alias = str(body.get("alias") or "").strip()
        if not consumer_app_id or not alias:
            return json_response(start_response, {"error": "consumer_app_id_and_alias_required"}, status="400 Bad Request")
        try:
            require_app_dependency_management(state.workspace_store, user=context.user, workspace_id=context.workspace_id)
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
        try:
            payload = save_app_dependency_selection(
                state.app_store,
                workspace_id=context.workspace_id,
                consumer_app_id=consumer_app_id,
                alias=alias,
                provider_app_ids=_provider_ids(body),
                user=context.user,
                workspace_store=state.workspace_store,
                start_path=start_path,
            )
        except AppHostingError as error:
            record_platform_audit(
                state.observability_store,
                action="apps.dependencies.configure",
                status="denied",
                source_domain="apps.dependencies",
                detail=str(error),
                workspace_id=context.workspace_id,
                app_id=consumer_app_id,
                payload={"alias": alias},
            )
            return json_response(start_response, {"error": "dependency_selection_failed", "detail": str(error)}, status="400 Bad Request")
        record_platform_audit(
            state.observability_store,
            action="apps.dependencies.configure",
            status="succeeded",
            source_domain="apps.dependencies",
            detail=f"Configured dependency alias `{alias}` for app `{consumer_app_id}`.",
            workspace_id=context.workspace_id,
            app_id=consumer_app_id,
            payload={"alias": alias, "provider_app_ids": _provider_ids(body)},
        )
        return json_response(start_response, payload)

    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
