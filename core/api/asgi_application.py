"""ASGI host for Maverick HTTP and WebSocket surfaces."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from functools import partial
from io import BytesIO
import json
import os
from typing import Any, Awaitable, Callable, Iterable, Iterator

from core.api.app_events import APP_EVENTS_WS_PATH, stream_app_events
from core.api.backend_recovery import start_backend_restart_recovery
from core.api.background_hooks import start_background_hook_scheduler
from core.api.http import max_json_body_bytes
from core.api.inter_agent_websocket import INTER_AGENT_RUN_WS_PREFIX, stream_inter_agent_run_events
from core.api.job_websocket import JOB_EVENTS_WS_PATH, stream_job_events
from core.api.platform_host import PlatformHost
from core.api.platform_state import PlatformState, bootstrap_platform_state
from core.api.runtime_thread_websocket import RUNTIME_THREADS_WS_PATH, stream_runtime_thread_events
from core.api.runtime_websocket import RUNTIME_SESSION_WS_PREFIX, stream_runtime_session_events
from core.api.session_api import resolve_request_session
from core.api.sidecar_browser import handle_sidecar_browser_origin, is_reserved_sidecar_browser_host
from core.api.sidecar_prewarm import start_declared_sidecar_prewarms
from core.api.sidecar_control import start_sidecar_control_server
from core.api.sidecar_proxy import handle_app_sidecar_proxy_asgi, parse_app_sidecar_proxy_route
from core.api.http import HttpRequestError, enforce_same_origin_for_unsafe_request
from core.shared.entrypoints import EntrypointShutdownController


AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]


class PlatformAsgiHost:
    """Expose the platform host through ASGI, including runtime WebSockets."""

    def __init__(
        self,
        state: PlatformState | None = None,
        *,
        shutdown_controller: EntrypointShutdownController | None = None,
    ) -> None:
        self.state = state or bootstrap_platform_state()
        self.shutdown_controller = shutdown_controller or EntrypointShutdownController()
        self.app_backend_executor = ThreadPoolExecutor(
            max_workers=_app_backend_worker_count(),
            thread_name_prefix="maverick-app-backend",
        )
        if state is None:
            start_backend_restart_recovery(self.state)
            start_background_hook_scheduler(self.state, shutdown_controller=self.shutdown_controller)
            start_declared_sidecar_prewarms(
                self.state,
                trigger="core_start",
                shutdown_controller=self.shutdown_controller,
            )
            start_sidecar_control_server(
                self.state,
                shutdown_controller=self.shutdown_controller,
            )
        self.http_host = PlatformHost(
            self.state,
            start_path=self.state.repository_root,
            shutdown_controller=self.shutdown_controller,
        )

    async def __call__(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(receive, send)
            return
        if scope_type == "websocket":
            await self._handle_websocket(scope, receive, send)
            return
        if scope_type == "http":
            await self._handle_http(scope, receive, send)
            return
        raise RuntimeError(f"Unsupported ASGI scope type: {scope_type}")

    async def _handle_websocket(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        path = str(scope.get("path") or "")
        if path == JOB_EVENTS_WS_PATH:
            context = resolve_request_session(self.state, _websocket_environ(scope))
            if context is None:
                await send({"type": "websocket.close", "code": 4401})
                return
            await stream_job_events(
                service=self.state.job_service,
                bus=self.state.job_event_bus,
                scope=scope,
                receive=receive,
                send=send,
                workspace_id=context.workspace_id,
                shutdown_controller=self.shutdown_controller,
            )
            return
        if path == APP_EVENTS_WS_PATH:
            context = resolve_request_session(self.state, _websocket_environ(scope))
            if context is None:
                await send({"type": "websocket.close", "code": 4401})
                return
            await stream_app_events(
                bus=self.state.app_event_bus,
                scope=scope,
                receive=receive,
                send=send,
                workspace_id=context.workspace_id,
                shutdown_controller=self.shutdown_controller,
            )
            return
        if path == RUNTIME_THREADS_WS_PATH:
            await stream_runtime_thread_events(
                state=self.state,
                scope=scope,
                receive=receive,
                send=send,
                shutdown_controller=self.shutdown_controller,
            )
            return
        if path.startswith(INTER_AGENT_RUN_WS_PREFIX):
            await stream_inter_agent_run_events(
                state=self.state,
                scope=scope,
                receive=receive,
                send=send,
                shutdown_controller=self.shutdown_controller,
            )
            return
        if not path.startswith(RUNTIME_SESSION_WS_PREFIX):
            await send({"type": "websocket.close", "code": 4404})
            return
        await stream_runtime_session_events(
            state=self.state,
            scope=scope,
            receive=receive,
            send=send,
            shutdown_controller=self.shutdown_controller,
        )

    async def _handle_lifespan(self, receive: AsgiReceive, send: AsgiSend) -> None:
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
                continue
            if message_type == "lifespan.shutdown":
                self.shutdown_controller.begin_shutdown()
                self.app_backend_executor.shutdown(wait=False, cancel_futures=True)
                await send({"type": "lifespan.shutdown.complete"})
                return
            raise RuntimeError(f"Unsupported ASGI lifespan event: {message_type}")

    async def _handle_http(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        if is_reserved_sidecar_browser_host(scope):
            await handle_sidecar_browser_origin(
                self.state,
                scope=scope,
                receive=receive,
                send=send,
                start_path=self.state.repository_root,
                shutdown_controller=self.shutdown_controller,
            )
            return
        if scope.get("path") == "/health":
            await _send_direct_json_response(send, b'{\n  "status": "ok",\n  "service": "maverick-core"\n}')
            return
        sidecar_route = parse_app_sidecar_proxy_route(scope.get("path"))
        if sidecar_route is not None:
            await self._handle_sidecar_http(scope, receive, send, sidecar_route)
            return
        try:
            body = await _read_asgi_body(receive)
        except ValueError:
            response_body = b'{\n  "error": "request_body_too_large"\n}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(response_body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response_body, "more_body": False})
            return
        status_holder: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            status_holder["status"] = int(status.split(" ", 1)[0])
            status_holder["headers"] = [(name.encode("latin1"), value.encode("latin1")) for name, value in headers]

        environ = _wsgi_environ(scope, body)
        use_app_backend_executor = _is_app_backend_request(scope)
        loop = asyncio.get_running_loop()
        request_shutdown_controller: EntrypointShutdownController | None = None
        disconnect_task: asyncio.Task[bool] | None = None
        if use_app_backend_executor:
            request_shutdown_controller = EntrypointShutdownController(
                parent=self.shutdown_controller,
                interruption_reason="client disconnect",
            )
            environ["maverick.entrypoint_shutdown_controller"] = request_shutdown_controller
            disconnect_task = asyncio.create_task(_wait_for_http_disconnect(receive))
            response_future = loop.run_in_executor(
                self.app_backend_executor,
                partial(_open_wsgi_http, self.http_host, environ, start_response),
            )
            done, _pending = await asyncio.wait(
                {response_future, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if disconnect_task in done and disconnect_task.result():
                request_shutdown_controller.begin_shutdown()
                await _consume_future(response_future)
                return
            response_iterable = await response_future
        else:
            response_iterable = await asyncio.to_thread(
                _open_wsgi_http,
                self.http_host,
                environ,
                start_response,
            )
        await send(
            {
                "type": "http.response.start",
                "status": status_holder.get("status", 500),
                "headers": status_holder.get("headers", []),
            }
        )
        disconnected = await _forward_wsgi_response_body(
            response_iterable,
            receive=receive,
            send=send,
            executor=self.app_backend_executor if use_app_backend_executor else None,
            disconnect_task=disconnect_task,
            request_shutdown_controller=request_shutdown_controller,
        )
        if not disconnected:
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _handle_sidecar_http(
        self,
        scope: dict[str, Any],
        receive: AsgiReceive,
        send: AsgiSend,
        sidecar_route: tuple[str, str, str],
    ) -> None:
        environ = _wsgi_environ(scope, b"")
        try:
            enforce_same_origin_for_unsafe_request(environ)
        except HttpRequestError as error:
            response_body = json_error_body(error.error)
            await send(
                {
                    "type": "http.response.start",
                    "status": int(error.status.split(" ", 1)[0]),
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(response_body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response_body, "more_body": False})
            return
        context = resolve_request_session(self.state, environ)
        workspace_id = context.workspace_id if context is not None else self.http_host.workspace_id
        user = context.user if context is not None else None
        app_id, sidecar_id, subpath = sidecar_route
        await handle_app_sidecar_proxy_asgi(
            self.state,
            scope=scope,
            receive=receive,
            send=send,
            workspace_id=workspace_id,
            app_id=app_id,
            sidecar_id=sidecar_id,
            subpath=subpath,
            user=user,
            start_path=self.state.repository_root,
            shutdown_controller=self.shutdown_controller,
        )


class LazyAsgiApplication:
    """Defer platform bootstrap until the ASGI server actually calls the app."""

    def __init__(self, factory: Callable[[], PlatformAsgiHost] | None = None) -> None:
        self._factory = factory or create_asgi_application
        self._app: PlatformAsgiHost | None = None

    async def __call__(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        if self._app is None:
            self._app = self._factory()
        await self._app(scope, receive, send)


async def _read_asgi_body(receive: AsgiReceive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > max_json_body_bytes():
            raise ValueError("ASGI request body exceeded maximum size.")
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _app_backend_worker_count() -> int:
    raw = os.environ.get("MAVERICK_APP_BACKEND_WORKERS", "")
    if not raw:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, min(value, 16))


def _is_app_backend_request(scope: dict[str, Any]) -> bool:
    path = str(scope.get("path") or "")
    method = str(scope.get("method") or "GET").upper()
    if method == "POST" and path.startswith("/api/apps/") and path.endswith("/backend"):
        return True
    return method in {"GET", "HEAD"} and _is_app_backend_media_request_path(path)


def _is_app_backend_media_request_path(path: str) -> bool:
    if not path.startswith("/api/apps/"):
        return False
    if path.endswith("/backend/media"):
        app_id = path.removeprefix("/api/apps/").removesuffix("/backend/media").strip("/")
        return bool(app_id and "/" not in app_id)
    if path.endswith("/media"):
        app_id = path.removeprefix("/api/apps/").removesuffix("/media").strip("/")
        return bool(app_id and "/" not in app_id)
    return False


def _wsgi_environ(scope: dict[str, Any], body: bytes) -> dict[str, Any]:
    headers = {
        key.decode("latin1").upper().replace("-", "_"): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    environ: dict[str, Any] = {
        "PATH_INFO": scope.get("path") or "/",
        "REQUEST_METHOD": scope.get("method") or "GET",
        "QUERY_STRING": scope.get("query_string", b"").decode("latin1"),
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": BytesIO(body),
        "wsgi.url_scheme": scope.get("scheme") or "http",
    }
    for name, value in headers.items():
        if name in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
            environ[name] = value
        else:
            environ[f"HTTP_{name}"] = value
    return environ


def _websocket_environ(scope: dict[str, Any]) -> dict[str, Any]:
    headers = {
        key.decode("latin1").upper().replace("-", "_"): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    environ: dict[str, Any] = {
        "PATH_INFO": scope.get("path") or "/",
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": scope.get("query_string", b"").decode("latin1"),
        "wsgi.input": BytesIO(b""),
        "wsgi.url_scheme": scope.get("scheme") or "http",
    }
    for name, value in headers.items():
        environ[f"HTTP_{name}"] = value
    return environ


async def _send_direct_json_response(send: AsgiSend, body: bytes, *, status: int = 200) -> None:
    """Send a small ASGI JSON response without entering the WSGI worker pool."""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _run_wsgi_http(http_host: PlatformHost, environ: dict[str, Any], start_response: Callable[[str, list[tuple[str, str]]], None]) -> bytes:
    """Run the synchronous platform HTTP host outside the ASGI event loop."""
    return b"".join(http_host(environ, start_response))


def _open_wsgi_http(
    http_host: PlatformHost,
    environ: dict[str, Any],
    start_response: Callable[[str, list[tuple[str, str]]], None],
) -> Iterator[bytes]:
    """Open the synchronous platform HTTP host and return its response iterator."""
    return iter(http_host(environ, start_response))


def _next_wsgi_chunk(iterator: Iterator[bytes]) -> bytes | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


def _close_wsgi_iterable(iterator: Iterable[bytes]) -> None:
    close = getattr(iterator, "close", None)
    if callable(close):
        close()


async def _forward_wsgi_response_body(
    response_iterable: Iterator[bytes],
    *,
    receive: AsgiReceive,
    send: AsgiSend,
    executor: ThreadPoolExecutor | None,
    disconnect_task: asyncio.Task[bool] | None = None,
    request_shutdown_controller: EntrypointShutdownController | None = None,
) -> bool:
    """Forward WSGI chunks while terminating app entrypoints on client disconnect."""
    loop = asyncio.get_running_loop()
    if request_shutdown_controller is not None and disconnect_task is None:
        disconnect_task = asyncio.create_task(_wait_for_http_disconnect(receive))
    disconnected = False
    try:
        while True:
            chunk_future = loop.run_in_executor(executor, partial(_next_wsgi_chunk, response_iterable))
            if disconnect_task is not None:
                done, _pending = await asyncio.wait(
                    {chunk_future, disconnect_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_task in done:
                    if disconnect_task.result():
                        disconnected = True
                        if request_shutdown_controller is not None:
                            request_shutdown_controller.begin_shutdown()
                        await _consume_future(chunk_future)
                        break
                    disconnect_task = None
            chunk = await chunk_future
            if chunk is None:
                break
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
    finally:
        if disconnect_task is not None and not disconnect_task.done():
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task
        await loop.run_in_executor(executor, partial(_close_wsgi_iterable, response_iterable))
    return disconnected


async def _wait_for_http_disconnect(receive: AsgiReceive) -> bool:
    """Wait until the ASGI server reports that the HTTP client disconnected."""
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return True


async def _consume_future(future: asyncio.Future[Any]) -> None:
    """Observe a worker future after cancellation without leaking its exception."""
    with suppress(asyncio.CancelledError, Exception):
        await future


def json_error_body(error: str) -> bytes:
    return json.dumps({"error": error}, indent=2).encode("utf-8")


def create_asgi_application() -> PlatformAsgiHost:
    """Create the ASGI application used by production hosts."""
    return PlatformAsgiHost()


app = LazyAsgiApplication()
