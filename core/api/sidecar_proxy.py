"""Governed HTTP proxy for app-owned local sidecar services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import http.client
import logging
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
from threading import BoundedSemaphore, Lock
import time
from typing import Any, AsyncIterator, Callable, Iterable, Iterator
from urllib.parse import quote

from core.api.app_registry import resolve_app_surface
from core.api.http import StartResponse, json_response, read_request_body_bytes, status_line
from core.api.platform_state import PlatformState
from core.api.sidecar_core_routes import (
    SidecarCoreRouteContext,
    handle_core_sidecar_route,
    handle_core_sidecar_route_asgi,
)
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.models import (
    HttpSidecarRouteRule,
    HttpSidecarSpec,
    ParsedAppContract,
    WorkspaceAppBindingRecord,
)
from core.apps.sidecar_execution import (
    ConfinedSidecarLaunch,
    MINIMAL_SIDECAR_ENV,
    prepare_confined_sidecar_launch,
    relay_preamble,
    sandbox_substitutions,
)
from core.authorization.errors import AuthorizationError
from core.authorization.service import can_mount_app_visibility, require_workspace_admin, require_workspace_membership
from core.identity.models import UserRecord
from core.shared.entrypoints import EntrypointShutdownController
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
_PROXY_CHUNK_SIZE = 64 * 1024
_REQUEST_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SIDECAR_MANAGER = None
AsgiReceive = Any
AsgiSend = Any


@dataclass
class RunningSidecar:
    """One active sidecar process bound to a workspace app."""

    process: subprocess.Popen[bytes]
    host: str
    port: int
    token: str
    instance_id: str
    confined_launch: ConfinedSidecarLaunch
    request_slots: BoundedSemaphore
    stdout_file: Any | None = None
    stderr_file: Any | None = None
    cleanup_callback: Callable[[], None] | None = None
    shutdown_controller: EntrypointShutdownController | None = None
    cleanup_lock: Lock = field(default_factory=Lock)
    cleaned: bool = False


@dataclass(frozen=True)
class SidecarProxyTarget:
    """Validated sidecar proxy request after policy and authorization checks."""

    source_root: Path
    data_root: str
    parsed: ParsedAppContract
    sidecar: HttpSidecarSpec
    proxy_path: str
    route_mode: str


@dataclass(frozen=True)
class AuthorizedSidecarTarget:
    """Sidecar identity authorized for one actor before route selection."""

    binding: WorkspaceAppBindingRecord
    source_root: Path
    parsed: ParsedAppContract
    sidecar: HttpSidecarSpec


@dataclass(frozen=True)
class SidecarProxyError:
    """Small shared error shape for WSGI and ASGI sidecar responses."""

    payload: dict[str, Any]
    status: str


class StreamingSidecarResponse:
    """Iterator that streams an open http.client response and closes it."""

    def __init__(
        self,
        connection: http.client.HTTPConnection,
        response: http.client.HTTPResponse,
        *,
        method: str,
        release_slot: Callable[[], None],
    ) -> None:
        self._connection = connection
        self._response = response
        self._method = method
        self._release_slot = release_slot
        self._closed = False

    def __iter__(self) -> Iterator[bytes]:
        try:
            if self._method == "HEAD":
                return
            while True:
                chunk = self._response.read(_PROXY_CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connection.close()
        self._release_slot()


class UnixRelayHTTPConnection(http.client.HTTPConnection):
    """HTTP connection authenticated to a private Unix relay."""

    def __init__(self, running: RunningSidecar, *, timeout: float) -> None:
        super().__init__(running.host, running.port, timeout=timeout)
        self._relay_socket = running.confined_launch.relay_socket
        self._relay_preamble = relay_preamble(running.confined_launch.relay_capability)

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self._relay_socket))
            sock.sendall(self._relay_preamble)
        except OSError:
            sock.close()
            raise
        self.sock = sock


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
                self._cleanup_sidecar(running)
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
        workspace = workspace_paths(workspace_id, start_path=start_path)
        stdout_file = _open_sidecar_log(workspace.root, sidecar.logs.stdout if sidecar.logs else None)
        stderr_file = _open_sidecar_log(workspace.root, sidecar.logs.stderr if sidecar.logs else None)
        try:
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
            confined_launch = prepare_confined_sidecar_launch(
                workspace_id=workspace_id,
                app_id=app_id,
                source_root=source_root,
                data_root=Path(data_root),
                workspace_root=workspace.root,
                sidecar=sidecar,
                port=port,
                env=env,
            )
        except Exception:
            _close_sidecar_logs(stdout_file, stderr_file)
            raise
        try:
            process = subprocess.Popen(
                confined_launch.command,
                cwd="/",
                env=confined_launch.env,
                stdout=stdout_file or subprocess.DEVNULL,
                stderr=stderr_file or subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=confined_launch.pass_fds,
            )
        except OSError as error:
            confined_launch.cleanup()
            _close_sidecar_logs(stdout_file, stderr_file)
            raise AppHostingError(f"HTTP sidecar `{sidecar.service_id}` failed to start: {error}") from error
        finally:
            confined_launch.close_parent_fds()
        running = RunningSidecar(
            process=process,
            host=host,
            port=port,
            token=token,
            instance_id=secrets.token_urlsafe(18),
            confined_launch=confined_launch,
            request_slots=BoundedSemaphore(sidecar.process_policy.limits.request_concurrency),
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            shutdown_controller=shutdown_controller,
        )
        if shutdown_controller is not None:
            shutdown_controller.register(process)  # type: ignore[arg-type]

            def cleanup_callback() -> None:
                self._cleanup_sidecar(running)

            running.cleanup_callback = cleanup_callback
            shutdown_controller.register_cleanup(cleanup_callback)
        try:
            _wait_for_sidecar_health(running, sidecar=sidecar)
        except AppHostingError:
            self._cleanup_sidecar(running)
            raise
        return running

    def stop_app(self, *, workspace_id: str, app_id: str) -> None:
        """Stop every running sidecar owned by one workspace app."""
        with self._lock:
            keys = [key for key in self._running if key[:2] == (workspace_id, app_id)]
            running_sidecars = [self._running.pop(key) for key in keys]
            for running in running_sidecars:
                self._cleanup_sidecar(running)

    def current_instance_id(
        self,
        *,
        workspace_id: str,
        app_id: str,
        sidecar_id: str,
        data_root: str,
    ) -> str | None:
        """Return the live process identity without starting or restarting it."""
        key = (workspace_id, app_id, sidecar_id, data_root)
        with self._lock:
            running = self._running.get(key)
            if running is None or running.process.poll() is not None:
                return None
            return running.instance_id

    def _cleanup_sidecar(self, running: RunningSidecar) -> None:
        with running.cleanup_lock:
            if running.cleaned:
                return
            process = running.process
            if process.poll() is None:
                _signal_process_group(process, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _signal_process_group(process, signal.SIGKILL)
                    process.wait(timeout=5)
            if running.shutdown_controller is not None:
                running.shutdown_controller.unregister(process)  # type: ignore[arg-type]
                if running.cleanup_callback is not None:
                    running.shutdown_controller.unregister_cleanup(running.cleanup_callback)
            running.confined_launch.cleanup()
            _close_sidecar_logs(running.stdout_file, running.stderr_file)
            running.cleaned = True


def stop_app_sidecars(*, workspace_id: str, app_id: str) -> None:
    """Stop an app's live sidecars without creating a manager as a side effect."""
    manager = _SIDECAR_MANAGER
    if manager is not None:
        manager.stop_app(workspace_id=workspace_id, app_id=app_id)


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
) -> Iterable[bytes]:
    """Proxy one request to a declared app-owned HTTP sidecar."""
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    target, error = _resolve_sidecar_proxy_target(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        subpath=subpath,
        user=user,
        method=method,
        start_path=start_path,
    )
    if error is not None:
        return json_response(start_response, error.payload, status=error.status)
    assert target is not None
    try:
        if target.route_mode == "handled_by_core":
            return handle_core_sidecar_route(
                state,
                environ=environ,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                context=_core_route_context(target),
                start_path=start_path,
                start_response=start_response,
                shutdown_controller=shutdown_controller,
                logger=logger,
            )
        body = read_request_body_bytes(environ)
        running = _sidecar_manager().ensure_running(
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=target.source_root,
            data_root=target.data_root,
            sidecar=target.sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
        return _proxy_to_running_sidecar(
            running,
            method=method,
            path=target.proxy_path,
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


async def handle_app_sidecar_proxy_asgi(
    state: PlatformState,
    *,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    subpath: str,
    user: UserRecord | None,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None = None,
    enforced_response_headers: list[tuple[str, str]] | None = None,
    expected_instance_id: str | None = None,
) -> None:
    """Proxy one ASGI request to a declared sidecar without pre-buffering the body."""
    method = str(scope.get("method") or "GET").upper()
    target, error = _resolve_sidecar_proxy_target(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        subpath=subpath,
        user=user,
        method=method,
        start_path=start_path,
    )
    if error is not None:
        await _send_asgi_json(send, error.payload, status=error.status, headers=enforced_response_headers)
        return
    assert target is not None
    try:
        if target.route_mode == "handled_by_core":
            await handle_core_sidecar_route_asgi(
                state,
                scope=scope,
                receive=receive,
                send=send,
                workspace_id=workspace_id,
                app_id=app_id,
                user=user,
                context=_core_route_context(target),
                start_path=start_path,
                shutdown_controller=shutdown_controller,
                logger=logger,
                response_headers=enforced_response_headers,
            )
            return
        running = await asyncio.to_thread(
            _sidecar_manager().ensure_running,
            workspace_id=workspace_id,
            app_id=app_id,
            source_root=target.source_root,
            data_root=target.data_root,
            sidecar=target.sidecar,
            start_path=start_path,
            shutdown_controller=shutdown_controller,
        )
        if expected_instance_id is not None and running.instance_id != expected_instance_id:
            await _send_asgi_json(
                send,
                {"error": "sidecar_session_stale"},
                status="401 Unauthorized",
                headers=enforced_response_headers,
            )
            return
        await _proxy_asgi_to_running_sidecar(
            running,
            method=method,
            path=target.proxy_path,
            query_string=bytes(scope.get("query_string") or b"").decode("latin1"),
            scope=scope,
            sidecar=target.sidecar,
            receive=receive,
            send=send,
            enforced_response_headers=enforced_response_headers,
        )
    except AppHostingError as error:
        logger.warning("App `%s` sidecar `%s` unavailable: %s", app_id, sidecar_id, error)
        await _send_asgi_json(
            send,
            {"error": "sidecar_unavailable", "detail": str(error)},
            status="503 Service Unavailable",
            headers=enforced_response_headers,
        )
    except Exception:
        logger.exception("App `%s` sidecar `%s` ASGI proxy failed.", app_id, sidecar_id)
        await _send_asgi_json(
            send,
            {"error": "sidecar_proxy_failed"},
            status="502 Bad Gateway",
            headers=enforced_response_headers,
        )


def parse_app_sidecar_proxy_route(path: object) -> tuple[str, str, str] | None:
    """Parse the generic app sidecar proxy route."""
    text = str(path or "")
    if not text.startswith("/api/apps/"):
        return None
    remainder = text.removeprefix("/api/apps/")
    app_id, separator, rest = remainder.partition("/sidecars/")
    if not separator or not app_id or "/" in app_id or not rest:
        return None
    sidecar_id, _separator, subpath = rest.partition("/")
    if not sidecar_id or "/" in sidecar_id:
        return None
    return app_id, sidecar_id, subpath


def _sidecar_manager() -> HttpSidecarManager:
    global _SIDECAR_MANAGER
    if _SIDECAR_MANAGER is None:
        _SIDECAR_MANAGER = HttpSidecarManager()
    return _SIDECAR_MANAGER


def _resolve_sidecar_proxy_target(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    subpath: str,
    user: UserRecord | None,
    method: str,
    start_path: Path,
) -> tuple[SidecarProxyTarget | None, SidecarProxyError | None]:
    authorized, error = resolve_authorized_sidecar(
        state,
        workspace_id=workspace_id,
        app_id=app_id,
        sidecar_id=sidecar_id,
        user=user,
        start_path=start_path,
    )
    if error is not None:
        return None, error
    assert authorized is not None
    binding = authorized.binding
    source_root = authorized.source_root
    parsed = authorized.parsed
    sidecar = authorized.sidecar
    proxy_path = _proxy_path(subpath)
    route_mode = _route_mode(sidecar, method=method, path=proxy_path)
    if route_mode == "blocked":
        return None, SidecarProxyError(
            {"error": "sidecar_route_blocked", "sidecar_id": sidecar.service_id},
            "403 Forbidden",
        )
    if route_mode not in {"handled_by_core", "pass_through"}:
        return None, SidecarProxyError(
            {"error": "sidecar_route_not_allowed", "sidecar_id": sidecar.service_id},
            "404 Not Found",
        )
    return SidecarProxyTarget(
        source_root=source_root,
        data_root=binding.data_root,
        parsed=parsed,
        sidecar=sidecar,
        proxy_path=proxy_path,
        route_mode=route_mode,
    ), None


def resolve_authorized_sidecar(
    state: PlatformState,
    *,
    workspace_id: str,
    app_id: str,
    sidecar_id: str,
    user: UserRecord | None,
    start_path: Path,
) -> tuple[AuthorizedSidecarTarget | None, SidecarProxyError | None]:
    """Resolve one sidecar and actor without granting any route."""
    if user is None:
        return None, SidecarProxyError({"error": "authentication_required"}, "401 Unauthorized")
    try:
        binding, source_root, parsed = resolve_app_surface(
            state,
            workspace_id=workspace_id,
            app_id=app_id,
            start_path=start_path,
        )
    except WorkspaceAppBindingNotFoundError:
        return None, SidecarProxyError({"error": "app_not_installed"}, "404 Not Found")
    except AppHostingError:
        return None, SidecarProxyError({"error": "app_unavailable"}, "404 Not Found")
    try:
        require_workspace_membership(state.workspace_store, user=user, workspace_id=workspace_id)
    except AuthorizationError:
        return None, SidecarProxyError({"error": "workspace_not_available"}, "403 Forbidden")
    if binding.source_kind == "workspace_local_project":
        try:
            require_workspace_admin(
                state.workspace_store,
                user=user,
                workspace_id=workspace_id,
                reason="workspace_local_sidecar_forbidden",
            )
        except AuthorizationError as error:
            return None, SidecarProxyError({"error": error.reason}, "403 Forbidden")
    if not can_mount_app_visibility(
        state.workspace_store,
        user=user,
        workspace_id=workspace_id,
        platform_roles=parsed.contract.visibility.platform_roles,
        workspace_roles=parsed.contract.visibility.workspace_roles,
        capabilities=parsed.contract.visibility.capabilities,
    ):
        return None, SidecarProxyError({"error": "app_forbidden"}, "403 Forbidden")
    sidecar = _find_sidecar(parsed.contract.services.http_sidecars, sidecar_id)
    if sidecar is None or sidecar.proxy is None:
        return None, SidecarProxyError({"error": "sidecar_not_found"}, "404 Not Found")
    return AuthorizedSidecarTarget(
        binding=binding,
        source_root=source_root,
        parsed=parsed,
        sidecar=sidecar,
    ), None


def ensure_authorized_sidecar_running(
    target: AuthorizedSidecarTarget,
    *,
    start_path: Path,
    shutdown_controller: EntrypointShutdownController | None,
) -> RunningSidecar:
    """Start or reuse an already-authorized sidecar for browser bootstrap."""
    return _sidecar_manager().ensure_running(
        workspace_id=target.binding.workspace_id,
        app_id=target.binding.app_id,
        source_root=target.source_root,
        data_root=target.binding.data_root,
        sidecar=target.sidecar,
        start_path=start_path,
        shutdown_controller=shutdown_controller,
    )


def current_sidecar_instance_id(target: AuthorizedSidecarTarget) -> str | None:
    """Return the current process identity for session restart validation."""
    return _sidecar_manager().current_instance_id(
        workspace_id=target.binding.workspace_id,
        app_id=target.binding.app_id,
        sidecar_id=target.sidecar.service_id,
        data_root=target.binding.data_root,
    )


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


def _core_route_context(target: SidecarProxyTarget) -> SidecarCoreRouteContext:
    return SidecarCoreRouteContext(
        source_root=target.source_root,
        data_root=target.data_root,
        parsed=target.parsed,
        sidecar=target.sidecar,
        proxy_path=target.proxy_path,
    )


def _proxy_to_running_sidecar(
    running: RunningSidecar,
    *,
    method: str,
    path: str,
    query_string: str,
    environ: dict,
    body: bytes,
    start_response: StartResponse,
) -> Iterable[bytes]:
    upstream_path = f"{path}?{query_string}" if query_string else path
    if not running.request_slots.acquire(blocking=False):
        raise AppHostingError("HTTP sidecar request concurrency limit reached.")
    connection = UnixRelayHTTPConnection(running, timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
    headers = _forward_request_headers(environ)
    headers["Authorization"] = f"Bearer {running.token}"
    if body:
        headers["Content-Length"] = str(len(body))
    try:
        connection.request(method, upstream_path, body=body if body else None, headers=headers)
        response = connection.getresponse()
    except (OSError, http.client.HTTPException) as error:
        connection.close()
        running.request_slots.release()
        raise AppHostingError("HTTP sidecar is not reachable.") from error
    try:
        response_headers = _forward_response_headers(response.getheaders())
        start_response(
            f"{response.status} {response.reason or status_line(response.status).split(' ', 1)[1]}",
            response_headers,
        )
    except Exception:
        connection.close()
        running.request_slots.release()
        raise
    return StreamingSidecarResponse(
        connection,
        response,
        method=method,
        release_slot=running.request_slots.release,
    )


async def _proxy_asgi_to_running_sidecar(
    running: RunningSidecar,
    *,
    method: str,
    path: str,
    query_string: str,
    scope: dict[str, Any],
    sidecar: HttpSidecarSpec,
    receive: AsgiReceive,
    send: AsgiSend,
    enforced_response_headers: list[tuple[str, str]] | None,
) -> None:
    upstream_path = f"{path}?{query_string}" if query_string else path
    if not running.request_slots.acquire(blocking=False):
        raise AppHostingError("HTTP sidecar request concurrency limit reached.")
    writer: asyncio.StreamWriter | None = None
    response_started = False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(running.confined_launch.relay_socket)),
            timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS,
        )
        writer.write(relay_preamble(running.confined_launch.relay_capability))
        await writer.drain()
        request_headers = _forward_asgi_request_headers(scope)
        stream_request_as_chunked = method in _REQUEST_BODY_METHODS and not _asgi_header_present(scope, "content-length")
        request_headers["Host"] = f"{running.host}:{running.port}"
        request_headers["Authorization"] = f"Bearer {running.token}"
        request_headers["Connection"] = "close"
        if stream_request_as_chunked:
            request_headers["Transfer-Encoding"] = "chunked"
        header_lines = [f"{method} {upstream_path} HTTP/1.1"]
        header_lines.extend(f"{name}: {value}" for name, value in request_headers.items())
        header_lines.append("")
        header_lines.append("")
        writer.write("\r\n".join(header_lines).encode("latin1"))
        await writer.drain()
        await _stream_asgi_request_body(receive, writer, chunked=stream_request_as_chunked)
        response_status, _response_reason, response_headers = await _read_asgi_upstream_response_head(reader)
        _ensure_asgi_response_allowed_by_contract(sidecar, response_headers)
        forwarded_headers = _merge_response_headers(
            _forward_asgi_response_headers(response_headers),
            enforced_response_headers,
        )
        await send(
            {
                "type": "http.response.start",
                "status": response_status,
                "headers": [
                    (name.lower().encode("latin1"), value.encode("latin1"))
                    for name, value in forwarded_headers
                ],
            }
        )
        response_started = True
        if method != "HEAD":
            async for chunk in _stream_asgi_upstream_response_body(reader, response_headers):
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
    except OSError as error:
        if not response_started:
            raise AppHostingError("HTTP sidecar is not reachable.") from error
        logger.warning("HTTP sidecar stream ended with a socket error.", exc_info=True)
    except Exception:
        if not response_started:
            raise
        logger.warning("HTTP sidecar stream ended with an upstream protocol error.", exc_info=True)
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        running.request_slots.release()
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def _stream_asgi_request_body(receive: AsgiReceive, writer: asyncio.StreamWriter, *, chunked: bool) -> None:
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            if chunked:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
            return
        chunk = bytes(message.get("body") or b"")
        if chunk:
            if chunked:
                writer.write(f"{len(chunk):x}\r\n".encode("ascii"))
                writer.write(chunk)
                writer.write(b"\r\n")
            else:
                writer.write(chunk)
            await writer.drain()
        if not message.get("more_body", False):
            if chunked:
                writer.write(b"0\r\n\r\n")
                await writer.drain()
            return


async def _read_asgi_upstream_response_head(reader: asyncio.StreamReader) -> tuple[int, str, list[tuple[str, str]]]:
    status_line_bytes = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
    if not status_line_bytes:
        raise AppHostingError("HTTP sidecar closed before sending a response.")
    try:
        status_parts = status_line_bytes.decode("latin1").rstrip("\r\n").split(" ", 2)
        status_code = int(status_parts[1])
        reason = status_parts[2] if len(status_parts) > 2 else ""
    except (UnicodeDecodeError, ValueError, IndexError) as error:
        raise AppHostingError("HTTP sidecar returned an invalid HTTP response.") from error
    headers: list[tuple[str, str]] = []
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if line in {b"\r\n", b"\n", b""}:
            break
        try:
            name, value = line.decode("latin1").rstrip("\r\n").split(":", 1)
        except ValueError as error:
            raise AppHostingError("HTTP sidecar returned an invalid HTTP header.") from error
        headers.append((name.strip(), value.strip()))
    return status_code, reason, headers


async def _stream_asgi_upstream_response_body(
    reader: asyncio.StreamReader,
    headers: list[tuple[str, str]],
) -> AsyncIterator[bytes]:
    lowered = {name.lower(): value for name, value in headers}
    transfer_encoding = lowered.get("transfer-encoding", "").lower()
    content_length = lowered.get("content-length")
    if "chunked" in transfer_encoding:
        async for chunk in _stream_chunked_asgi_body(reader):
            yield chunk
        return
    if content_length is not None:
        try:
            remaining = int(content_length)
        except ValueError as error:
            raise AppHostingError("HTTP sidecar returned an invalid Content-Length header.") from error
        while remaining > 0:
            chunk = await asyncio.wait_for(
                reader.read(min(_PROXY_CHUNK_SIZE, remaining)),
                timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS,
            )
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
        return
    while True:
        chunk = await asyncio.wait_for(reader.read(_PROXY_CHUNK_SIZE), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if not chunk:
            return
        yield chunk


async def _stream_chunked_asgi_body(reader: asyncio.StreamReader) -> AsyncIterator[bytes]:
    while True:
        size_line = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if not size_line:
            return
        size_text = size_line.decode("latin1").strip().split(";", 1)[0]
        try:
            size = int(size_text, 16)
        except ValueError as error:
            raise AppHostingError("HTTP sidecar returned an invalid chunked response.") from error
        if size == 0:
            await _discard_chunked_trailers(reader)
            return
        remaining = size
        while remaining > 0:
            chunk = await asyncio.wait_for(
                reader.read(min(_PROXY_CHUNK_SIZE, remaining)),
                timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS,
            )
            if not chunk:
                return
            remaining -= len(chunk)
            yield chunk
        await asyncio.wait_for(reader.readexactly(2), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)


async def _discard_chunked_trailers(reader: asyncio.StreamReader) -> None:
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=_DEFAULT_PROXY_TIMEOUT_SECONDS)
        if line in {b"\r\n", b"\n", b""}:
            return


def _ensure_asgi_response_allowed_by_contract(sidecar: HttpSidecarSpec, headers: list[tuple[str, str]]) -> None:
    if sidecar.proxy is None:
        return
    content_type = ""
    for name, value in headers:
        if name.lower() == "content-type":
            content_type = value.split(";", 1)[0].strip().lower()
            break
    if content_type == "text/event-stream" and not sidecar.proxy.sse:
        raise AppHostingError("HTTP sidecar returned SSE without declaring `proxy.sse` support.")


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


def _forward_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    forwarded: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered in {"authorization", "set-cookie"}:
            continue
        if lowered == "location" and not _safe_redirect_location(value):
            continue
        forwarded.append((name, value))
    return forwarded


def _forward_asgi_request_headers(scope: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin1").replace("_", "-").title()
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered in {"host", "cookie", "authorization"}:
            continue
        headers[name] = raw_value.decode("latin1")
    return headers


def _asgi_header_present(scope: dict[str, Any], header_name: str) -> bool:
    expected = header_name.lower().encode("latin1")
    return any(raw_name.lower() == expected for raw_name, _raw_value in scope.get("headers", []))


def _forward_asgi_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    forwarded: list[tuple[str, str]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _HOP_BY_HOP_HEADERS or lowered in {"authorization", "set-cookie"}:
            continue
        if lowered == "location" and not _safe_redirect_location(value):
            continue
        forwarded.append((name, value))
    return forwarded


def _safe_redirect_location(value: str) -> bool:
    return value.startswith("/") and not value.startswith("//") and "\\" not in value and not any(
        ord(character) < 32 for character in value
    )


def _merge_response_headers(
    headers: list[tuple[str, str]],
    enforced: list[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    if not enforced:
        return headers
    enforced_names = {name.lower() for name, _value in enforced}
    return [(name, value) for name, value in headers if name.lower() not in enforced_names] + list(enforced)


async def _send_asgi_json(
    send: AsgiSend,
    payload: dict[str, Any],
    *,
    status: str,
    headers: list[tuple[str, str]] | None = None,
) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    status_code = int(status.split(" ", 1)[0])
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                *[(name.lower().encode("latin1"), value.encode("latin1")) for name, value in (headers or [])],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


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
    del data_root, source_root, workspace_root, start_path
    env = dict(MINIMAL_SIDECAR_ENV)
    substitutions = sandbox_substitutions(port=port, token=token)
    for key, value in sidecar.env.items():
        env[key] = _replace_substitutions(value, substitutions)
    env["MAVERICK_APP_ID"] = app_id
    env["MAVERICK_WORKSPACE_ID"] = workspace_id
    env["MAVERICK_SIDECAR_ID"] = sidecar.service_id
    env["MAVERICK_SIDECAR_PORT"] = str(port)
    return env


def _replace_substitutions(value: str, substitutions: dict[str, str]) -> str:
    result = value
    for token, replacement in substitutions.items():
        result = result.replace(token, replacement)
    if "${" in result:
        raise AppHostingError("HTTP sidecar environment contains an unsupported substitution.")
    return result


def _wait_for_sidecar_health(running: RunningSidecar, *, sidecar: HttpSidecarSpec) -> None:
    deadline = time.monotonic() + (sidecar.health.timeout_ms / 1000)
    last_error = "not ready"
    while time.monotonic() < deadline:
        if running.process.poll() is not None:
            raise AppHostingError(f"HTTP sidecar exited with code {running.process.returncode}.")
        connection = UnixRelayHTTPConnection(running, timeout=1.5)
        try:
            connection.request(
                "GET",
                sidecar.health.path,
                headers={
                    "Authorization": f"Bearer {running.token}",
                    "Connection": "close",
                    "Host": f"{running.host}:{running.port}",
                },
            )
            response = connection.getresponse()
            if 200 <= response.status < 300:
                return
            last_error = f"health returned HTTP {response.status}"
        except (OSError, http.client.HTTPException) as error:
            last_error = str(error)
        finally:
            connection.close()
        time.sleep(0.1)
    raise AppHostingError(f"HTTP sidecar `{sidecar.service_id}` did not become ready: {last_error}")


def _signal_process_group(process: subprocess.Popen[bytes], signum: signal.Signals) -> None:
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        if process.poll() is None:
            if signum == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
