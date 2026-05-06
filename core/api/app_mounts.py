"""Mounted app frontend and backend execution handlers."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path
import re
from typing import Any

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, query_params, read_json_body, status_line, text_response
from core.api.platform_state import PlatformState
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.runtime_requests import apply_app_runtime_requests
from core.apps.service import build_workspace_app_frontend
from core.authorization.errors import AuthorizationError
from core.authorization.service import can_mount_app_visibility, require_workspace_admin, require_workspace_membership
from core.providers.errors import ProviderError
from core.providers.service import resolve_provider_for_workspace
from core.secrets.errors import SecretError
from core.secrets.service import bind_app_secret, build_secret_ref, create_platform_secret, resolve_app_secret, rotate_platform_secret
from core.shared.entrypoints import EntrypointShutdownController, run_json_entrypoint
from core.workspaces.paths import workspace_paths
from core.identity.models import UserRecord


logger = logging.getLogger(__name__)
DEFAULT_APP_BACKEND_TIMEOUT_SECONDS = 300


_PUBLIC_STATIC_EXTENSIONS = {
    ".css",
    ".gif",
    ".ico",
    ".jpg",
    ".jpeg",
    ".js",
    ".json",
    ".map",
    ".png",
    ".svg",
    ".txt",
    ".webp",
    ".woff",
    ".woff2",
}


def serve_frontend(
    start_response: StartResponse,
    *,
    frontend_root: Path,
    subpath: str,
    spa_fallback: bool = True,
    cross_origin: bool = False,
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
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
    if content_type.startswith("text/html"):
        headers.append(("Cache-Control", "no-store"))
    elif cross_origin:
        headers.append(("Cache-Control", "public, max-age=31536000, immutable"))
    if cross_origin:
        headers.extend(
            [
                ("Access-Control-Allow-Origin", "*"),
                ("Cross-Origin-Resource-Policy", "cross-origin"),
            ]
        )
    start_response("200 OK", headers)
    return [body]


def is_public_app_static_asset(subpath: str) -> bool:
    """Return true for static frontend assets that iframe sandboxes must load without session cookies."""
    normalized = subpath.lstrip("/")
    suffix = Path(normalized).suffix.lower()
    return normalized.startswith("assets/") or (bool(suffix) and suffix in _PUBLIC_STATIC_EXTENSIONS)


def app_backend_timeout_seconds() -> int:
    raw = os.environ.get("MAVERICK_APP_BACKEND_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_APP_BACKEND_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_APP_BACKEND_TIMEOUT_SECONDS
    return max(30, value)


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
    try:
        return serve_frontend(
            start_response,
            frontend_root=(source_root / parsed.contract.entrypoints.frontend).resolve(),
            subpath="/",
        )
    except Exception:
        logger.exception(
            "Root shell `%s` in workspace `%s` failed during frontend serving.",
            root_shell_app_id,
            workspace_id,
        )
        return json_response(start_response, {"error": "shell_unavailable"}, status="503 Service Unavailable")


def handle_app_frontend(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    subpath: str,
    user: UserRecord | None,
    public_static_asset: bool = False,
    allow_unauthenticated_frontend: bool = False,
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
    if user is None and not public_static_asset and not allow_unauthenticated_frontend:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    if user is not None and not can_mount_app_visibility(
        state.workspace_store,
        user=user,
        workspace_id=workspace_id,
        platform_roles=parsed.contract.visibility.platform_roles,
        workspace_roles=parsed.contract.visibility.workspace_roles,
        capabilities=parsed.contract.visibility.capabilities,
    ):
        return json_response(start_response, {"error": "app_forbidden"}, status="403 Forbidden")
    frontend = parsed.contract.entrypoints.frontend
    if frontend is None:
        return text_response(start_response, "App frontend not found", status="404 Not Found")
    try:
        return serve_frontend(
            start_response,
            frontend_root=(source_root / frontend).resolve(),
            subpath=subpath,
            spa_fallback=not public_static_asset,
            cross_origin=public_static_asset,
        )
    except Exception:
        logger.exception("App `%s` frontend mount failed in workspace `%s`.", app_id, workspace_id)
        return json_response(start_response, {"error": "app_unavailable"}, status="404 Not Found")


def handle_app_frontend_build(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Build one app frontend through the hosted core process and notify mounted clients."""
    if user is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    workspace_store = getattr(state, "workspace_store", None)
    if workspace_store is None:
        if user.platform_role != "admin":
            return json_response(start_response, {"error": "app_management_forbidden"}, status="403 Forbidden")
    else:
        try:
            require_workspace_admin(workspace_store, user=user, workspace_id=workspace_id, reason="app_management_forbidden")
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    try:
        payload = build_workspace_app_frontend(
            state.app_store,
            workspace_id=workspace_id,
            app_id=app_id,
            start_path=start_path,
            app_event_bus=state.app_event_bus,
        )
    except WorkspaceAppBindingNotFoundError:
        return json_response(start_response, {"error": "app_not_installed"}, status="404 Not Found")
    except AppHostingError as error:
        return json_response(start_response, {"error": "frontend_build_failed", "detail": str(error)}, status="400 Bad Request")
    return json_response(start_response, payload)


