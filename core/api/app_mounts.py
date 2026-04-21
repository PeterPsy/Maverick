"""Mounted app frontend and backend execution handlers."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, query_params, read_json_body, status_line, text_response
from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.providers.service import resolve_provider_for_workspace
from core.secrets.errors import SecretError
from core.secrets.service import bind_app_secret, build_secret_ref, create_platform_secret, resolve_app_secret, rotate_platform_secret
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
                "app_secrets": _resolve_app_secret_payload(state, workspace_id=workspace_id, app_id=app_id),
            },
            cwd=source_root,
        )
    except Exception as error:
        return json_response(start_response, {"error": str(error)}, status=status_line(500))
    try:
        secret_results = _apply_app_secret_writes(state, workspace_id=workspace_id, app_id=app_id, result=result)
    except SecretError as error:
        return json_response(start_response, {"error": "secret_error", "detail": str(error)}, status=status_line(500))
    _publish_app_events(state, workspace_id=workspace_id, app_id=app_id, result=result)
    status_code = int(result.get("status_code", 200))
    if "json" in result:
        response_json = result["json"]
        if secret_results:
            response_json = {**response_json, "platform_secret_results": secret_results}
        return json_response(start_response, response_json, status=status_line(status_code))
    if "body" in result:
        return text_response(start_response, str(result["body"]), status=status_line(status_code))
    return json_response(start_response, result, status=status_line(status_code))


def _publish_app_events(state: PlatformState, *, workspace_id: str, app_id: str, result: dict[str, Any]) -> None:
    events = result.pop("app_events", [])
    if not isinstance(events, list):
        return
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "maverick.app.data-changed").strip()
        owner_app_id = str(event.get("owner_app_id") or app_id).strip()
        state.app_event_bus.publish(
            {
                "type": event_type,
                "workspace_id": workspace_id,
                "owner_app_id": owner_app_id,
                "resource": str(event.get("resource") or ""),
            }
        )


def _resolve_app_secret_payload(state: PlatformState, *, workspace_id: str, app_id: str) -> dict[str, str]:
    """Resolve app-scoped secrets for one mounted backend invocation."""
    secrets: dict[str, str] = {}
    for binding in state.secret_store.list_secret_bindings(workspace_id=workspace_id, app_id=app_id, scope="app"):
        if binding.status != "active":
            continue
        lease = resolve_app_secret(
            state.secret_store,
            workspace_id=workspace_id,
            app_id=app_id,
            logical_name=binding.logical_name,
        )
        secrets[binding.logical_name] = lease.value
    return secrets


def _apply_app_secret_writes(state: PlatformState, *, workspace_id: str, app_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Persist app-requested secret writes through generic app-scoped bindings."""
    writes = result.pop("platform_secret_writes", [])
    if not isinstance(writes, list):
        return []
    persisted: list[dict[str, Any]] = []
    for write in writes:
        if not isinstance(write, dict):
            continue
        logical_name = str(write.get("logical_name") or "").strip().lower()
        raw_payload = write.get("raw_value")
        raw_value = raw_payload if isinstance(raw_payload, str) else json.dumps(raw_payload or {}, ensure_ascii=False, sort_keys=True)
        if not logical_name or not raw_value:
            continue
        existing = [
            item
            for item in state.secret_store.list_secret_bindings(workspace_id=workspace_id, app_id=app_id, scope="app", logical_name=logical_name)
            if item.status == "active"
        ]
        if existing:
            binding = existing[0]
            secret_id = binding.secret_ref.removeprefix("platform:secrets/")
            if binding.secret_ref.startswith("platform:secret-alias/"):
                secret_id = state.secret_store.get_secret_by_alias(binding.secret_ref.removeprefix("platform:secret-alias/")).secret_id
            secret = rotate_platform_secret(state.secret_store, secret_id=secret_id, raw_value=raw_value)
        else:
            alias = str(write.get("alias") or f"{workspace_id}-{app_id}-{logical_name}").strip().lower()
            secret = create_platform_secret(
                state.secret_store,
                label=str(write.get("label") or f"{app_id} {logical_name}"),
                raw_value=raw_value,
                alias=alias,
                description=str(write.get("description") or f"App-scoped secret for {app_id}/{logical_name}."),
            )
            binding = bind_app_secret(
                state.secret_store,
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_ref=build_secret_ref(alias=secret.alias) if secret.alias else build_secret_ref(secret_id=secret.secret_id),
            )
        persisted.append(
            {
                "logical_name": logical_name,
                "secret_id": secret.secret_id,
                "alias": secret.alias,
                "binding_id": binding.binding_id,
                "status": secret.status,
            }
        )
    return persisted
