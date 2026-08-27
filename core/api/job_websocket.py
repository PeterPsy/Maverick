"""Authenticated workspace WebSocket for durable job replay and live events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import Any
from urllib.parse import parse_qs

from core.api.websocket_tasks import cancel_websocket_tasks
from core.jobs.events import JobEventBus
from core.jobs.serialization import record_to_payload
from core.jobs.service import JobService
from core.shared.entrypoints import EntrypointShutdownController


JOB_EVENTS_WS_PATH = "/api/jobs/events/ws"
DEFAULT_REPLAY_LIMIT = 100
MAX_REPLAY_LIMIT = 200


def job_websocket_manifest() -> dict[str, object]:
    """Describe the public durable-job event transport."""
    return {
        "path": JOB_EVENTS_WS_PATH,
        "transport": "websocket",
        "primary_for": ["durable_job_event_replay", "durable_job_live_updates"],
        "query": {
            "last_event_id": "optional persisted event cursor",
            "replay_limit": f"bounded replay size, at most {MAX_REPLAY_LIMIT}",
        },
        "frames": {
            "compute.job.snapshot": "bounded persisted workspace event replay",
            "compute.job.event": "one newly persisted workspace job event",
            "compute.job.heartbeat": "transport keepalive frame",
        },
    }


def initial_job_event_replay(
    service: JobService,
    *,
    workspace_id: str,
    last_event_id: str | None,
    limit: int,
) -> tuple[list, bool, bool]:
    """Return a bounded replay tail plus cursor and truncation metadata."""
    events = service.list_workspace_events(workspace_id=workspace_id)
    cursor_found = not last_event_id
    selected = events
    if last_event_id:
        for index, event in enumerate(events):
            if event.event_id == last_event_id:
                cursor_found = True
                selected = events[index + 1 :]
                break
    truncated = len(selected) > limit
    return selected[-limit:], cursor_found, truncated


async def stream_job_events(
    *,
    service: JobService,
    bus: JobEventBus,
    scope: dict,
    receive,
    send,
    workspace_id: str,
    heartbeat_interval_seconds: float = 25.0,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> None:
    """Replay persisted events, then stream workspace-filtered live events."""
    if str(scope.get("path") or "") != JOB_EVENTS_WS_PATH:
        await send({"type": "websocket.close", "code": 4404})
        return
    query = _websocket_query(scope)
    replay_limit = _bounded_positive_int(query.get("replay_limit"), default=DEFAULT_REPLAY_LIMIT)
    requested_cursor = query.get("last_event_id") or None
    subscription = bus.subscribe(workspace_id)
    seen_event_ids: set[str] = set()
    last_heartbeat_at = datetime.now(tz=UTC)
    receive_task: asyncio.Task | None = None
    event_task: asyncio.Task | None = None
    shutdown_task: asyncio.Task | None = None
    try:
        replay, cursor_found, replay_truncated = initial_job_event_replay(
            service,
            workspace_id=workspace_id,
            last_event_id=requested_cursor,
            limit=replay_limit,
        )
        seen_event_ids.update(event.event_id for event in replay)
        await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
        await _send_json(
            send,
            {
                "type": "compute.job.snapshot",
                "workspace_id": workspace_id,
                "events": [record_to_payload(event) for event in replay],
                "last_event_id": replay[-1].event_id if replay else requested_cursor,
                "cursor_found": cursor_found,
                "replay_truncated": replay_truncated,
            },
        )
        shutdown_task = _shutdown_task(shutdown_controller)
        while True:
            if receive_task is None:
                receive_task = asyncio.create_task(receive())
            if event_task is None:
                event_task = asyncio.create_task(subscription.get())
            tasks = {event_task, receive_task}
            if shutdown_task is not None:
                tasks.add(shutdown_task)
            done, _ = await asyncio.wait(
                tasks,
                timeout=_seconds_until_heartbeat(last_heartbeat_at, heartbeat_interval_seconds),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                now = datetime.now(tz=UTC)
                await _send_json(
                    send,
                    {"type": "compute.job.heartbeat", "workspace_id": workspace_id, "at": now.isoformat()},
                )
                last_heartbeat_at = now
                continue
            if shutdown_task is not None and shutdown_task in done:
                return
            if receive_task in done:
                incoming = receive_task.result()
                receive_task = None
                if incoming.get("type") == "websocket.disconnect":
                    return
            if event_task in done:
                event = event_task.result()
                event_task = None
                if event.event_id not in seen_event_ids:
                    seen_event_ids.add(event.event_id)
                    await _send_json(
                        send,
                        {"type": "compute.job.event", "event": record_to_payload(event)},
                    )
            now = datetime.now(tz=UTC)
            if (now - last_heartbeat_at).total_seconds() >= heartbeat_interval_seconds:
                await _send_json(
                    send,
                    {"type": "compute.job.heartbeat", "workspace_id": workspace_id, "at": now.isoformat()},
                )
                last_heartbeat_at = now
    finally:
        await cancel_websocket_tasks(receive_task, event_task, shutdown_task)
        bus.unsubscribe(subscription)


def _websocket_query(scope: dict[str, Any]) -> dict[str, str]:
    raw = scope.get("query_string", b"")
    query_string = raw.decode("latin1") if isinstance(raw, bytes) else str(raw or "")
    return {key: values[-1] for key, values in parse_qs(query_string, keep_blank_values=True).items() if values}


def _bounded_positive_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return min(MAX_REPLAY_LIMIT, parsed) if parsed > 0 else default


async def _send_json(send, frame: dict[str, Any]) -> None:
    await send({"type": "websocket.send", "text": json.dumps(frame, ensure_ascii=True, separators=(",", ":"))})


def _seconds_until_heartbeat(last_heartbeat_at: datetime, heartbeat_interval_seconds: float) -> float:
    elapsed = (datetime.now(tz=UTC) - last_heartbeat_at).total_seconds()
    return max(0.0, heartbeat_interval_seconds - elapsed)


def _shutdown_task(controller: EntrypointShutdownController | None) -> asyncio.Task | None:
    if controller is None:
        return None
    return asyncio.create_task(_wait_for_shutdown(controller))


async def _wait_for_shutdown(controller: EntrypointShutdownController) -> None:
    while not controller.is_shutting_down():
        await asyncio.sleep(0.1)
