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
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeEventPage
from core.shared.entrypoints import EntrypointShutdownController
from core.usage.payloads import chat_usage_summary_payload
from core.usage.service import build_chat_usage_summary, resolve_root_session_id


AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]

RUNTIME_SESSION_WS_PREFIX = "/ws/runtime/sessions/"
WEBSOCKET_UNAUTHORIZED = 4401
WEBSOCKET_NOT_FOUND = 4404
WEBSOCKET_POLICY_VIOLATION = 4408
DEFAULT_INITIAL_EVENT_LIMIT = 500
MAX_HISTORY_EVENT_LIMIT = 500
MAX_REPLAY_PAYLOAD_TEXT_CHARS = 8000
MAX_TURN_ANCHOR_BACKFILL_EVENTS = 5000
TURN_ANCHOR_EVENT_TYPES = {"runtime.turn.queued", "runtime.turn.started"}


def runtime_websocket_manifest() -> dict[str, object]:
    """Return the public runtime WebSocket surface for app authors."""
    return {
        "path": "/ws/runtime/sessions/{session_id}",
        "transport": "websocket",
        "primary_for": ["runtime_events", "agent_turn_updates"],
        "client_query": {
            "last_event_id": "optional last persisted runtime event id for replay after reconnect",
            "initial_event_limit": "optional bounded tail event count; replay may include earlier same-turn anchor events",
        },
        "frames": {
            "runtime.snapshot": "runtime session metadata, authoritative token usage, and persisted event replay after the requested cursor",
            "runtime.history.page": "older persisted runtime event page requested by the client, anchored to avoid starting mid-turn when possible",
            "runtime.event": "persisted runtime event record",
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


def replay_runtime_event_payload(event: RuntimeEventRecord) -> dict[str, Any]:
    """Return the runtime event payload used in bounded replay frames."""
    payload = asdict(event)
    event_payload = dict(payload.get("payload") or {})
    if event.event_type == "runtime.step.updated":
        event_payload.pop("raw", None)
    elif event.event_type.startswith("runtime.tool_call."):
        for key in ("raw", "stdout", "stderr", "output"):
            value = event_payload.get(key)
            if isinstance(value, str) and len(value) > MAX_REPLAY_PAYLOAD_TEXT_CHARS:
                event_payload[key] = value[:MAX_REPLAY_PAYLOAD_TEXT_CHARS]
                event_payload[f"{key}_truncated"] = True
                event_payload[f"{key}_original_chars"] = len(value)
    payload["payload"] = event_payload
    return payload


def runtime_snapshot_frame(
    *,
    session,
    events: list[RuntimeEventRecord],
    turns: list[RuntimeTurnRecord] | None = None,
    last_event_id: str | None,
    has_more_before: bool = False,
    oldest_event_id: str | None = None,
    usage: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Wrap the initial runtime session state in a transport frame."""
    return {
        "type": "runtime.snapshot",
        "session": asdict(session),
        "events": [replay_runtime_event_payload(event) for event in events],
        "turns": [asdict(turn) for turn in turns or []],
        "last_event_id": last_event_id,
        "has_more_before": has_more_before,
        "oldest_event_id": oldest_event_id,
        "usage": usage,
    }


def runtime_history_page_frame(page: RuntimeEventPage, *, turns: list[RuntimeTurnRecord] | None = None) -> dict[str, Any]:
    """Wrap one older runtime history page in a transport frame."""
    return {
        "type": "runtime.history.page",
        "events": [replay_runtime_event_payload(event) for event in page.events],
        "turns": [asdict(turn) for turn in turns or []],
        "before_event_id": page.before_event_id,
        "oldest_event_id": page.oldest_event_id,
        "newest_event_id": page.newest_event_id,
        "has_more_before": page.has_more_before,
    }


def ordered_events_after(events: list[RuntimeEventRecord], last_event_id: str | None) -> list[RuntimeEventRecord]:
    """Return events after the last client-seen event id."""
    ordered = sorted(events, key=lambda event: (event.created_at, event.event_id))
    if not last_event_id:
        return ordered
    for index, event in enumerate(ordered):
        if event.event_id == last_event_id:
            return ordered[index + 1 :]
    return ordered


def turn_anchored_runtime_event_page(
    state: PlatformState,
    session_id: str,
    *,
    before_event_id: str | None,
    limit: int,
) -> RuntimeEventPage:
    """Return a bounded event page extended backward to the oldest turn anchor."""
    page = state.runtime_store.list_event_page(session_id, before_event_id=before_event_id, limit=limit)
    return _extend_page_to_turn_anchor(state, session_id, page)


def initial_runtime_event_page(state: PlatformState, session_id: str, *, last_event_id: str | None, limit: int) -> RuntimeEventPage:
    """Return the bounded initial replay page for a WebSocket connection."""
    page = turn_anchored_runtime_event_page(state, session_id, before_event_id=None, limit=limit)
    tail_events = page.events
    if last_event_id:
        events = ordered_events_after(tail_events, last_event_id)
        if not events:
            events = tail_events
        return RuntimeEventPage(
            events=events,
            has_more_before=page.has_more_before,
            before_event_id=None,
            oldest_event_id=events[0].event_id if events else None,
            newest_event_id=events[-1].event_id if events else None,
        )
    return page


def _extend_page_to_turn_anchor(state: PlatformState, session_id: str, page: RuntimeEventPage) -> RuntimeEventPage:
    if not page.events or not page.has_more_before:
        return page
    oldest_event = page.events[0]
    turn_id = oldest_event.turn_id
    if not turn_id or _contains_turn_anchor(page.events, turn_id):
        return page

    events = list(page.events)
    cursor_event_id = page.oldest_event_id
    backfilled_count = 0
    while cursor_event_id and backfilled_count < MAX_TURN_ANCHOR_BACKFILL_EVENTS:
        older_page = state.runtime_store.list_event_page(
            session_id,
            before_event_id=cursor_event_id,
            limit=MAX_HISTORY_EVENT_LIMIT,
        )
        if not older_page.events:
            return page

        anchor_index = _turn_anchor_index(older_page.events, turn_id)
        if anchor_index is not None:
            prefix = older_page.events[anchor_index:]
            events = _merge_runtime_event_lists(prefix, events)
            has_more_before = older_page.has_more_before or anchor_index > 0
            return RuntimeEventPage(
                events=events,
                has_more_before=has_more_before,
                before_event_id=page.before_event_id,
                oldest_event_id=events[0].event_id if events else None,
                newest_event_id=events[-1].event_id if events else None,
            )

        first_turn_index = _first_turn_event_index(older_page.events, turn_id)
        if first_turn_index is None:
            return page
        prefix = older_page.events[first_turn_index:]
        events = _merge_runtime_event_lists(prefix, events)
        backfilled_count += len(prefix)
        cursor_event_id = events[0].event_id if events else None
        if not older_page.has_more_before and first_turn_index == 0:
            break

    return RuntimeEventPage(
        events=events,
        has_more_before=True,
        before_event_id=page.before_event_id,
        oldest_event_id=events[0].event_id if events else None,
        newest_event_id=events[-1].event_id if events else None,
    )


def _contains_turn_anchor(events: list[RuntimeEventRecord], turn_id: str) -> bool:
    return any(event.turn_id == turn_id and event.event_type in TURN_ANCHOR_EVENT_TYPES for event in events)


def _turn_anchor_index(events: list[RuntimeEventRecord], turn_id: str) -> int | None:
    for index, event in enumerate(events):
        if event.turn_id == turn_id and event.event_type in TURN_ANCHOR_EVENT_TYPES:
            return index
    return None


def _first_turn_event_index(events: list[RuntimeEventRecord], turn_id: str) -> int | None:
    for index, event in enumerate(events):
        if event.turn_id == turn_id:
            return index
    return None


def _merge_runtime_event_lists(left: list[RuntimeEventRecord], right: list[RuntimeEventRecord]) -> list[RuntimeEventRecord]:
    merged: dict[str, RuntimeEventRecord] = {}
    for event in [*left, *right]:
        merged[event.event_id] = event
    return sorted(merged.values(), key=lambda event: (event.created_at, event.event_id))


def runtime_turns_for_events(state: PlatformState, session_id: str, events: list[RuntimeEventRecord]) -> list[RuntimeTurnRecord]:
    """Return turn records needed to rehydrate bounded event pages."""
    turn_ids = {event.turn_id for event in events if event.turn_id}
    if not turn_ids:
        return []
    return [turn for turn in state.runtime_store.list_turns(session_id) if turn.turn_id in turn_ids]


def _bounded_positive_int(value: str | None, *, default: int, maximum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


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
    except (RuntimeSessionNotFoundError, ValueError):
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    if session.workspace_id != context.workspace_id:
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    if not runtime_session_allows_user_thread(session):
        await send({"type": "websocket.close", "code": WEBSOCKET_POLICY_VIOLATION})
        return

    query = websocket_query(scope)
    last_event_id = query.get("last_event_id") or None
    initial_event_limit = _bounded_positive_int(
        query.get("initial_event_limit"),
        default=DEFAULT_INITIAL_EVENT_LIMIT,
        maximum=MAX_HISTORY_EVENT_LIMIT,
    )
    subscription = state.runtime_event_bus.subscribe(session_id)
    seen_event_ids: set[str] = set()
    last_heartbeat_at = datetime.now(tz=UTC)
    try:
        await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
        initial_page = initial_runtime_event_page(state, session_id, last_event_id=last_event_id, limit=initial_event_limit)
        replay_events = initial_page.events
        replay_turns = runtime_turns_for_events(state, session_id, replay_events)
        for event in replay_events:
            last_event_id = event.event_id
            seen_event_ids.add(event.event_id)
        await _send_json(
            send,
            runtime_snapshot_frame(
                session=session,
                events=replay_events,
                turns=replay_turns,
                last_event_id=last_event_id,
                has_more_before=initial_page.has_more_before,
                oldest_event_id=initial_page.oldest_event_id,
                usage=_runtime_usage_snapshot(state, session),
            ),
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
                    client_frame = _parse_client_frame(incoming)
                    if client_frame is not None:
                        ack_event_id = _ack_event_id(client_frame)
                        if ack_event_id:
                            last_event_id = ack_event_id
                        if client_frame.get("type") == "runtime.history.before":
                            before_event_id = client_frame.get("before_event_id")
                            page_limit = _bounded_positive_int(
                                str(client_frame.get("limit") or "") or None,
                                default=DEFAULT_INITIAL_EVENT_LIMIT,
                                maximum=MAX_HISTORY_EVENT_LIMIT,
                            )
                            if isinstance(before_event_id, str) and before_event_id:
                                page = turn_anchored_runtime_event_page(
                                    state,
                                    session_id,
                                    before_event_id=before_event_id,
                                    limit=page_limit,
                                )
                                await _send_json(
                                    send,
                                    runtime_history_page_frame(page, turns=runtime_turns_for_events(state, session_id, page.events)),
                                )

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


def _runtime_usage_snapshot(state: PlatformState, session) -> dict[str, object] | None:
    usage_store = getattr(state, "usage_store", None)
    if usage_store is None:
        return None
    root_session_id = resolve_root_session_id(state.runtime_store, session)
    summary = build_chat_usage_summary(
        usage_store,
        workspace_id=session.workspace_id,
        root_session_id=root_session_id,
    )
    return chat_usage_summary_payload(summary)


def _parse_client_frame(frame: dict[str, Any]) -> dict[str, Any] | None:
    """Parse optional client control frames."""
    text = frame.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _ack_event_id(payload: dict[str, Any]) -> str | None:
    if payload.get("type") not in {"runtime.ack", "runtime.replay"}:
        return None
    event_id = payload.get("last_event_id")
    return event_id if isinstance(event_id, str) and event_id else None


def _shutdown_task(shutdown_controller: EntrypointShutdownController | None) -> asyncio.Task | None:
    if shutdown_controller is None:
        return None
    return asyncio.create_task(_wait_for_shutdown(shutdown_controller))


async def _wait_for_shutdown(shutdown_controller: EntrypointShutdownController) -> None:
    while not shutdown_controller.is_shutting_down():
        await asyncio.sleep(0.1)
