"""Unit tests for runtime WebSocket replay paging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.api.runtime_websocket import (
    initial_runtime_event_page,
    requested_runtime_history_frame,
    turn_anchored_runtime_event_page,
)
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeEventPage


BASE_TIME = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


class RuntimeWebSocketReplayPagingTestCase(unittest.TestCase):
    def test_reading_window_includes_anchor_once_and_handles_both_archive_edges(self) -> None:
        state = _state_with_events([_event(f"event-{i}", i, "runtime.output.delta", turn_id=None) for i in range(9)])
        for anchor, expected, before, after in [
            ("event-4", ["event-2", "event-3", "event-4", "event-5", "event-6"], True, True),
            ("event-0", ["event-0", "event-1", "event-2"], False, True),
            ("event-8", ["event-6", "event-7", "event-8"], True, False),
            ("missing", [], False, False),
        ]:
            frame = requested_runtime_history_frame(state, "session-1", {
                "type": "runtime.history.around", "around_event_id": anchor, "limit": 4, "request_id": "restore",
            })
            self.assertEqual([event["event_id"] for event in frame["events"]], expected)
            self.assertEqual((frame["has_more_before"], frame["has_more_after"]), (before, after))
            self.assertEqual(frame["request_id"], "restore")
        other = requested_runtime_history_frame(state, "other-session", {
            "type": "runtime.history.around", "around_event_id": "event-4", "limit": 4,
        })
        self.assertEqual(other["events"], [])

    def test_forward_page_and_latest_keep_cursor_direction_and_request_identity(self) -> None:
        state = _state_with_events([_event(f"event-{i}", i, "runtime.output.delta", turn_id=None) for i in range(8)])
        frame = requested_runtime_history_frame(state, "session-1", {
            "type": "runtime.history.after", "after_event_id": "event-2", "limit": 2, "request_id": "request-1",
        })
        self.assertEqual([event["event_id"] for event in frame["events"]], ["event-3", "event-4"])
        self.assertEqual(frame["direction"], "after")
        self.assertEqual(frame["after_event_id"], "event-2")
        self.assertEqual(frame["request_id"], "request-1")
        self.assertTrue(frame["has_more_after"])
        latest = requested_runtime_history_frame(state, "session-1", {"type": "runtime.history.latest", "limit": 2})
        self.assertEqual([event["event_id"] for event in latest["events"]], ["event-6", "event-7"])
        self.assertFalse(latest["has_more_after"])
        self.assertTrue(latest["has_more_before"])

    def test_history_requests_reject_invalid_cursor_and_correlation(self) -> None:
        state = _state_with_events([])
        for frame in [
            {"type": "runtime.history.after"},
            {"type": "runtime.history.before", "before_event_id": ["event"]},
            {"type": "runtime.history.latest", "request_id": "x" * 129},
            {"type": "runtime.history.latest", "request_id": {"session_id": "other"}},
            {"type": "unknown"},
        ]:
            self.assertIsNone(requested_runtime_history_frame(state, "session-1", frame))
        self.assertEqual(state.runtime_store.page_calls, [])

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


class _RuntimeStore:
    def __init__(self, events: list[RuntimeEventRecord], sessions: list[object] | None = None) -> None:
        self.events = sorted(events, key=lambda event: (event.created_at, event.event_id))
        self.sessions = {
            session.session_id: session for session in (sessions or [])
        }
        self.page_calls: list[tuple[str, str | None, int]] = []

    def get_session(self, session_id: str):
        return self.sessions[session_id]

    def find_event(self, session_id: str, event_id: str):
        return next((event for event in self.events if event.session_id == session_id and event.event_id == event_id), None)

    def list_event_page(self, session_id: str, *, before_event_id: str | None = None, after_event_id: str | None = None, limit: int = 200) -> RuntimeEventPage:
        self.page_calls.append((session_id, before_event_id, limit))
        events = [event for event in self.events if event.session_id == session_id]
        if before_event_id:
            cursor_index = next((index for index, event in enumerate(events) if event.event_id == before_event_id), None)
            events = events[:cursor_index] if cursor_index is not None else []
        if after_event_id:
            cursor_index = next((index for index, event in enumerate(events) if event.event_id == after_event_id), None)
            events = events[cursor_index + 1:] if cursor_index is not None else []
        has_more_before = bool(after_event_id) or len(events) > limit
        has_more_after = bool(after_event_id) and len(events) > limit
        events = events[:limit] if after_event_id else events[-limit:]
        return RuntimeEventPage(
            events=events,
            has_more_before=has_more_before,
            before_event_id=before_event_id,
            after_event_id=after_event_id,
            has_more_after=has_more_after,
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
