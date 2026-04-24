"""Runtime WebSocket transport for interactive clients."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
import json
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

from core.api.http import json_default
from core.api.platform_state import PlatformState
from core.api.session_api import resolve_request_session
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_events import RuntimeEventRecord
from core.shared.entrypoints import EntrypointShutdownController


AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]

RUNTIME_SESSION_WS_PREFIX = "/ws/runtime/sessions/"
WEBSOCKET_UNAUTHORIZED = 4401
WEBSOCKET_NOT_FOUND = 4404
WEBSOCKET_POLICY_VIOLATION = 4408


def runtime_websocket_manifest() -> dict[str, object]:
    """Return the public runtime WebSocket surface for app authors."""
    return {
        "path": "/ws/runtime/sessions/{session_id}",
        "transport": "websocket",
        "primary_for": ["runtime_events", "agent_turn_updates"],
        "fallback_http": "/api/runtime/sessions/{session_id}/events",
        "client_query": {
            "last_event_id": "optional last persisted runtime event id for replay after reconnect",
        },
        "frames": {
            "runtime.event": "persisted runtime event record",
            "runtime.replay_complete": "transport control frame emitted after catch-up replay",
            "runtime.heartbeat": "transport keepalive frame, never persisted as a runtime event",
        },
    }


def runtime_session_id_from_path(path: str) -> str | None:
    """Extract a runtime session id from the canonical WebSocket path."""
    if not path.startswith(RUNTIME_SESSION_WS_PREFIX):
        return None
    session_id = path.removeprefix(RUNTIME_SESSION_WS_PREFIX).strip("/")
    return session_id or None


def websocket_environ(scope: dict[str, Any]) -> dict[str, str]:
    """Build the small WSGI-like environment needed by session resolution."""
    headers = {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }
    return {
        "HTTP_COOKIE": headers.get("cookie", ""),
        "PATH_INFO": str(scope.get("path") or ""),
        "REQUEST_METHOD": "GET",
        "QUERY_STRING": scope.get("query_string", b"").decode("latin1"),
    }


def websocket_query(scope: dict[str, Any]) -> dict[str, str]:
    """Return single-value query parameters from one ASGI scope."""
    raw_query = scope.get("query_string", b"").decode("latin1")
    return {key: values[-1] for key, values in parse_qs(raw_query).items()}


def encode_websocket_frame(frame: dict[str, Any]) -> str:
    """Serialize one WebSocket JSON frame."""
    return json.dumps(frame, default=json_default, separators=(",", ":"))


def runtime_event_frame(event: RuntimeEventRecord) -> dict[str, Any]:
    """Wrap one persisted runtime event in a transport frame."""
    return {"type": "runtime.event", "event": asdict(event)}


def ordered_events_after(events: list[RuntimeEventRecord], last_event_id: str | None) -> list[RuntimeEventRecord]:
    """Return events after the last client-seen event id."""
    ordered = sorted(events, key=lambda event: (event.created_at, event.event_id))
    if not last_event_id:
        return ordered
    for index, event in enumerate(ordered):
        if event.event_id == last_event_id:
            return ordered[index + 1 :]
    return ordered


async def _send_json(send: AsgiSend, frame: dict[str, Any]) -> None:
    await send({"type": "websocket.send", "text": encode_websocket_frame(frame)})


def _seconds_until_heartbeat(last_heartbeat_at: datetime, heartbeat_interval_seconds: float) -> float:
    elapsed = (datetime.now(tz=UTC) - last_heartbeat_at).total_seconds()
    return max(0.0, heartbeat_interval_seconds - elapsed)


async def _cancel_pending(tasks: set[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


async def stream_runtime_session_events(
    *,
    state: PlatformState,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    heartbeat_interval_seconds: float = 25.0,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> None:
    """Handle the canonical runtime WebSocket stream."""
    session_id = runtime_session_id_from_path(str(scope.get("path") or ""))
    if session_id is None:
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    context = resolve_request_session(state, websocket_environ(scope))
    if context is None:
        await send({"type": "websocket.close", "code": WEBSOCKET_UNAUTHORIZED})
        return
    try:
        session = state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    if session.workspace_id != context.workspace_id:
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return

    query = websocket_query(scope)
    last_event_id = query.get("last_event_id") or None
    subscription = state.runtime_event_bus.subscribe(session_id)
    seen_event_ids: set[str] = set()
    last_heartbeat_at = datetime.now(tz=UTC)
    try:
        await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
        replay_events = ordered_events_after(state.runtime_store.list_events(session_id), last_event_id)
        for event in replay_events:
            await _send_json(send, runtime_event_frame(event))
            last_event_id = event.event_id
            seen_event_ids.add(event.event_id)
        if replay_events:
            await _send_json(
                send,
                {
                    "type": "runtime.replay_complete",
                    "session_id": session_id,
                    "last_event_id": last_event_id,
                },
            )

        while True:
            receive_task = asyncio.create_task(receive())
            event_task = asyncio.create_task(subscription.get())
            shutdown_task = _shutdown_task(shutdown_controller)
            timeout = _seconds_until_heartbeat(last_heartbeat_at, heartbeat_interval_seconds)
            wait_tasks = {receive_task, event_task}
            if shutdown_task is not None:
                wait_tasks.add(shutdown_task)
            done, pending = await asyncio.wait(wait_tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            await _cancel_pending(pending)

            if not done:
                now = datetime.now(tz=UTC)
                if (now - last_heartbeat_at).total_seconds() >= heartbeat_interval_seconds:
                    await _send_json(send, {"type": "runtime.heartbeat", "session_id": session_id, "at": now})
                    last_heartbeat_at = now
                continue

            if shutdown_task is not None and shutdown_task in done:
                return

            if receive_task in done:
                incoming = receive_task.result()
                if incoming and incoming.get("type") == "websocket.disconnect":
                    return
                if incoming and incoming.get("type") == "websocket.receive":
                    last_event_id = _handle_client_frame(incoming, fallback_last_event_id=last_event_id)

            if event_task in done:
                event = event_task.result()
                if event.event_id in seen_event_ids:
                    continue
                await _send_json(send, runtime_event_frame(event))
                last_event_id = event.event_id
                seen_event_ids.add(event.event_id)

            now = datetime.now(tz=UTC)
            if (now - last_heartbeat_at).total_seconds() >= heartbeat_interval_seconds:
                await _send_json(send, {"type": "runtime.heartbeat", "session_id": session_id, "at": now})
                last_heartbeat_at = now
    finally:
        state.runtime_event_bus.unsubscribe(subscription)


def _handle_client_frame(frame: dict[str, Any], *, fallback_last_event_id: str | None) -> str | None:
    """Handle optional client ack/replay control frames."""
    text = frame.get("text")
    if not isinstance(text, str) or not text.strip():
        return fallback_last_event_id
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return fallback_last_event_id
    if not isinstance(payload, dict):
        return fallback_last_event_id
    if payload.get("type") in {"runtime.ack", "runtime.replay"}:
        event_id = payload.get("last_event_id")
        return event_id if isinstance(event_id, str) and event_id else fallback_last_event_id
    return fallback_last_event_id


def _shutdown_task(shutdown_controller: EntrypointShutdownController | None) -> asyncio.Task | None:
    if shutdown_controller is None:
        return None
    return asyncio.create_task(_wait_for_shutdown(shutdown_controller))


async def _wait_for_shutdown(shutdown_controller: EntrypointShutdownController) -> None:
    while not shutdown_controller.is_shutting_down():
        await asyncio.sleep(0.1)
