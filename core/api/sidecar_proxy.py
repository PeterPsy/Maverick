"""Governed HTTP proxy for app-owned local sidecar services."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
from threading import Lock
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, read_request_body_bytes, status_line
from core.api.platform_state import PlatformState
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.models import HttpSidecarRouteRule, HttpSidecarSpec
from core.authorization.errors import AuthorizationError
from core.authorization.service import can_mount_app_visibility, require_workspace_admin, require_workspace_membership
from core.identity.models import UserRecord
from core.shared.entrypoints import EntrypointShutdownController
from core.shared.repository import installation_paths
from core.workspaces.paths import workspace_paths


logger = logging.getLogger(__name__)

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_DEFAULT_PROXY_TIMEOUT_SECONDS = 60
_SIDECAR_MANAGER = None


@dataclass
class RunningSidecar:
    """One active sidecar process bound to a workspace app."""

    process: subprocess.Popen[bytes]
    host: str
    port: int
    token: str
    stdout_file: Any | None = None
    stderr_file: Any | None = None


class HttpSidecarManager:
    """Start and reuse app-owned HTTP sidecar processes."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._running: dict[tuple[str, str, str, str], RunningSidecar] = {}

    def ensure_running(
        self,
        *,
        workspace_id: str,
        app_id: str,
        source_root: Path,
        data_root: str,
        sidecar: HttpSidecarSpec,
        start_path: Path,
        shutdown_controller: EntrypointShutdownController | None,
    ) -> RunningSidecar:
        key = (workspace_id, app_id, sidecar.service_id, data_root)
        with self._lock:
            running = self._running.get(key)
            if running is not None and running.process.poll() is None:
                return running
            if running is not None:
                self._cleanup_sidecar(running, shutdown_controller=shutdown_controller)
                self._running.pop(key, None)
            running = self._start_sidecar(
                workspace_id=workspace_id,
                app_id=app_id,
                source_root=source_root,
                data_root=data_root,
                sidecar=sidecar,
                start_path=start_path,
                shutdown_controller=shutdown_controller,
            )
            self._running[key] = running
            return running

    def _start_sidecar(
        self,
        *,
        workspace_id: str,
        app_id: str,
        source_root: Path,
        data_root: str,
        sidecar: HttpSidecarSpec,
        start_path: Path,
        shutdown_controller: EntrypointShutdownController | None,
    ) -> RunningSidecar:
        host = sidecar.bind.host
        port = _allocate_loopback_port(host) if sidecar.bind.port == "auto" else int(sidecar.bind.port)
        token = secrets.token_urlsafe(32)
        workdir = (source_root / sidecar.working_directory).resolve()
        workspace = workspace_paths(workspace_id, start_path=start_path)
        stdout_file = _open_sidecar_log(workspace.root, sidecar.logs.stdout if sidecar.logs else None)
        stderr_file = _open_sidecar_log(workspace.root, sidecar.logs.stderr if sidecar.logs else None)
        env = _sidecar_env(
            workspace_id=workspace_id,
            app_id=app_id,
            data_root=data_root,
            source_root=source_root,
            workspace_root=workspace.root,
            port=port,
            token=token,
            sidecar=sidecar,
            start_path=start_path,
        )
        try:
            process = subprocess.Popen(
                sidecar.command,
                cwd=str(workdir),
                env=env,
                stdout=stdout_file or subprocess.DEVNULL,
                stderr=stderr_file or subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            _close_sidecar_logs(stdout_file, stderr_file)
            raise AppHostingError(f"HTTP sidecar `{sidecar.service_id}` failed to start: {error}") from error
        if shutdown_controller is not None:
            shutdown_controller.register(process)  # type: ignore[arg-type]
        running = RunningSidecar(
            process=process,
            host=host,
            port=port,
            token=token,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
        )
        try:
            _wait_for_sidecar_health(running, sidecar=sidecar)
        except AppHostingError:
            self._cleanup_sidecar(running, shutdown_controller=shutdown_controller)
            raise
        return running

    def _cleanup_sidecar(
        self,
        running: RunningSidecar,
        *,
        shutdown_controller: EntrypointShutdownController | None,
    ) -> None:
        process = running.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if shutdown_controller is not None:
            shutdown_controller.unregister(process)  # type: ignore[arg-type]
        _close_sidecar_logs(running.stdout_file, running.stderr_file)


def handle_app_sidecar_proxy(
    state: PlatformState,
    *,
    environ: dict,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    subpath: str,
    user: UserRecord | None,
    start_path: Path,
    start_response: StartResponse,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> list[bytes]:
    """Proxy one request to a declared app-owned HTTP sidecar."""
    if user is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
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
    try:
        require_workspace_membership(state.workspace_store, user=user, workspace_id=workspace_id)
    except AuthorizationError:
        return json_response(start_response, {"error": "workspace_not_available"}, status="403 Forbidden")
    if binding.source_kind == "workspace_local_project":
        try:
            require_workspace_admin(
                state.workspace_store,
                user=user,
                workspace_id=workspace_id,
                reason="workspace_local_sidecar_forbidden",
            )
        except AuthorizationError as error:
            return json_response(start_response, {"error": error.reason}, status="403 Forbidden")
    if not can_mount_app_visibility(
        state.workspace_store,
        user=user,
        workspace_id=workspace_id,
        platform_roles=parsed.contract.visibility.platform_roles,
        workspace_roles=parsed.contract.visibility.workspace_roles,
        capabilities=parsed.contract.visibility.capabilities,
    ):
        return json_response(start_response, {"error": "app_forbidden"}, status="403 Forbidden")
    sidecar = _find_sidecar(parsed.contract.services.http_sidecars, sidecar_id)
    if sidecar is None or sidecar.proxy is None:
        return json_response(start_response, {"error": "sidecar_not_found"}, status="404 Not Found")
    proxy_path = _proxy_path(subpath)
    route_mode = _route_mode(sidecar, method=method, path=proxy_path)
    if route_mode == "blocked":
        return json_response(
            start_response,
            {"error": "sidecar_route_blocked", "sidecar_id": sidecar.service_id},
            status="403 Forbidden",
        )
    if route_mode == "handled_by_core":
        return json_response(
            start_response,
            {"error": "sidecar_route_handled_by_core", "sidecar_id": sidecar.service_id},
            status="501 Not Implemented",
        )
    if route_mode != "pass_through":
        return json_response(
            start_response,
            {"error": "sidecar_route_not_allowed", "sidecar_id": sidecar.service_id},
            status="404 Not Found",
        )
    try:
        body = read_request_body_bytes(environ)
        running = _sidecar_manager().ensure_running(
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=source_root,
            data_root=binding.data_root,
            sidecar=sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
        return _proxy_to_running_sidecar(
            running,
            method=method,
            path=proxy_path,
            query_string=str(environ.get("QUERY_STRING") or ""),
            environ=environ,
            body=body,
            start_response=start_response,
        )
    except AppHostingError as error:
        logger.warning("App `%s` sidecar `%s` unavailable: %s", app_id, sidecar_id, error)
        return json_response(start_response, {"error": "sidecar_unavailable", "detail": str(error)}, status="503 Service Unavailable")
    except Exception:
        logger.exception("App `%s` sidecar `%s` proxy failed.", app_id, sidecar_id)
        return json_response(start_response, {"error": "sidecar_proxy_failed"}, status="502 Bad Gateway")


def _sidecar_manager() -> HttpSidecarManager:
    global _SIDECAR_MANAGER
    if _SIDECAR_MANAGER is None:
        _SIDECAR_MANAGER = HttpSidecarManager()
    return _SIDECAR_MANAGER


def _find_sidecar(sidecars: list[HttpSidecarSpec], sidecar_id: str) -> HttpSidecarSpec | None:
    for sidecar in sidecars:
        if sidecar.service_id == sidecar_id:
            return sidecar
    return None


def _route_mode(sidecar: HttpSidecarSpec, *, method: str, path: str) -> str:
    assert sidecar.proxy is not None
    policy = sidecar.proxy.route_policy
    if _matches_any(policy.blocked, method=method, path=path):
        return "blocked"
    if _matches_any(policy.handled_by_core, method=method, path=path):
        return "handled_by_core"
    if _matches_any(policy.pass_through, method=method, path=path):
        return "pass_through"
    return "not_allowed"


def _matches_any(rules: list[HttpSidecarRouteRule], *, method: str, path: str) -> bool:
    return any(_route_rule_matches(rule, method=method, path=path) for rule in rules)


def _route_rule_matches(rule: HttpSidecarRouteRule, *, method: str, path: str) -> bool:
    if rule.method is not None and rule.method != method and not (method == "HEAD" and rule.method == "GET"):
        return False
    prefix = rule.path_prefix.rstrip("/") or "/"
    return path == prefix or path.startswith(f"{prefix.rstrip('/')}/")


def _proxy_path(subpath: str) -> str:
    clean = quote(str(subpath or "").lstrip("/"), safe="/:@-._~!$&'()*+,;=")
    return f"/{clean}" if clean else "/"


def _proxy_to_running_sidecar(
    running: RunningSidecar,
    *,
    method: str,
    path: str,
    query_string: str,
    environ: dict,
    body: bytes,
    start_response: StartResponse,
) -> list[bytes]:
    upstream_path = f"{path}?{query_string}" if query_string else path
    connection = http.client.HTTPConnection(running.host, running.port, timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
    headers = _forward_request_headers(environ)
    headers["Authorization"] = f"Bearer {running.token}"
    if body:
        headers["Content-Length"] = str(len(body))
    try:
        connection.request(method, upstream_path, body=body if body else None, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
    except OSError as error:
        raise AppHostingError("HTTP sidecar is not reachable.") from error
    finally:
        connection.close()
    response_headers = _forward_response_headers(response.getheaders(), body_length=len(response_body))
    start_response(f"{response.status} {response.reason or status_line(response.status).split(' ', 1)[1]}", response_headers)
    if method == "HEAD":
        return []
    return [response_body]


def _forward_request_headers(environ: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in environ.items():
        if not key.startswith("HTTP_"):
            continue
        name = key.removeprefix("HTTP_").replace("_", "-").title()
        if name.lower() in _HOP_BY_HOP_HEADERS or name.lower() in {"host", "cookie", "authorization"}:
            continue
        headers[name] = str(value)
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = str(environ["CONTENT_TYPE"])
    return headers


def _forward_response_headers(headers: list[tuple[str, str]], *, body_length: int) -> list[tuple[str, str]]:
    forwarded: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered == "content-length":
            continue
        forwarded.append((name, value))
    forwarded.append(("Content-Length", str(body_length)))
    return forwarded


def _allocate_loopback_port(host: str) -> int:
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _open_sidecar_log(workspace_root: Path, relative_path: str | None):
    if not relative_path:
        return None
    path = (workspace_root / relative_path).resolve()
    root = workspace_root.resolve()
    if root != path and root not in path.parents:
        raise AppHostingError("Sidecar log path escapes workspace root.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("ab")


def _close_sidecar_logs(*files: Any | None) -> None:
    seen: set[int] = set()
    for file_obj in files:
        if file_obj is None or id(file_obj) in seen:
            continue
        seen.add(id(file_obj))
        try:
            file_obj.close()
        except OSError:
            pass


def _sidecar_env(
    *,
    workspace_id: str,
    app_id: str,
    data_root: str,
    source_root: Path,
    workspace_root: Path,
    port: int,
    token: str,
    sidecar: HttpSidecarSpec,
    start_path: Path,
) -> dict[str, str]:
    env = dict(os.environ)
    repository_root = str(installation_paths(start_path=start_path).repository_root)
    env["PYTHONPATH"] = repository_root if not env.get("PYTHONPATH") else f"{repository_root}{os.pathsep}{env['PYTHONPATH']}"
    substitutions = {
        "${service.port}": str(port),
        "${service_secret:od_api_token}": token,
        "${app.data_dir}": data_root,
        "${app.source_dir}": str(source_root),
        "${workspace.root}": str(workspace_root),
    }
    for key, value in sidecar.env.items():
        env[key] = _replace_substitutions(value, substitutions)
    env.setdefault("MAVERICK_APP_ID", app_id)
    env.setdefault("MAVERICK_WORKSPACE_ID", workspace_id)
    env.setdefault("MAVERICK_SIDECAR_ID", sidecar.service_id)
    env.setdefault("MAVERICK_SIDECAR_PORT", str(port))
    return env


def _replace_substitutions(value: str, substitutions: dict[str, str]) -> str:
    result = value
    for token, replacement in substitutions.items():
        result = result.replace(token, replacement)
    return result


def _wait_for_sidecar_health(running: RunningSidecar, *, sidecar: HttpSidecarSpec) -> None:
    deadline = time.monotonic() + (sidecar.health.timeout_ms / 1000)
    url = f"http://{running.host}:{running.port}{sidecar.health.path}"
    last_error = "not ready"
    while time.monotonic() < deadline:
        if running.process.poll() is not None:
            raise AppHostingError(f"HTTP sidecar exited with code {running.process.returncode}.")
        try:
            request = Request(url, headers={"Authorization": f"Bearer {running.token}"}, method="GET")
            with urlopen(request, timeout=1.5) as response:
                if 200 <= response.status < 500:
                    return
                last_error = f"health returned HTTP {response.status}"
        except HTTPError as error:
            if 200 <= error.code < 500:
                return
            last_error = f"health returned HTTP {error.code}"
        except (OSError, URLError) as error:
            last_error = str(error)
        time.sleep(0.1)
    raise AppHostingError(f"HTTP sidecar `{sidecar.service_id}` did not become ready: {last_error}")
