"""ASGI host for Maverick v3 HTTP and WebSocket surfaces."""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, Awaitable, Callable

from core.api.app_events import APP_EVENTS_WS_PATH, stream_app_events
from core.api.platform_host import PlatformHost
from core.api.platform_state import PlatformState, bootstrap_platform_state
from core.api.runtime_websocket import RUNTIME_SESSION_WS_PREFIX, stream_runtime_session_events
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
        if path == APP_EVENTS_WS_PATH:
            await stream_app_events(
                bus=self.state.app_event_bus,
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
                await send({"type": "lifespan.shutdown.complete"})
                return
            raise RuntimeError(f"Unsupported ASGI lifespan event: {message_type}")

    async def _handle_http(self, scope: dict[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        body = await _read_asgi_body(receive)
        status_holder: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            status_holder["status"] = int(status.split(" ", 1)[0])
            status_holder["headers"] = [(name.encode("latin1"), value.encode("latin1")) for name, value in headers]

        response_body = await asyncio.to_thread(
            _run_wsgi_http,
            self.http_host,
            _wsgi_environ(scope, body),
            start_response,
        )
        await send(
            {
                "type": "http.response.start",
                "status": status_holder.get("status", 500),
                "headers": status_holder.get("headers", []),
            }
        )
        await send({"type": "http.response.body", "body": response_body, "more_body": False})


async def _read_asgi_body(receive: AsgiReceive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


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


def _run_wsgi_http(http_host: PlatformHost, environ: dict[str, Any], start_response: Callable[[str, list[tuple[str, str]]], None]) -> bytes:
    """Run the synchronous platform HTTP host outside the ASGI event loop."""
    return b"".join(http_host(environ, start_response))


def create_asgi_application() -> PlatformAsgiHost:
    """Create the ASGI application used by production hosts."""
    return PlatformAsgiHost()


app = create_asgi_application()