def handle_app_backend(
    state: PlatformState,
    *,
    environ: dict,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    start_path: Path,
    start_response: StartResponse,
    shutdown_controller: EntrypointShutdownController | None = None,
    trusted_platform_invocation: bool = False,
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
    if user is None and not trusted_platform_invocation:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    if user is not None:
        try:
            require_workspace_membership(state.workspace_store, user=user, workspace_id=workspace_id)
        except AuthorizationError:
            return json_response(start_response, {"error": "workspace_not_available"}, status="403 Forbidden")
    if binding.source_kind == "workspace_local_project" and not trusted_platform_invocation:
        try:
            require_workspace_admin(
                state.workspace_store,
                user=user,
                workspace_id=workspace_id,
                reason="workspace_local_backend_forbidden",
            )
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    if not trusted_platform_invocation and not can_mount_app_visibility(
        state.workspace_store,
        user=user,
        workspace_id=workspace_id,
        platform_roles=parsed.contract.visibility.platform_roles,
        workspace_roles=parsed.contract.visibility.workspace_roles,
        capabilities=parsed.contract.visibility.capabilities,
    ):
        return json_response(start_response, {"error": "app_forbidden"}, status="403 Forbidden")
    backend = parsed.contract.entrypoints.backend
    if backend is None:
        return text_response(start_response, "App backend not found", status="404 Not Found")
    body = read_json_body(environ)
    provider_id = None
    try:
        provider, _selection = resolve_provider_for_workspace(state.provider_store, workspace_id=workspace_id)
        provider_id = provider.provider_id
    except ProviderError:
        provider_id = None
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
                "provider_id": provider_id,
                "app_dependencies": _app_dependencies_payload(
                    state,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    user=user,
                    start_path=start_path,
                ),
                "runtime_session_id": "",
                "turn_id": "",
                "app_secrets": _resolve_app_secret_payload(
                    state,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    allowed_logical_names=parsed.contract.permissions.secrets.read,
                ),
            },
            cwd=source_root,
            timeout_seconds=app_backend_timeout_seconds(),
            shutdown_controller=shutdown_controller,
        )
    except Exception as error:
        logger.exception("App `%s` backend entrypoint failed in workspace `%s`.", app_id, workspace_id)
        return json_response(start_response, {"error": "app_backend_failed"}, status=status_line(500))
    try:
        secret_results = _apply_app_secret_writes(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            allowed_logical_names=parsed.contract.permissions.secrets.write,
            result=result,
        )
    except SecretError as error:
        return json_response(start_response, {"error": "secret_error", "detail": str(error)}, status=status_line(500))
    publish_declared_app_events(
        state.app_event_bus,
        result,
        workspace_id=workspace_id,
        app_id=app_id,
        declared_resources=declared_data_event_resources(parsed.contract.capabilities.data_events),
        remove_from_result=True,
    )
    try:
        runtime_request_results = apply_app_runtime_requests(
            state,
            result=result,
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=source_root,
            backend_entrypoint=backend,
            data_root=binding.data_root,
            parsed=parsed,
            start_path=start_path,
        )
    except AppHostingError as error:
        return json_response(start_response, {"error": "runtime_request_failed", "detail": str(error)}, status=status_line(500))
    try:
        runtime_cleanup_results = _apply_runtime_cleanup_requests(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            cleanup_allowed=parsed.contract.permissions.runtime.cleanup_sessions,
            result=result,
            start_path=start_path,
        )
    except AppHostingError as error:
        return json_response(start_response, {"error": "runtime_cleanup_failed", "detail": str(error)}, status=status_line(500))
    status_code = int(result.get("status_code", 200))
    if "json" in result:
        response_json = result["json"]
        if secret_results:
            response_json = {**response_json, "platform_secret_results": secret_results}
        if runtime_request_results:
            response_json = {**response_json, "runtime_request_results": runtime_request_results}
        if runtime_cleanup_results:
            response_json = {**response_json, "runtime_cleanup_results": runtime_cleanup_results}
        return json_response(start_response, response_json, status=status_line(status_code))
    if "body" in result:
        return text_response(start_response, str(result["body"]), status=status_line(status_code))
    return json_response(start_response, result, status=status_line(status_code))


