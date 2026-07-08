"""Runtime thread WebSocket transport for workspace chat catalogs."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from core.api.http import json_default
from core.api.session_api import resolve_request_session
from core.observability.startup_performance import startup_performance_enabled, startup_timer
from core.runtime.plain_hosted_text import queue_provider_id_for_session
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_threads import ensure_runtime_threads_for_sessions, thread_payload, thread_recency_key
from core.shared.entrypoints import EntrypointShutdownController

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]

RUNTIME_THREADS_WS_PATH = "/ws/runtime/threads"
WEBSOCKET_UNAUTHORIZED = 4401
WEBSOCKET_NOT_FOUND = 4404
RUNTIME_THREAD_SNAPSHOT_LIMIT = 50


def runtime_thread_websocket_manifest() -> dict[str, object]:
    """Return the public runtime thread WebSocket surface for app authors."""
    return {
        "path": RUNTIME_THREADS_WS_PATH,
        "transport": "websocket",
        "primary_for": ["runtime_thread_catalog", "chat_thread_updates"],
        "frames": {
            "runtime.thread.snapshot": "current workspace runtime thread catalog",
            "runtime.thread.changed": "one core-owned thread catalog mutation",
            "runtime.thread.heartbeat": "transport keepalive frame",
        },
    }


def encode_thread_websocket_frame(frame: dict[str, Any]) -> str:
    """Serialize one WebSocket JSON frame."""
    return json.dumps(frame, default=json_default, separators=(",", ":"))


async def _send_json(send: AsgiSend, frame: dict[str, Any]) -> None:
    await send({"type": "websocket.send", "text": encode_thread_websocket_frame(frame)})


def _websocket_environ(scope: dict[str, Any]) -> dict[str, str]:
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


def runtime_thread_snapshot_frame(state: PlatformState, *, workspace_id: str, viewer_user_id: str | None = None) -> dict[str, Any]:
    """Build the current workspace runtime thread catalog snapshot."""
    with startup_timer("runtime.threads.websocket_snapshot", workspace_id=workspace_id) as timing:
        sessions = state.runtime_store.list_sessions(workspace_id)
        sessions_by_id = {session.session_id: session for session in sessions}
        threads = _ordered_runtime_threads(state, workspace_id=workspace_id, sessions=sessions)
        page_threads = threads[:RUNTIME_THREAD_SNAPSHOT_LIMIT]
        items = [
            _thread_payload_with_runtime(
                state,
                thread,
                session=sessions_by_id.get(thread.runtime_session_id),
                viewer_user_id=viewer_user_id,
            )
            for thread in page_threads
        ]
        frame = {
            "type": "runtime.thread.snapshot",
            "workspace_id": workspace_id,
            "threads": items,
            "threads_page": {
                "items": items,
                "limit": RUNTIME_THREAD_SNAPSHOT_LIMIT,
                "has_more": len(threads) > RUNTIME_THREAD_SNAPSHOT_LIMIT,
                "cursor": page_threads[-1].thread_id if len(threads) > RUNTIME_THREAD_SNAPSHOT_LIMIT and page_threads else None,
                "sort": "recency_desc",
                "query": None,
            },
            "at": datetime.now(tz=UTC),
        }
        timing["session_count"] = len(sessions)
        timing["thread_count"] = len(items)
        timing["total_thread_count"] = len(threads)
        if startup_performance_enabled():
            timing["encoded_bytes"] = len(encode_thread_websocket_frame(frame).encode("utf-8"))
        return frame


def runtime_thread_changed_frame(
    state: PlatformState,
    *,
    workspace_id: str,
    viewer_user_id: str | None,
    event: dict[str, Any],
) -> dict[str, Any]:
    """Build one user-specific thread catalog mutation frame."""
    frame: dict[str, Any] = {
        "type": "runtime.thread.changed",
        "workspace_id": workspace_id,
        "action": str(event.get("action") or "updated"),
    }
    for key in ("deleted_thread_ids", "deleted_runtime_session_ids"):
        value = event.get(key)
        if isinstance(value, list):
            frame[key] = value
    thread_id = _event_thread_id(event)
    if thread_id:
        with suppress(Exception):
            thread = state.runtime_store.get_thread(thread_id)
            if thread.workspace_id == workspace_id:
                frame["thread"] = _thread_payload_with_runtime(state, thread, viewer_user_id=viewer_user_id)
    return frame


def _thread_payload_with_runtime(state: PlatformState, thread, *, session=None, viewer_user_id: str | None = None) -> dict[str, Any]:
    payload = thread_payload(thread, viewer_user_id=viewer_user_id)
    runtime_session = session
    if runtime_session is None and getattr(thread, "runtime_session_id", ""):
        try:
            runtime_session = state.runtime_store.get_session(thread.runtime_session_id)
        except (RuntimeSessionNotFoundError, ValueError):
            runtime_session = None
    if runtime_session is None:
        return payload
    payload["runtime_mode"] = runtime_session.runtime_mode
    payload["provider_id"] = runtime_session.provider_id or queue_provider_id_for_session(runtime_session)
    payload["hosted_provider_id"] = runtime_session.hosted_provider_id
    payload["hosted_model_id"] = runtime_session.hosted_model_id
    return payload


def _ordered_runtime_threads(state: PlatformState, *, workspace_id: str, sessions=None):
    runtime_sessions = sessions if sessions is not None else state.runtime_store.list_sessions(workspace_id)
    threads = ensure_runtime_threads_for_sessions(
        state.runtime_store,
        workspace_id=workspace_id,
        sessions=runtime_sessions,
    )
    return sorted(threads, key=thread_recency_key, reverse=True)


def _event_thread_id(event: dict[str, Any]) -> str:
    direct_thread_id = event.get("thread_id")
    if isinstance(direct_thread_id, str):
        return direct_thread_id
    thread = event.get("thread")
    if isinstance(thread, dict):
        thread_id = thread.get("thread_id")
        if isinstance(thread_id, str):
            return thread_id
    return ""

async def stream_runtime_thread_events(
    *,
    state: PlatformState,
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    heartbeat_interval_seconds: float = 25.0,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> None:
    """Handle the workspace runtime thread catalog WebSocket stream."""
    if str(scope.get("path") or "") != RUNTIME_THREADS_WS_PATH:
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    context = resolve_request_session(state, _websocket_environ(scope))
    if context is None:
        await send({"type": "websocket.close", "code": WEBSOCKET_UNAUTHORIZED})
        return
    workspace_id = context.workspace_id
    subscription = state.runtime_thread_event_bus.subscribe(workspace_id)
    last_heartbeat_at = datetime.now(tz=UTC)
    try:
        await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
        await _send_json(send, runtime_thread_snapshot_frame(state, workspace_id=workspace_id, viewer_user_id=context.user.user_id))
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
                    await _send_json(send, {"type": "runtime.thread.heartbeat", "workspace_id": workspace_id, "at": now})
                    last_heartbeat_at = now
                continue
            if shutdown_task is not None and shutdown_task in done:
                return
            if receive_task in done:
                incoming = receive_task.result()
                if incoming and incoming.get("type") == "websocket.disconnect":
                    return
            if event_task in done:
                event = event_task.result()
                await _send_json(
                    send,
                    runtime_thread_changed_frame(
                        state,
                        workspace_id=workspace_id,
                        viewer_user_id=context.user.user_id,
                        event=event,
                    ),
                )
            now = datetime.now(tz=UTC)
            if (now - last_heartbeat_at).total_seconds() >= heartbeat_interval_seconds:
                await _send_json(send, {"type": "runtime.thread.heartbeat", "workspace_id": workspace_id, "at": now})
                last_heartbeat_at = now
    finally:
        state.runtime_thread_event_bus.unsubscribe(subscription)


def _seconds_until_heartbeat(last_heartbeat_at: datetime, heartbeat_interval_seconds: float) -> float:
    elapsed = (datetime.now(tz=UTC) - last_heartbeat_at).total_seconds()
    return max(0.0, heartbeat_interval_seconds - elapsed)


async def _cancel_pending(tasks: set[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


def _shutdown_task(shutdown_controller: EntrypointShutdownController | None) -> asyncio.Task | None:
    if shutdown_controller is None:
        return None
    return asyncio.create_task(_wait_for_shutdown(shutdown_controller))


async def _wait_for_shutdown(shutdown_controller: EntrypointShutdownController) -> None:
    while not shutdown_controller.is_shutting_down():
        await asyncio.sleep(0.1)
