"""Mounted app frontend and backend execution handlers."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, query_params, read_json_body, status_line, text_response
from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.providers.service import resolve_provider_for_workspace
from core.shared.entrypoints import run_json_entrypoint
from core.workspaces.paths import workspace_paths
from core.identity.models import UserRecord


def serve_frontend(
    start_response: StartResponse,
    *,
    frontend_root: Path,
    subpath: str,
    spa_fallback: bool = True,
) -> list[bytes]:
    """Serve an app frontend asset, optionally falling back to index.html for SPA routes."""
    root = frontend_root.resolve()
    candidate = (root / subpath.lstrip("/")).resolve() if subpath.strip("/") else (root / "index.html").resolve()
    if candidate == root or root not in candidate.parents:
        return text_response(start_response, "Not found", status="404 Not Found")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.exists():
        if not spa_fallback:
            return text_response(start_response, "Not found", status="404 Not Found")
        candidate = root / "index.html"
    if not candidate.exists() or not candidate.is_file():
        return text_response(start_response, "Not found", status="404 Not Found")
    body = candidate.read_bytes()
    content_type = mimetypes.guess_type(str(candidate))[0] or "text/html; charset=utf-8"
    start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


def handle_root_shell(
    state: PlatformState,
    *,
    workspace_id: str,
    root_shell_app_id: str,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Serve the configured root shell app for the active workspace."""
    try:
        _binding, source_root, parsed = resolve_app_surface(
            state,
            workspace_id=workspace_id,
            app_id=root_shell_app_id,
            start_path=start_path,
        )
    except WorkspaceAppBindingNotFoundError:
        return json_response(start_response, {"error": "shell_not_installed"}, status="404 Not Found")
    except AppHostingError:
        return json_response(start_response, {"error": "shell_unavailable"}, status="503 Service Unavailable")
    return serve_frontend(
        start_response,
        frontend_root=(source_root / parsed.contract.entrypoints.frontend).resolve(),
        subpath="/",
    )


def handle_app_frontend(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    subpath: str,
    user: UserRecord | None,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Serve one mounted app frontend."""
    try:
        _binding, source_root, parsed = resolve_app_surface(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            start_path=start_path,
        )
    except WorkspaceAppBindingNotFoundError:
        return json_response(start_response, {"error": "app_not_installed"}, status="404 Not Found")
    except AppHostingError:
        return json_response(start_response, {"error": "app_unavailable"}, status="404 Not Found")
    allowed_roles = parsed.contract.visibility.platform_roles
    if allowed_roles and (user is None or user.platform_role not in allowed_roles):
        return json_response(start_response, {"error": "app_forbidden"}, status="403 Forbidden")
    frontend = parsed.contract.entrypoints.frontend
    if frontend is None:
        return text_response(start_response, "App frontend not found", status="404 Not Found")
    return serve_frontend(start_response, frontend_root=(source_root / frontend).resolve(), subpath=subpath)


def handle_app_backend(
    state: PlatformState,
    *,
    environ: dict,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Execute one app backend entrypoint through the platform host."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    try:
        binding, source_root, parsed = resolve_app_surface(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            start_path=start_path,
        )
    except WorkspaceAppBindingNotFoundError:
        return json_response(start_response, {"error": "app_not_installed"}, status="404 Not Found")
    except AppHostingError:
        return json_response(start_response, {"error": "app_unavailable"}, status="404 Not Found")
    allowed_roles = parsed.contract.visibility.platform_roles
    if allowed_roles and (user is None or user.platform_role not in allowed_roles):
        return json_response(start_response, {"error": "app_forbidden"}, status="403 Forbidden")
    backend = parsed.contract.entrypoints.backend
    if backend is None:
        return text_response(start_response, "App backend not found", status="404 Not Found")
    body = read_json_body(environ)
    provider, _selection = resolve_provider_for_workspace(state.provider_store, workspace_id=workspace_id)
    paths = workspace_paths(workspace_id, start_path=start_path)
    try:
        result = run_json_entrypoint(
            source_root / backend,
            payload={
                "surface": "backend",
                "workspace_id": workspace_id,
                "app_id": app_id,
                "workspace_root": str(paths.root),
                "data_root": binding.data_root,
                "uploaded_storage_root": str(paths.uploaded_storage),
                "generated_storage_root": str(paths.generated_storage),
                "route_path": environ.get("PATH_INFO", ""),
                "method": method,
                "query": query_params(environ),
                "headers": {"content_type": environ.get("CONTENT_TYPE", "")},
                "body": body,
                "provider_id": provider.provider_id,
                "runtime_session_id": "",
                "turn_id": "",
            },
            cwd=source_root,
        )
    except Exception as error:
        return json_response(start_response, {"error": str(error)}, status=status_line(500))
    status_code = int(result.get("status_code", 200))
    if "json" in result:
        response_json = result["json"]
        return json_response(start_response, response_json, status=status_line(status_code))
    if "body" in result:
        return text_response(start_response, str(result["body"]), status=status_line(status_code))
    return json_response(start_response, result, status=status_line(status_code))