def _app_dependencies_payload(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    user: UserRecord | None,
    start_path: Path,
) -> dict[str, object]:
    try:
        return resolve_app_dependencies(
            state.app_store,
            workspace_id=workspace_id,
            consumer_app_id=app_id,
            user=user,
            workspace_store=state.workspace_store,
            start_path=start_path,
        )
    except Exception:
        logger.exception("App `%s` dependency resolution failed in workspace `%s`.", app_id, workspace_id)
        return {"workspace_id": workspace_id, "consumer_app_id": app_id, "status": "blocked", "dependencies": []}


def _apply_runtime_cleanup_requests(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    cleanup_allowed: bool,
    result: dict[str, Any],
    start_path: Path,
) -> list[dict[str, object]]:
    response_json = result.get("json") if isinstance(result.get("json"), dict) else None
    requests = result.pop("runtime_cleanup_requests", None)
    if requests is None and response_json is not None:
        requests = response_json.pop("runtime_cleanup_requests", [])
    if requests is None:
        requests = []
    if not isinstance(requests, list) or not requests:
        return []
    if not cleanup_allowed:
        raise AppHostingError(f"App `{app_id}` requested runtime cleanup without declaring runtime.cleanup_sessions.")
    from core.api.runtime_cleanup import cleanup_runtime_session
    from core.runtime.errors import RuntimeSessionNotFoundError

    cleanup_results: list[dict[str, object]] = []
    for item in requests:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("runtime_session_id") or item.get("session_id") or "").strip()
        if not session_id:
            continue
        try:
            session = state.runtime_store.get_session(session_id)
        except RuntimeSessionNotFoundError:
            session = None
        if session is not None and session.workspace_id != workspace_id:
            raise AppHostingError(f"App `{app_id}` cannot clean runtime session outside workspace `{workspace_id}`.")
        cleanup = cleanup_runtime_session(
            state,
            session_id=session_id,
            reason=str(item.get("reason") or f"{app_id}_runtime_cleanup"),
            start_path=start_path,
        )
        cleanup_results.append(cleanup)
    return cleanup_results


def _resolve_app_secret_payload(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    allowed_logical_names: list[str] | None = None,
) -> dict[str, str]:
    """Resolve app-scoped secrets for one mounted backend invocation."""
    secrets: dict[str, str] = {}
    allowed = set(allowed_logical_names or [])
    for binding in state.secret_store.list_secret_bindings(workspace_id=workspace_id, app_id=app_id, scope="app"):
        if binding.status != "active":
            continue
        if binding.logical_name not in allowed:
            continue
        lease = resolve_app_secret(
            state.secret_store,
            workspace_id=workspace_id,
            app_id=app_id,
            logical_name=binding.logical_name,
        )
        secrets[binding.logical_name] = lease.value
    return secrets


def _apply_app_secret_writes(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    allowed_logical_names: list[str] | None,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Persist app-requested secret writes through generic app-scoped bindings."""
    writes = result.pop("platform_secret_writes", [])
    if not isinstance(writes, list):
        return []
    allowed = set(allowed_logical_names or [])
    persisted: list[dict[str, Any]] = []
    for write in writes:
        if not isinstance(write, dict):
            continue
        logical_name = str(write.get("logical_name") or "").strip().lower()
        raw_payload = write.get("raw_value")
        raw_value = raw_payload if isinstance(raw_payload, str) else json.dumps(raw_payload or {}, ensure_ascii=False, sort_keys=True)
        if not logical_name or not raw_value:
            continue
        if logical_name not in allowed:
            raise SecretError(f"App `{app_id}` requested secret write `{logical_name}` without declaring permission.")
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
            secret_id = _scoped_app_secret_id(workspace_id=workspace_id, app_id=app_id, logical_name=logical_name)
            alias = _scoped_app_secret_alias(workspace_id=workspace_id, app_id=app_id, logical_name=logical_name)
            secret = create_platform_secret(
                state.secret_store,
                label=f"{app_id} {logical_name}",
                raw_value=raw_value,
                alias=alias,
                description=f"App-scoped secret for {workspace_id}/{app_id}/{logical_name}.",
                secret_id=secret_id,
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


def _secret_segment(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "item"


def _scoped_app_secret_id(*, workspace_id: str, app_id: str, logical_name: str) -> str:
    return f"app-{_secret_segment(workspace_id)}-{_secret_segment(app_id)}-{_secret_segment(logical_name)}"


def _scoped_app_secret_alias(*, workspace_id: str, app_id: str, logical_name: str) -> str:
    return f"{_secret_segment(workspace_id)}-{_secret_segment(app_id)}-{_secret_segment(logical_name)}"
