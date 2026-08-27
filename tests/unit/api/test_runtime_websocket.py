"""Unit tests for runtime WebSocket replay paging."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_websocket import (
    initial_runtime_event_page,
    lineage_runtime_event_page,
    stream_runtime_session_events,
    turn_anchored_runtime_event_page,
)
from core.runtime.event_bus import RuntimeEventBus
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeEventPage


BASE_TIME = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


class RuntimeWebSocketReplayPagingTestCase(unittest.TestCase):
    def test_initial_snapshot_extends_cut_tail_to_queued_turn_anchor(self) -> None:
        state = _state_with_events(
            [
                _event("event-0", 0, "runtime.turn.queued", turn_id="turn-1"),
                _event("event-1", 1, "runtime.turn.started", turn_id="turn-1"),
                _event("event-2", 2, "runtime.step.updated", turn_id="turn-1"),
                _event("event-3", 3, "runtime.output.delta", turn_id="turn-1"),
                _event("event-4", 4, "runtime.turn.completed", turn_id="turn-1"),
            ]
        )

        page = initial_runtime_event_page(state, "session-1", last_event_id=None, limit=2)

        self.assertEqual([event.event_id for event in page.events], ["event-0", "event-1", "event-2", "event-3", "event-4"])
        self.assertFalse(page.has_more_before)
        self.assertEqual(page.oldest_event_id, "event-0")

    def test_initial_snapshot_keeps_previous_turns_outside_anchor_backfill(self) -> None:
        state = _state_with_events(
            [
                _event("previous-0", 0, "runtime.turn.queued", turn_id="turn-0"),
                _event("previous-1", 1, "runtime.turn.completed", turn_id="turn-0"),
                _event("event-0", 2, "runtime.turn.queued", turn_id="turn-1"),
                _event("event-1", 3, "runtime.output.delta", turn_id="turn-1"),
                _event("event-2", 4, "runtime.output.delta", turn_id="turn-1"),
                _event("event-3", 5, "runtime.turn.completed", turn_id="turn-1"),
            ]
        )

        page = initial_runtime_event_page(state, "session-1", last_event_id=None, limit=2)

        self.assertEqual([event.event_id for event in page.events], ["event-0", "event-1", "event-2", "event-3"])
        self.assertTrue(page.has_more_before)
        self.assertEqual(page.oldest_event_id, "event-0")

    def test_history_page_extends_cut_page_to_started_turn_anchor(self) -> None:
        state = _state_with_events(
            [
                _event("event-0", 0, "runtime.turn.started", turn_id="turn-1"),
                _event("event-1", 1, "runtime.output.delta", turn_id="turn-1"),
                _event("event-2", 2, "runtime.output.delta", turn_id="turn-1"),
                _event("event-3", 3, "runtime.turn.completed", turn_id="turn-1"),
                _event("next-0", 4, "runtime.turn.queued", turn_id="turn-2"),
            ]
        )

        page = turn_anchored_runtime_event_page(state, "session-1", before_event_id="next-0", limit=2)

        self.assertEqual([event.event_id for event in page.events], ["event-0", "event-1", "event-2", "event-3"])
        self.assertFalse(page.has_more_before)
        self.assertEqual(page.before_event_id, "next-0")

    def test_initial_snapshot_replay_after_cursor_keeps_only_unseen_events(self) -> None:
        state = _state_with_events(
            [
                _event("event-0", 0, "runtime.turn.started", turn_id="turn-1"),
                _event("event-1", 1, "runtime.output.delta", turn_id="turn-1"),
                _event("event-2", 2, "runtime.turn.completed", turn_id="turn-1"),
            ]
        )

        page = initial_runtime_event_page(state, "session-1", last_event_id="event-0", limit=2)

        self.assertEqual([event.event_id for event in page.events], ["event-1", "event-2"])
        self.assertEqual(page.oldest_event_id, "event-1")

    def test_lineage_initial_page_reads_only_the_bounded_recent_tail(self) -> None:
        predecessor = type(
            "Session",
            (),
            {
                "session_id": "session-1",
                "predecessor_session_id": None,
                "continuation_successor_session_id": "session-2",
                "workspace_id": "default",
            },
        )()
        successor = type(
            "Session",
            (),
            {
                "session_id": "session-2",
                "predecessor_session_id": "session-1",
                "continuation_successor_session_id": None,
                "workspace_id": "default",
            },
        )()
        state = _state_with_events(
            [
                _event("old-0", 0, "runtime.turn.queued", turn_id="old-turn"),
                _event("old-1", 1, "runtime.turn.completed", turn_id="old-turn"),
                _event(
                    "new-0",
                    2,
                    "runtime.turn.queued",
                    turn_id="new-turn",
                    session_id="session-2",
                ),
                _event(
                    "new-1",
                    3,
                    "runtime.turn.completed",
                    turn_id="new-turn",
                    session_id="session-2",
                ),
            ],
            sessions=[predecessor, successor],
        )

        page = lineage_runtime_event_page(
            state,
            successor,
            before_event_id=None,
            limit=2,
        )

        self.assertEqual([event.event_id for event in page.events], ["new-0", "new-1"])
        self.assertTrue(page.has_more_before)
        self.assertEqual(state.runtime_store.page_calls, [("session-2", None, 2)])


class RuntimeWebSocketSchedulingTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_does_not_cancel_the_pending_client_receive(self) -> None:
        session = _runtime_session()
        state = SimpleNamespace(
            provider_registry=object(),
            provider_store=object(),
            runtime_event_bus=RuntimeEventBus(),
            runtime_store=_RuntimeStore([], [session]),
            usage_store=None,
        )
        context = SimpleNamespace(
            workspace_id="default",
            user=SimpleNamespace(user_id="user-a"),
        )
        receive_queue: asyncio.Queue[dict] = asyncio.Queue()
        await receive_queue.put({"type": "websocket.connect"})
        heartbeat_sent = asyncio.Event()
        receive_cancellations = 0

        async def receive() -> dict:
            nonlocal receive_cancellations
            try:
                return await receive_queue.get()
            except asyncio.CancelledError:
                receive_cancellations += 1
                raise

        async def send(message: dict) -> None:
            if "runtime.heartbeat" in str(message.get("text") or ""):
                heartbeat_sent.set()

        with (
            patch("core.api.runtime_websocket.resolve_request_session", return_value=context),
            patch("core.api.runtime_websocket.resolve_latest_runtime_session", return_value=session),
            patch("core.api.runtime_websocket.runtime_session_lineage", return_value=[session]),
            patch("core.api.runtime_websocket.runtime_session_admission_payload", return_value={}),
        ):
            stream_task = asyncio.create_task(
                stream_runtime_session_events(
                    state=state,
                    scope={
                        "type": "websocket",
                        "path": f"/ws/runtime/sessions/{session.session_id}",
                        "headers": [],
                        "query_string": b"",
                    },
                    receive=receive,
                    send=send,
                    heartbeat_interval_seconds=0.01,
                )
            )
            await asyncio.wait_for(heartbeat_sent.wait(), timeout=1)
            cancellations_before_disconnect = receive_cancellations
            await receive_queue.put({"type": "websocket.disconnect"})
            await asyncio.wait_for(stream_task, timeout=1)

        self.assertEqual(cancellations_before_disconnect, 0)


class _RuntimeStore:
    def __init__(self, events: list[RuntimeEventRecord], sessions: list[object] | None = None) -> None:
        self.events = sorted(events, key=lambda event: (event.created_at, event.event_id))
        self.sessions = {
            session.session_id: session for session in (sessions or [])
        }
        self.page_calls: list[tuple[str, str | None, int]] = []

    def get_session(self, session_id: str):
        return self.sessions[session_id]

    def list_event_page(self, session_id: str, *, before_event_id: str | None = None, limit: int = 200) -> RuntimeEventPage:
        self.page_calls.append((session_id, before_event_id, limit))
        events = [event for event in self.events if event.session_id == session_id]
        if before_event_id:
            cursor_index = next((index for index, event in enumerate(events) if event.event_id == before_event_id), None)
            events = events[:cursor_index] if cursor_index is not None else []
        has_more_before = len(events) > limit
        events = events[-limit:]
        return RuntimeEventPage(
            events=events,
            has_more_before=has_more_before,
            before_event_id=before_event_id,
            oldest_event_id=events[0].event_id if events else None,
            newest_event_id=events[-1].event_id if events else None,
        )


def _state_with_events(
    events: list[RuntimeEventRecord],
    *,
    sessions: list[object] | None = None,
):
    return type("State", (), {"runtime_store": _RuntimeStore(events, sessions)})()


def _runtime_session() -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        session_id="session-1",
        workspace_id="default",
        agent_id="chat",
        status="running",
        requested_mode=None,
        effective_mode="sandbox",
        workspace_root="/workspace",
        workdir="/workspace",
        runtime_root="/workspace/runtime/session-1",
        started_at=BASE_TIME,
        updated_at=BASE_TIME,
        ended_at=None,
        last_progress_at=BASE_TIME,
    )


def _event(
    event_id: str,
    offset_ms: int,
    event_type: str,
    *,
    turn_id: str | None,
    session_id: str = "session-1",
) -> RuntimeEventRecord:
    return RuntimeEventRecord(
        event_id=event_id,
        workspace_id="default",
        session_id=session_id,
        plane="turn",
        event_type=event_type,
        turn_id=turn_id,
        process_id=None,
        payload={},
        created_at=BASE_TIME + timedelta(milliseconds=offset_ms),
    )
