"""Mounted app frontend and backend execution handlers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import logging
import mimetypes
import re
from pathlib import Path
import uuid
from typing import Any

from core.api.app_event_publication import declared_data_event_resources, publish_declared_app_events
from core.api.app_runtime_cleanup_requests import apply_runtime_cleanup_requests
from core.api.app_registry import enabled_app_items, resolve_app_surface
from core.api.secret_grant_targets import (
    SecretConsumersByLogicalName,
    app_secret_consumers_by_logical_name,
    assert_consumer_resource_scope_allowed,
)
from core.api.http import StartResponse, json_response, max_json_body_bytes, query_params, read_json_body, read_request_body_bytes, status_line, text_response
from core.api.platform_state import PlatformState
from core.apps.dependencies import resolve_app_dependencies
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.models import ParsedAppContract
from core.apps.runtime_requests import apply_app_runtime_requests
from core.apps.service import build_workspace_app_frontend
from core.authorization.errors import AuthorizationError
from core.authorization.service import can_mount_app_visibility, require_workspace_admin, require_workspace_membership
from core.observability.service import record_platform_audit, record_platform_event
from core.providers.errors import ProviderError
from core.providers.service import resolve_provider_for_workspace
from core.secrets.app_delivery import (
    APP_SECRET_ACTION,
    APP_SECRET_TARGET_PREFIX,
    AppSecretRequest,
    AppSecretPayloadResult,
    app_secret_target,
    resolve_app_secret_payload,
    resolve_app_secret_payload_requests,
)
from core.secrets.errors import SecretError
from core.secrets.secret_resolution import parse_secret_ref
from core.secrets.service import build_secret_ref, create_platform_secret, grant_app_secret_use, rotate_platform_secret
from core.secrets.target_policy import target_allowed
from core.shared.entrypoints import EntrypointShutdownController, run_json_entrypoint
from core.workspaces.paths import workspace_paths
from core.identity.models import UserRecord


logger = logging.getLogger(__name__)

APP_BACKEND_BINARY_BODY_LIMITS = {
    "speech": 700_000,
}

FILE_RESPONSE_CHUNK_BYTES = 1024 * 1024
UNSAFE_INLINE_CONTENT_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/html",
    "text/javascript",
}


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


def handle_root_shell_static_asset(
    state: PlatformState,
    *,
    workspace_id: str,
    root_shell_app_id: str,
    subpath: str,
    start_path: Path,
    start_response: StartResponse,
) -> list[bytes]:
    """Serve a public root-level asset emitted by the configured shell frontend."""
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
    frontend = parsed.contract.entrypoints.frontend
    if frontend is None:
        return text_response(start_response, "Shell frontend not found", status="404 Not Found")
    try:
        return serve_frontend(
            start_response,
            frontend_root=(source_root / frontend).resolve(),
            subpath=subpath,
            spa_fallback=False,
            cross_origin=True,
        )
    except Exception:
        logger.exception(
            "Root shell `%s` in workspace `%s` failed while serving root asset `%s`.",
            root_shell_app_id,
            workspace_id,
            subpath,
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
    authorization = None
    if user is not None:
        try:
            authorization = require_workspace_membership(state.workspace_store, user=user, workspace_id=workspace_id)
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
    try:
        body, body_file = _read_backend_body(environ, data_root=binding.data_root, app_id=parsed.app_id)
    except Exception as error:
        if hasattr(error, "error") and hasattr(error, "status"):
            return json_response(start_response, {"error": error.error}, status=error.status)
        raise
    provider_id = None
    try:
        provider, _selection = resolve_provider_for_workspace(state.provider_store, workspace_id=workspace_id)
        provider_id = provider.provider_id
    except ProviderError:
        provider_id = None
    paths = workspace_paths(workspace_id, start_path=start_path)
    request_query = query_params(environ)
    secret_request_body = _backend_secret_request_body(
        body=body,
        method=method,
        route_path=str(environ.get("PATH_INFO") or ""),
        query=request_query,
    )
    try:
        app_secret_result = _resolve_app_secret_payload_requests(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            requests=_requested_backend_secret_requests(
                declared_logical_names=parsed.contract.permissions.secrets.read,
                body=secret_request_body,
            ),
            surface="backend",
            actor_user_id=None if user is None else user.user_id,
            request_context={
                "surface": "backend",
                "method": method,
                "route_path": str(environ.get("PATH_INFO") or ""),
            },
            fail_closed=_requested_backend_secrets_fail_closed(secret_request_body),
        )
    except SecretError as error:
        if body_file and body_file.get("path"):
            try:
                Path(str(body_file["path"])).unlink()
            except FileNotFoundError:
                pass
        return json_response(start_response, {"error": "app_secret_unavailable", "detail": str(error)}, status=status_line(500))
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
                "query": request_query,
                "headers": {"content_type": environ.get("CONTENT_TYPE", ""), "range": environ.get("HTTP_RANGE", "")},
                "body": body,
                "body_file": body_file or {},
                "provider_id": provider_id,
                "effective_mode": "full-access" if trusted_platform_invocation else "sandbox",
                "platform_role": None if user is None else user.platform_role,
                "user_id": None if user is None else user.user_id,
                "workspace_role": _workspace_role_for_backend_user(user=user, authorization=authorization),
                "app_dependencies": _app_dependencies_payload(
                    state,
                    workspace_id=workspace_id,
                    app_id=app_id,
                    user=user,
                    start_path=start_path,
                ),
                "workspace_apps": {
                    "items": enabled_app_items(
                        state,
                        workspace_id=workspace_id,
                        start_path=start_path,
                        user=user,
                    )
                },
                "runtime_session_id": "",
                "turn_id": "",
                "app_secrets": app_secret_result.secrets,
                "app_secret_errors": app_secret_result.errors,
            },
            cwd=source_root,
            timeout_seconds=backend_entrypoint_timeout_seconds(parsed),
            shutdown_controller=shutdown_controller,
        )
    except Exception as error:
        logger.exception("App `%s` backend entrypoint failed in workspace `%s`.", app_id, workspace_id)
        return json_response(start_response, {"error": "app_backend_failed"}, status=status_line(500))
    finally:
        if body_file and body_file.get("path"):
            try:
                Path(str(body_file["path"])).unlink()
            except FileNotFoundError:
                pass
    try:
        secret_results = _apply_app_secret_writes(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            allowed_logical_names=parsed.contract.permissions.secrets.write,
            result=result,
            actor_user_id=None if user is None else user.user_id,
            secret_consumers=app_secret_consumers_by_logical_name(
                source_root=source_root,
                declared_logical_names=[
                    str(item).strip().lower()
                    for item in parsed.contract.permissions.secrets.read
                    if str(item).strip()
                ],
                backend_declared=parsed.contract.entrypoints.backend is not None,
                cli_commands=[
                    str(item).strip()
                    for item in parsed.contract.capabilities.cli_commands
                    if str(item).strip()
                ],
                mcp_tools=[
                    str(item).strip()
                    for item in parsed.contract.capabilities.mcp_tools
                    if str(item).strip()
                ],
            ),
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
        runtime_cleanup_results = apply_runtime_cleanup_requests(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            cleanup_allowed=parsed.contract.permissions.runtime.cleanup_sessions,
            user=user,
            source_root=source_root,
            backend_entrypoint=backend,
            data_root=binding.data_root,
            parsed=parsed,
            result=result,
            start_path=start_path,
        )
    except AuthorizationError as error:
        return json_response(start_response, {"error": error.reason}, status=status_line(403))
    except AppHostingError as error:
        return json_response(start_response, {"error": "runtime_cleanup_failed", "detail": str(error)}, status=status_line(500))
    status_code = int(result.get("status_code", 200))
    if "file_response" in result and isinstance(result.get("file_response"), dict):
        return _serve_app_file_response(
            environ=environ,
            start_response=start_response,
            file_response=result["file_response"],
            allowed_roots=[Path(binding.data_root), paths.uploaded_storage, paths.generated_storage],
            status_code=status_code,
        )
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


def _serve_app_file_response(
    *,
    environ: dict,
    start_response: StartResponse,
    file_response: dict[str, Any],
    allowed_roots: list[Path],
    status_code: int = 200,
):
    """Serve an app-approved local file with HTTP range support."""
    if status_code >= 400:
        return json_response(start_response, {"error": "file_response_failed"}, status=status_line(status_code))
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    if method not in {"GET", "HEAD"}:
        return json_response(
            start_response,
            {"error": "method_not_allowed"},
            status=status_line(405),
            headers=[("Allow", "GET, HEAD")],
        )
    raw_path = str(file_response.get("path") or "").strip()
    if not raw_path:
        return json_response(start_response, {"error": "file_response_path_required"}, status=status_line(500))
    try:
        path = Path(raw_path).resolve()
        roots = [root.resolve() for root in allowed_roots]
    except OSError:
        return json_response(start_response, {"error": "file_response_path_invalid"}, status=status_line(400))
    if not _path_is_under_any_root(path, roots):
        return json_response(start_response, {"error": "file_response_forbidden"}, status=status_line(403))
    if not path.is_file():
        return json_response(start_response, {"error": "file_response_not_found"}, status=status_line(404))

    size = path.stat().st_size
    content_type = str(file_response.get("content_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    file_name = _safe_header_filename(str(file_response.get("file_name") or path.name))
    disposition = "attachment" if _truthy(file_response.get("download")) or not _safe_inline_file_response_type(content_type) else "inline"
    etag = _quoted_etag(str(file_response.get("etag") or f"{path.stat().st_mtime_ns:x}-{size:x}"))
    base_headers = [
        ("Content-Type", content_type),
        ("Accept-Ranges", "bytes"),
        ("ETag", etag),
        ("Cache-Control", str(file_response.get("cache_control") or "private, max-age=60")),
        ("X-Content-Type-Options", "nosniff"),
        ("Content-Disposition", f'{disposition}; filename="{file_name}"'),
    ]

    try:
        served_range = _served_file_response_range(file_response, path_size=size)
    except ValueError:
        return json_response(start_response, {"error": "file_response_range_invalid"}, status=status_line(500))
    if served_range is not None:
        start, end, total_size = served_range
        headers = [*base_headers, ("Content-Range", f"bytes {start}-{end}/{total_size}"), ("Content-Length", str(size))]
        start_response(status_line(206), headers)
        if method == "HEAD":
            return [b""]
        return _file_range_chunks(path, start=0, length=size)

    range_header = str(environ.get("HTTP_RANGE") or "").strip()
    if range_header:
        selected = _parse_single_byte_range(range_header, size)
        if selected is None:
            headers = [*base_headers, ("Content-Range", f"bytes */{size}"), ("Content-Length", "0")]
            start_response(status_line(416), headers)
            return [b""]
        start, end = selected
        length = end - start + 1
        headers = [*base_headers, ("Content-Range", f"bytes {start}-{end}/{size}"), ("Content-Length", str(length))]
        start_response(status_line(206), headers)
        if method == "HEAD":
            return [b""]
        return _file_range_chunks(path, start=start, length=length)

    headers = [*base_headers, ("Content-Length", str(size))]
    start_response(status_line(200), headers)
    if method == "HEAD":
        return [b""]
    return _file_range_chunks(path, start=0, length=size)


def _path_is_under_any_root(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _safe_inline_file_response_type(content_type: str) -> bool:
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized in UNSAFE_INLINE_CONTENT_TYPES:
        return False
    if normalized == "application/pdf":
        return True
    if normalized.startswith("audio/") or normalized.startswith("video/"):
        return True
    if normalized.startswith("image/") and normalized != "image/svg+xml":
        return True
    return False


def _served_file_response_range(file_response: dict[str, Any], *, path_size: int) -> tuple[int, int, int] | None:
    raw = file_response.get("served_range")
    if not isinstance(raw, dict):
        return None
    try:
        start = int(raw.get("start"))
        end = int(raw.get("end"))
        total_size = int(raw.get("size"))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid served_range") from error
    if start < 0 or end < start or total_size <= end or end - start + 1 != path_size:
        raise ValueError("Invalid served_range")
    return start, end, total_size


def _parse_single_byte_range(value: str, size: int) -> tuple[int, int] | None:
    if size <= 0 or not value.startswith("bytes=") or "," in value:
        return None
    start_text, separator, end_text = value.removeprefix("bytes=").partition("-")
    if not separator:
        return None
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            start = max(0, size - suffix_length)
            end = size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
            if start < 0:
                return None
            end = min(end, size - 1)
    except ValueError:
        return None
    if start >= size or end < start:
        return None
    return start, end


def _file_range_chunks(path: Path, *, start: int, length: int):
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(FILE_RESPONSE_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _safe_header_filename(value: str) -> str:
    name = Path(value).name or "download"
    return name.replace("\\", "_").replace('"', "'").replace("\r", "_").replace("\n", "_")


def _quoted_etag(value: str) -> str:
    clean = value.strip().strip('"') or "file"
    return f'"{clean.replace(chr(34), "")}"'


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _workspace_role_for_backend_user(*, user: UserRecord | None, authorization: Any | None) -> str | None:
    if user is None:
        return None
    membership = getattr(authorization, "membership", None)
    if membership is not None and getattr(membership, "status", None) == "active":
        return str(getattr(membership, "role", "") or "") or None
    if user.platform_role == "admin":
        return "admin"
    return None


def backend_entrypoint_timeout_seconds(parsed: ParsedAppContract) -> int:
    return int(parsed.contract.hook_timeouts.backend_seconds)


def _backend_secret_request_body(*, body: dict[str, Any], method: str, route_path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    if method.upper() in {"GET", "HEAD"} and route_path.startswith("/api/apps/") and route_path.endswith("/media"):
        params = query or {}
        secret_request = _app_secret_request_from_query(params)
        if secret_request is None:
            secret_request = {"logical_names": [], "required": False}
        return {**body, **params, "_app_secret_request": secret_request}
    return body


def _app_secret_request_from_query(query: dict[str, str]) -> dict[str, Any] | None:
    raw_value = str(query.get("_app_secret_request") or query.get("app_secret_request") or "").strip()
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _read_backend_body(environ: dict, *, data_root: str, app_id: str = "") -> tuple[dict[str, Any], dict[str, Any] | None]:
    content_type = str(environ.get("CONTENT_TYPE") or "").split(";", 1)[0].strip().lower()
    if not content_type or content_type == "application/json":
        return read_json_body(environ), None
    raw = read_request_body_bytes(environ, max_bytes=app_backend_binary_body_limit(app_id))
    if not raw:
        return {}, None
    body_dir = Path(data_root) / "run" / "http-body"
    body_dir.mkdir(parents=True, exist_ok=True)
    body_path = body_dir / f"body-{uuid.uuid4().hex}.bin"
    body_path.write_bytes(raw)
    return {}, {"path": str(body_path), "content_type": content_type, "size_bytes": len(raw)}


def app_backend_binary_body_limit(app_id: str) -> int:
    return APP_BACKEND_BINARY_BODY_LIMITS.get(app_id, max_json_body_bytes())


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


def _resolve_app_secret_payload(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    allowed_logical_names: list[str] | None = None,
    surface: str = "backend",
    runtime_session_id: str | None = None,
    actor_user_id: str | None = None,
    request_context: dict[str, str] | None = None,
    fail_closed: bool = True,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> AppSecretPayloadResult:
    """Resolve grant-authorized app secrets for one mounted backend invocation."""
    return resolve_app_secret_payload(
        state.secret_store,
        workspace_id=workspace_id,
        app_id=app_id,
        allowed_logical_names=allowed_logical_names,
        surface=surface,
        runtime_session_id=runtime_session_id,
        actor_user_id=actor_user_id,
        observability_store=state.observability_store,
        request_context=request_context,
        fail_closed=fail_closed,
        resource_type=resource_type,
        resource_id=resource_id,
    )


def _resolve_app_secret_payload_requests(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    requests: list[AppSecretRequest],
    surface: str = "backend",
    runtime_session_id: str | None = None,
    actor_user_id: str | None = None,
    request_context: dict[str, str] | None = None,
    fail_closed: bool = True,
) -> AppSecretPayloadResult:
    """Resolve grant-authorized app secrets for mounted backend selectors."""
    return resolve_app_secret_payload_requests(
        state.secret_store,
        workspace_id=workspace_id,
        app_id=app_id,
        requests=requests,
        surface=surface,
        runtime_session_id=runtime_session_id,
        actor_user_id=actor_user_id,
        observability_store=state.observability_store,
        request_context=request_context,
        fail_closed=fail_closed,
    )


def _requested_backend_secret_requests(*, declared_logical_names: list[str], body: dict[str, Any]) -> list[AppSecretRequest]:
    request = body.get("_app_secret_request")
    declared = {str(item).strip().lower() for item in declared_logical_names if str(item).strip()}
    if not isinstance(request, dict):
        return [AppSecretRequest(logical_names=sorted(declared))]
    raw_selectors = request.get("selectors")
    if isinstance(raw_selectors, list):
        selectors: list[AppSecretRequest] = []
        for item in raw_selectors:
            if not isinstance(item, dict):
                continue
            logical_names = _requested_secret_names_from_value(item.get("logical_names", []), declared=declared)
            if not logical_names:
                continue
            resource_type, resource_id = _secret_resource_from_mapping(item)
            selectors.append(AppSecretRequest(logical_names=logical_names, resource_type=resource_type, resource_id=resource_id))
        return selectors
    resource_type, resource_id = _requested_backend_secret_resource(body)
    return [
        AppSecretRequest(
            logical_names=_requested_backend_secret_names(declared_logical_names=declared_logical_names, body=body),
            resource_type=resource_type,
            resource_id=resource_id,
        )
    ]


def _requested_backend_secret_names(*, declared_logical_names: list[str], body: dict[str, Any]) -> list[str]:
    request = body.get("_app_secret_request")
    declared = {str(item).strip().lower() for item in declared_logical_names if str(item).strip()}
    if not isinstance(request, dict):
        return sorted(declared)
    raw_names = request.get("logical_names", [])
    return _requested_secret_names_from_value(raw_names, declared=declared)


def _requested_secret_names_from_value(raw_names: object, *, declared: set[str]) -> list[str]:
    if not isinstance(raw_names, list):
        return []
    requested = []
    for item in raw_names:
        logical_name = str(item).strip().lower()
        if logical_name in declared and logical_name not in requested:
            requested.append(logical_name)
    return requested


def _requested_backend_secrets_fail_closed(body: dict[str, Any]) -> bool:
    request = body.get("_app_secret_request")
    if not isinstance(request, dict):
        return True
    return bool(request.get("required"))


def _requested_backend_secret_resource(body: dict[str, Any]) -> tuple[str | None, str | None]:
    request = body.get("_app_secret_request")
    if not isinstance(request, dict):
        return None, None
    return _secret_resource_from_mapping(request)


def _secret_resource_from_mapping(request: dict[str, Any]) -> tuple[str | None, str | None]:
    resource_type = str(request.get("resource_type") or "").strip().lower()
    resource_id = str(request.get("resource_id") or "").strip().lower()
    if not resource_type or not resource_id:
        return None, None
    return resource_type, resource_id


def _apply_app_secret_writes(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    allowed_logical_names: list[str] | None,
    result: dict[str, Any],
    actor_user_id: str | None = None,
    secret_consumers: SecretConsumersByLogicalName | None = None,
) -> list[dict[str, Any]]:
    """Persist app-requested secret writes through grant-backed app delivery."""
    writes = result.pop("platform_secret_writes", [])
    if not isinstance(writes, list):
        return []
    allowed = set(allowed_logical_names or [])
    persisted: list[dict[str, Any]] = []
    for write in writes:
        if not isinstance(write, dict):
            continue
        logical_name = str(write.get("logical_name") or "").strip().lower()
        resource_type, resource_id = _secret_write_resource(write)
        delivery_target = app_secret_target("backend", resource_type=resource_type, resource_id=resource_id)
        grant_targets = [f"{APP_SECRET_TARGET_PREFIX}/*"] if resource_type and resource_id else [delivery_target]
        raw_payload = write.get("raw_value")
        raw_value = raw_payload if isinstance(raw_payload, str) else json.dumps(raw_payload or {}, ensure_ascii=False, sort_keys=True)
        if not logical_name or not raw_value:
            continue
        if logical_name not in allowed:
            raise SecretError(f"App `{app_id}` requested secret write `{logical_name}` without declaring permission.")
        if secret_consumers is not None and logical_name in secret_consumers:
            assert_consumer_resource_scope_allowed(
                app_id=app_id,
                logical_name=logical_name,
                actions=[APP_SECRET_ACTION],
                resource_type=resource_type,
                resource_id=resource_id,
                consumers=secret_consumers,
            )
        grant = _active_app_backend_grant(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            logical_name=logical_name,
            target=delivery_target,
            base_target=app_secret_target("backend"),
            resource_type=resource_type,
            resource_id=resource_id,
        )
        legacy_binding = (
            _active_legacy_app_binding(state, workspace_id=workspace_id, app_id=app_id, logical_name=logical_name)
            if resource_type is None and resource_id is None
            else None
        )
        if grant is not None:
            secret_id = _secret_id_for_ref(state, grant.secret_ref)
            secret = rotate_platform_secret(state.secret_store, secret_id=secret_id, raw_value=raw_value)
            if grant.target_patterns != grant_targets:
                grant = state.secret_store.save_secret_grant(replace(grant, target_patterns=grant_targets, updated_at=datetime.now(tz=UTC)))
            secret_ref = grant.secret_ref
            _record_app_secret_write(
                state,
                action="core.secrets.app_write.rotate",
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_id=secret.secret_id,
                alias=secret.alias,
                grant_id=grant.grant_id,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                delivery_target=delivery_target,
                actor_user_id=actor_user_id,
            )
        elif legacy_binding is not None:
            secret_id = _secret_id_for_ref(state, legacy_binding.secret_ref)
            secret = rotate_platform_secret(state.secret_store, secret_id=secret_id, raw_value=raw_value)
            secret_ref = legacy_binding.secret_ref
            _record_app_secret_write(
                state,
                action="core.secrets.app_write.rotate",
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_id=secret.secret_id,
                alias=secret.alias,
                grant_id=None,
                resource_type=None,
                resource_id=None,
                delivery_target=f"{APP_SECRET_TARGET_PREFIX}/*",
                actor_user_id=actor_user_id,
            )
            grant = grant_app_secret_use(
                state.secret_store,
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_ref=secret_ref,
                actions=[APP_SECRET_ACTION],
                target_patterns=[f"{APP_SECRET_TARGET_PREFIX}/*"],
                created_by_user_id=actor_user_id,
                reason="Created automatically for app backend secret write delivery.",
            )
            _record_app_secret_write(
                state,
                action="core.secrets.grant.create.app_write",
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_id=secret.secret_id,
                alias=secret.alias,
                grant_id=grant.grant_id,
                resource_type=None,
                resource_id=None,
                delivery_target=f"{APP_SECRET_TARGET_PREFIX}/*",
                actor_user_id=actor_user_id,
            )
        else:
            secret_id = _scoped_app_secret_id(
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            alias = _scoped_app_secret_alias(
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            secret = create_platform_secret(
                state.secret_store,
                label=f"{app_id} {logical_name}",
                raw_value=raw_value,
                alias=alias,
                description=f"App-scoped secret for {workspace_id}/{app_id}/{logical_name}.",
                secret_id=secret_id,
            )
            _record_app_secret_write(
                state,
                action="core.secrets.app_write.create",
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_id=secret.secret_id,
                alias=secret.alias,
                grant_id=None,
                resource_type=resource_type,
                resource_id=resource_id,
                delivery_target=delivery_target,
                actor_user_id=actor_user_id,
            )
            secret_ref = build_secret_ref(alias=secret.alias) if secret.alias else build_secret_ref(secret_id=secret.secret_id)
            grant = grant_app_secret_use(
                state.secret_store,
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_ref=secret_ref,
                actions=[APP_SECRET_ACTION],
                target_patterns=grant_targets,
                grant_id=_scoped_app_secret_grant_id(
                    workspace_id=workspace_id,
                    app_id=app_id,
                    logical_name=logical_name,
                    resource_type=resource_type,
                    resource_id=resource_id,
                ),
                created_by_user_id=actor_user_id,
                reason="Created automatically for app backend secret write delivery.",
                resource_type=resource_type,
                resource_id=resource_id,
            )
            _record_app_secret_write(
                state,
                action="core.secrets.grant.create.app_write",
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=logical_name,
                secret_id=secret.secret_id,
                alias=secret.alias,
                grant_id=grant.grant_id,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                delivery_target=delivery_target,
                actor_user_id=actor_user_id,
            )
        persisted.append(
            {
                "logical_name": logical_name,
                "secret_id": secret.secret_id,
                "alias": secret.alias,
                "grant_id": None if grant is None else grant.grant_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "delivery_target": delivery_target,
                "status": secret.status,
            }
        )
    return persisted


def _record_app_secret_write(
    state: PlatformState,
    *,
    action: str,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    secret_id: str,
    alias: str | None,
    grant_id: str | None,
    resource_type: str | None,
    resource_id: str | None,
    delivery_target: str,
    actor_user_id: str | None,
) -> None:
    if state.observability_store is None:
        return
    payload = {
        "actor_user_id": actor_user_id,
        "app_id": app_id,
        "logical_name": logical_name,
        "secret_id": secret_id,
        "alias": alias,
        "grant_id": grant_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "delivery_target": delivery_target,
    }
    record_platform_audit(
        state.observability_store,
        action=action,
        status="succeeded",
        source_domain="secrets",
        detail=f"Applied app-owned secret write `{logical_name}` for app `{app_id}`.",
        workspace_id=workspace_id,
        app_id=app_id,
        payload=payload,
    )
    record_platform_event(
        state.observability_store,
        event_type=action,
        event_plane="platform",
        source_domain="secrets",
        workspace_id=workspace_id,
        app_id=app_id,
        payload=payload,
    )


def _active_app_backend_grant(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    target: str,
    base_target: str,
    resource_type: str | None,
    resource_id: str | None,
):
    now = datetime.now(tz=UTC)
    candidates = [
        grant
        for grant in state.secret_store.list_secret_grants(workspace_id=workspace_id, app_id=app_id, status="active")
        if grant.logical_name == logical_name
        and APP_SECRET_ACTION in grant.actions
        and grant.resource_type == resource_type
        and grant.resource_id == resource_id
        and _grant_target_matches(grant.target_patterns, target=target, base_target=base_target)
        and (grant.expires_at is None or grant.expires_at.astimezone(UTC) > now)
    ]
    return sorted(candidates, key=lambda item: item.created_at, reverse=True)[0] if candidates else None


def _grant_target_matches(target_patterns: list[str], *, target: str, base_target: str) -> bool:
    try:
        return target_allowed(target, target_patterns) or (target != base_target and target_allowed(base_target, target_patterns))
    except SecretError:
        return False


def _active_legacy_app_binding(state: PlatformState, *, workspace_id: str, app_id: str, logical_name: str):
    bindings = [
        item
        for item in state.secret_store.list_secret_bindings(
            workspace_id=workspace_id,
            app_id=app_id,
            scope="app",
            logical_name=logical_name,
        )
        if item.status == "active"
    ]
    return bindings[0] if bindings else None


def _secret_id_for_ref(state: PlatformState, secret_ref: str) -> str:
    parsed = parse_secret_ref(secret_ref)
    if parsed.kind == "secret_id":
        return parsed.value
    return state.secret_store.get_secret_by_alias(parsed.value).secret_id


def _secret_segment(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-") or "item"


def _secret_write_resource(write: dict[str, Any]) -> tuple[str | None, str | None]:
    resource_type = str(write.get("resource_type") or "").strip().lower()
    resource_id = str(write.get("resource_id") or "").strip().lower()
    if not resource_type and not resource_id:
        return None, None
    if not resource_type or not resource_id:
        raise SecretError("App secret writes must include both resource_type and resource_id.")
    return resource_type, resource_id


def _scoped_app_secret_id(
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> str:
    segments = ["app", workspace_id, app_id, logical_name]
    if resource_type and resource_id:
        segments.extend([resource_type, resource_id])
    return "-".join(_secret_segment(item) for item in segments)


def _scoped_app_secret_alias(
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> str:
    segments = [workspace_id, app_id, logical_name]
    if resource_type and resource_id:
        segments.extend([resource_type, resource_id])
    return "-".join(_secret_segment(item) for item in segments)


def _scoped_app_secret_grant_id(
    *,
    workspace_id: str,
    app_id: str,
    logical_name: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> str:
    segments = ["grant", workspace_id, app_id, logical_name]
    if resource_type and resource_id:
        segments.extend([resource_type, resource_id])
    return ":".join(_secret_segment(item) for item in segments)
