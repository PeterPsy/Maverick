"""Inter-agent graph WebSocket transport."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
import json
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

from core.api.http import json_default
from core.api.session_api import resolve_request_session
from core.inter_agent.authorization import (
    authorize_inter_agent_run_view,
    authorized_inter_agent_event_visibility,
)
from core.inter_agent.errors import InterAgentEventNotFoundError, InterAgentRunNotFoundError
from core.inter_agent.events import InterAgentEventPage, InterAgentEventRecord, validate_visibility_plane
from core.inter_agent.service import InterAgentService
from core.inter_agent.surfaces import artifact_items_payload, inter_agent_payload, run_detail_payload
from core.runtime.errors import RuntimeSessionNotFoundError
from core.shared.entrypoints import EntrypointShutdownController

AsgiReceive = Callable[[], Awaitable[dict[str, Any]]]
AsgiSend = Callable[[dict[str, Any]], Awaitable[None]]

INTER_AGENT_RUN_WS_PREFIX = "/ws/inter-agent/runs/"
WEBSOCKET_UNAUTHORIZED = 4401
WEBSOCKET_NOT_FOUND = 4404
WEBSOCKET_POLICY_VIOLATION = 4408
DEFAULT_INITIAL_EVENT_LIMIT = 240
MAX_HISTORY_EVENT_LIMIT = 500
DEFAULT_POLL_INTERVAL_SECONDS = 0.5


def inter_agent_websocket_manifest() -> dict[str, object]:
    """Return the public inter-agent graph WebSocket surface."""
    return {
        "path": "/ws/inter-agent/runs/{run_id}",
        "transport": "websocket",
        "primary_for": ["inter_agent_graph", "inter_agent_event_replay"],
        "client_query": {
            "visibility_plane": "summary, detail, or debug; capped server-side by caller authority and run policy",
            "last_event_id": "optional last persisted inter-agent event id for replay after reconnect",
            "initial_event_limit": "optional bounded tail event count for the initial snapshot",
        },
        "client_frames": {
            "inter_agent.history.before": "request an older bounded event page before before_event_id",
            "inter_agent.ack": "acknowledge the last event id the client has rendered",
        },
        "frames": {
            "inter_agent.snapshot": "run detail, approval, artifact, and persisted event replay",
            "inter_agent.history.page": "older persisted inter-agent event page requested by the client",
            "inter_agent.event": "one persisted inter-agent event",
            "inter_agent.heartbeat": "transport keepalive frame",
        },
    }


def inter_agent_run_id_from_path(path: str) -> str | None:
    """Extract a run id from the canonical inter-agent WebSocket path."""
    if not path.startswith(INTER_AGENT_RUN_WS_PREFIX):
        return None
    run_id = path.removeprefix(INTER_AGENT_RUN_WS_PREFIX).strip("/")
    return run_id or None


def websocket_environ(scope: dict[str, Any]) -> dict[str, str]:
    """Build the WSGI-like environment used by session resolution."""
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


def inter_agent_event_frame(event: InterAgentEventRecord) -> dict[str, Any]:
    """Wrap one persisted inter-agent event in a transport frame."""
    return {"type": "inter_agent.event", "event": asdict(event)}


def inter_agent_snapshot_frame(
    state: "PlatformState",
    run,
    *,
    events: list[InterAgentEventRecord],
    visibility_plane: str,
    last_event_id: str | None,
    has_more_before: bool,
    oldest_event_id: str | None,
) -> dict[str, Any]:
    """Wrap the initial inter-agent graph state in one transport frame."""
    approvals = state.inter_agent_store.list_approvals(run.run_id, workspace_id=run.workspace_id)
    return {
        "type": "inter_agent.snapshot",
        "run_detail": run_detail_payload(state.inter_agent_store, run),
        "approvals": inter_agent_payload(approvals),
        "artifacts": artifact_items_payload(events),
        "events": [asdict(event) for event in events],
        "visibility_plane": visibility_plane,
        "last_event_id": last_event_id,
        "has_more_before": has_more_before,
        "oldest_event_id": oldest_event_id,
    }


def inter_agent_history_page_frame(page: InterAgentEventPage) -> dict[str, Any]:
    """Wrap one older inter-agent history page in a transport frame."""
    return {
        "type": "inter_agent.history.page",
        "events": [asdict(event) for event in page.events],
        "visibility_plane": page.visibility_plane,
        "before_event_id": page.before_event_id,
        "oldest_event_id": page.oldest_event_id,
        "newest_event_id": page.newest_event_id,
        "has_more_before": page.has_more_before,
        "artifacts": artifact_items_payload(page.events),
    }


def initial_inter_agent_event_page(
    state: "PlatformState",
    run,
    *,
    visibility_plane: str,
    last_event_id: str | None,
    limit: int,
) -> InterAgentEventPage:
    """Return a bounded initial event replay page for a graph connection."""
    if last_event_id:
        try:
            page = state.inter_agent_store.list_event_page(
                run.run_id,
                workspace_id=run.workspace_id,
                visibility_plane=validate_visibility_plane(visibility_plane),
                after_event_id=last_event_id,
                limit=limit,
            )
            if page.events:
                return page
        except InterAgentEventNotFoundError:
            pass
    return state.inter_agent_store.list_event_page(
        run.run_id,
        workspace_id=run.workspace_id,
        visibility_plane=validate_visibility_plane(visibility_plane),
        limit=limit,
    )


async def stream_inter_agent_run_events(
    *,
    state: "PlatformState",
    scope: dict[str, Any],
    receive: AsgiReceive,
    send: AsgiSend,
    heartbeat_interval_seconds: float = 25.0,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    shutdown_controller: EntrypointShutdownController | None = None,
) -> None:
    """Handle the canonical inter-agent graph WebSocket stream."""
    run_id = inter_agent_run_id_from_path(str(scope.get("path") or ""))
    if run_id is None:
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    context = resolve_request_session(state, websocket_environ(scope))
    if context is None:
        await send({"type": "websocket.close", "code": WEBSOCKET_UNAUTHORIZED})
        return
    try:
        run = state.inter_agent_store.get_run(run_id, workspace_id=context.workspace_id)
    except (InterAgentRunNotFoundError, ValueError):
        await send({"type": "websocket.close", "code": WEBSOCKET_NOT_FOUND})
        return
    try:
        authorize_inter_agent_run_view(context_workspace_id=context.workspace_id, run_workspace_id=run.workspace_id)
        query = websocket_query(scope)
        visibility = authorized_inter_agent_event_visibility(
            workspace_store=state.workspace_store,
            context_workspace_id=context.workspace_id,
            caller_kind="http",
            run=run,
            requested_visibility_plane=validate_visibility_plane(query.get("visibility_plane") or "summary"),
            user_id=context.user.user_id,
            platform_role=context.user.platform_role,
            root_session=_root_session_for_run(state, run),
        )
    except Exception:
        await send({"type": "websocket.close", "code": WEBSOCKET_POLICY_VIOLATION})
        return

    query = websocket_query(scope)
    initial_event_limit = _bounded_positive_int(
        query.get("initial_event_limit"),
        default=DEFAULT_INITIAL_EVENT_LIMIT,
        maximum=MAX_HISTORY_EVENT_LIMIT,
    )
    last_event_id = query.get("last_event_id") or None
    seen_event_ids: set[str] = set()
    last_heartbeat_at = datetime.now(tz=UTC)
    try:
        await send({"type": "websocket.accept", "subprotocol": None, "headers": []})
        InterAgentService(state.inter_agent_store).expire_pending_approvals(run)
        initial_page = initial_inter_agent_event_page(
            state,
            run,
            visibility_plane=visibility,
            last_event_id=last_event_id,
            limit=initial_event_limit,
        )
        replay_events = initial_page.events
        for event in replay_events:
            last_event_id = event.event_id
            seen_event_ids.add(event.event_id)
        await _send_json(
            send,
            inter_agent_snapshot_frame(
                state,
                run,
                events=replay_events,
                visibility_plane=visibility,
                last_event_id=last_event_id,
                has_more_before=initial_page.has_more_before,
                oldest_event_id=initial_page.oldest_event_id,
            ),
        )

        while True:
            receive_task = asyncio.create_task(receive())
            shutdown_task = _shutdown_task(shutdown_controller)
            timeout = min(
                _seconds_until_heartbeat(last_heartbeat_at, heartbeat_interval_seconds),
                max(0.1, float(poll_interval_seconds)),
            )
            wait_tasks = {receive_task}
            if shutdown_task is not None:
                wait_tasks.add(shutdown_task)
            done, pending = await asyncio.wait(wait_tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            await _cancel_pending(pending)

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
                        if ack_event_id and ack_event_id in seen_event_ids:
                            last_event_id = ack_event_id
                        if client_frame.get("type") == "inter_agent.history.before":
                            before_event_id = client_frame.get("before_event_id")
                            page_limit = _bounded_positive_int(
                                str(client_frame.get("limit") or "") or None,
                                default=DEFAULT_INITIAL_EVENT_LIMIT,
                                maximum=MAX_HISTORY_EVENT_LIMIT,
                            )
                            if isinstance(before_event_id, str) and before_event_id:
                                with suppress(InterAgentEventNotFoundError):
                                    page = state.inter_agent_store.list_event_page(
                                        run.run_id,
                                        workspace_id=run.workspace_id,
                                        visibility_plane=visibility,
                                        before_event_id=before_event_id,
                                        limit=page_limit,
                                    )
                                    await _send_json(send, inter_agent_history_page_frame(page))

            for event in _events_after_cursor(
                state,
                run,
                visibility_plane=visibility,
                last_event_id=last_event_id,
                limit=MAX_HISTORY_EVENT_LIMIT,
            ):
                if event.event_id in seen_event_ids:
                    continue
                await _send_json(send, inter_agent_event_frame(event))
                last_event_id = event.event_id
                seen_event_ids.add(event.event_id)

            now = datetime.now(tz=UTC)
            if (now - last_heartbeat_at).total_seconds() >= heartbeat_interval_seconds:
                await _send_json(send, {"type": "inter_agent.heartbeat", "run_id": run.run_id, "at": now})
                last_heartbeat_at = now
    finally:
        return


def _events_after_cursor(
    state: "PlatformState",
    run,
    *,
    visibility_plane: str,
    last_event_id: str | None,
    limit: int,
) -> list[InterAgentEventRecord]:
    try:
        kwargs: dict[str, Any] = {
            "workspace_id": run.workspace_id,
            "visibility_plane": validate_visibility_plane(visibility_plane),
            "limit": limit,
        }
        if last_event_id:
            kwargs["after_event_id"] = last_event_id
        return state.inter_agent_store.list_event_page(
            run.run_id,
            **kwargs,
        ).events
    except InterAgentEventNotFoundError:
        return state.inter_agent_store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane=validate_visibility_plane(visibility_plane),
            limit=limit,
        ).events


def _root_session_for_run(state: "PlatformState", run):
    try:
        return state.runtime_store.get_session(run.root_runtime_session_id)
    except (RuntimeSessionNotFoundError, ValueError):
        return None


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
    if payload.get("type") not in {"inter_agent.ack", "inter_agent.replay"}:
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
