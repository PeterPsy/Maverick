"""Workspace-scoped HTTP surface for the official Maverick App SDK."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.api.http import StartResponse, json_response, read_json_body, status_line
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, resolve_request_session
from core.app_sdk.errors import AppSdkError
from core.app_sdk.docs import sdk_docs_markdown
from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.packaging import package_app_source
from core.app_sdk.service import (
    app_sdk_status,
    create_app_source,
    install_local_app,
    register_local_app,
    validate_app_source,
)
from core.app_sdk.templates import SUPPORTED_TEMPLATES
from core.apps.errors import AppHostingError
from core.apps.paths import workspace_apps_root
from core.runtime.workspace_api_token import validate_workspace_api_token_lifecycle
from core.runtime.errors import RuntimeSessionNotFoundError
from core.workspaces.errors import WorkspaceMembershipError, WorkspaceNotFoundError
from core.workspaces.paths import workspace_paths


def handle_app_sdk_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
    *,
    start_path: Path,
) -> list[bytes] | None:
    """Handle authenticated SDK API requests."""
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if path != "/api/app-sdk":
        return None
    if method != "POST":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")

    identity = _resolve_sdk_identity(state, environ)
    if identity is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    workspace_id, context = identity

    body = read_json_body(environ)
    action = str(body.get("action") or "templates").strip()
    authorization_error = _authorize_sdk_action(state, workspace_id=workspace_id, context=context, action=action)
    if authorization_error is not None:
        return json_response(start_response, {"error": authorization_error}, status="403 Forbidden")

    try:
        if action == "templates":
            return json_response(start_response, {"workspace_id": workspace_id, "templates": sorted(SUPPORTED_TEMPLATES)})
        if action == "docs":
            return json_response(
                start_response,
                {
                    "workspace_id": workspace_id,
                    "format": "markdown",
                    "content": sdk_docs_markdown(),
                },
            )
        if action == "create":
            result = create_app_source(
                AppSdkCreateRequest(
                    app_id=str(body.get("app_id") or "").strip(),
                    template_id=str(body.get("template_id") or "minimal").strip(),
                    target_kind="workspace_local",
                    workspace_id=workspace_id,
                    name=_optional_string(body.get("name")),
                    description=_optional_string(body.get("description")),
                    publisher=str(body.get("publisher") or "workspace").strip() or "workspace",
                    overwrite=bool(body.get("overwrite", False)),
                    entities=_string_list(body.get("entities")),
                ),
                start_path=start_path,
            )
            return json_response(start_response, {"workspace_id": workspace_id, **asdict(result)}, status="201 Created")
        if action == "validate":
            app_id = _required_app_id(body)
            app_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path) / app_id
            return json_response(start_response, {"workspace_id": workspace_id, **asdict(validate_app_source(app_root))})
        if action == "register-local":
            app_id = _required_app_id(body)
            return json_response(
                start_response,
                register_local_app(state.app_store, workspace_id=workspace_id, app_id=app_id, start_path=start_path),
                status="201 Created",
            )
        if action == "install-local":
            app_id = _required_app_id(body)
            return json_response(
                start_response,
                install_local_app(
                    state.app_store,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    start_path=start_path,
                    observability_store=state.observability_store,
                ),
                status="201 Created",
            )
        if action == "status":
            app_id = _required_app_id(body)
            return json_response(start_response, asdict(app_sdk_status(state.app_store, workspace_id=workspace_id, app_id=app_id, start_path=start_path)))
        if action == "package":
            app_id = _required_app_id(body)
            paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
            app_root = paths.apps / app_id
            output_path = paths.generated_storage / f"{app_id}.tar.gz"
            return json_response(
                start_response,
                {"workspace_id": workspace_id, **asdict(package_app_source(app_root, output_path=output_path))},
                status="201 Created",
            )
    except (AppHostingError, AppSdkError, WorkspaceNotFoundError, ValueError) as error:
        return json_response(start_response, {"error": "sdk_action_failed", "detail": str(error)}, status=status_line(400))
    return json_response(start_response, {"error": "unsupported_action", "detail": f"Unsupported action `{action}`."}, status="400 Bad Request")


def _resolve_sdk_identity(state: PlatformState, environ: dict) -> tuple[str, RequestSession | None] | None:
    context = resolve_request_session(state, environ)
    if context is not None:
        return context.workspace_id, context
    header = str(environ.get("HTTP_AUTHORIZATION") or "").strip()
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    claims, _auth_error = validate_workspace_api_token_lifecycle(state.runtime_store, token.strip())
    if claims is None:
        return None
    try:
        session = state.runtime_store.get_session(str(claims["runtime_session_id"]))
    except (RuntimeSessionNotFoundError, ValueError):
        return None
    if session.workspace_id != str(claims["workspace_id"]) or session.status in {"stopped", "failed"}:
        return None
    if session.effective_mode != claims.get("mode"):
        return None
    return str(claims["workspace_id"]), None


def _authorize_sdk_action(
    state: PlatformState,
    *,
    workspace_id: str,
    context: RequestSession | None,
    action: str,
) -> str | None:
    try:
        workspace = state.workspace_store.get_workspace(workspace_id)
        governance = state.workspace_store.get_governance(workspace_id)
    except WorkspaceNotFoundError:
        return "workspace_not_available"
    if workspace.status != "active":
        return "workspace_not_available"
    if context is not None:
        try:
            membership = state.workspace_store.get_membership(user_id=context.user.user_id, workspace_id=workspace_id)
        except WorkspaceMembershipError:
            return "workspace_not_available"
        if membership.status != "active":
            return "workspace_not_available"
    if action in {"create", "validate", "register-local", "install-local", "status", "package", "templates", "docs"} and not governance.allow_custom_apps:
        return "custom_apps_disabled"
    if action in {"register-local", "install-local"} and not governance.allow_app_installation:
        return "app_installation_disabled"
    if context is None and action in {"create", "register-local", "install-local", "package"}:
        return "app_management_forbidden"
    return None


def _required_app_id(body: dict[str, object]) -> str:
    app_id = str(body.get("app_id") or "").strip()
    if not app_id:
        raise ValueError("app_id is required")
    return app_id


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items = [str(item).strip() for item in value]
    return [item for item in items if item]
