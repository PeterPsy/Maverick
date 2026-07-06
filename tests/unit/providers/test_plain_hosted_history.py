from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from core.runtime.plain_hosted_history import build_plain_hosted_message_history
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord


class StubRuntimeStore:
    def __init__(
        self,
        turns: list[RuntimeTurnRecord],
        events: list[RuntimeEventRecord],
        *,
        event_pages: list[list[RuntimeEventRecord]] | None = None,
    ) -> None:
        self.turns = turns
        self.events = events
        self.event_pages = list(event_pages or [])
        self.recent_turn_limits: list[int] = []
        self.recent_event_limits: list[int] = []
        self.event_page_requests: list[tuple[str | None, int]] = []

    def list_turns(self, session_id: str) -> list[RuntimeTurnRecord]:
        raise AssertionError("plain hosted history must use bounded turn reads")

    def list_recent_turns(self, session_id: str, *, limit: int) -> list[RuntimeTurnRecord]:
        self.recent_turn_limits.append(limit)
        return [turn for turn in self.turns if turn.session_id == session_id]

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        raise AssertionError("plain hosted history must use bounded event reads")

    def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
        self.recent_event_limits.append(limit)
        return [event for event in self.events if event.session_id == session_id]

    def list_event_page(self, session_id: str, *, before_event_id: str | None = None, limit: int = 200):
        self.event_page_requests.append((before_event_id, limit))
        events = self.event_pages.pop(0) if self.event_pages else []
        return SimpleNamespace(
            events=[event for event in events if event.session_id == session_id],
            has_more_before=bool(self.event_pages),
            oldest_event_id=events[0].event_id if events else None,
        )


class PlainHostedHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def turn(self, turn_id: str, minutes: int, *, status: str = "completed", input_text: str = "question") -> RuntimeTurnRecord:
        created_at = self.now + timedelta(minutes=minutes)
        return RuntimeTurnRecord(
            turn_id=turn_id,
            session_id="session-1",
            workspace_id="default",
            status=status,
            input_text=input_text,
            created_at=created_at,
            updated_at=created_at,
            started_at=created_at,
            completed_at=created_at if status == "completed" else None,
            failure_reason=None,
            runtime_mode="plain_hosted_chat",
        )

    def final_event(self, turn_id: str, minutes: int, event_id: str, text: str) -> RuntimeEventRecord:
        return RuntimeEventRecord(
            event_id=event_id,
            workspace_id="default",
            session_id="session-1",
            plane="turn",
            event_type="runtime.output.final",
            turn_id=turn_id,
            process_id=None,
            payload={"text": "stream suffix", "complete_text": text},
            created_at=self.now + timedelta(minutes=minutes),
        )

    def delta_event(self, turn_id: str, minutes: int, event_id: str, text: str) -> RuntimeEventRecord:
        return RuntimeEventRecord(
            event_id=event_id,
            workspace_id="default",
            session_id="session-1",
            plane="turn",
            event_type="runtime.output.delta",
            turn_id=turn_id,
            process_id=None,
            payload={"text": text},
            created_at=self.now + timedelta(minutes=minutes),
        )

    def test_completed_turns_produce_user_assistant_current_user_messages(self) -> None:
        store = StubRuntimeStore(
            turns=[
                self.turn("turn-2", 2, input_text="second"),
                self.turn("turn-current", 3, status="active", input_text="current"),
                self.turn("turn-1", 1, input_text="first"),
            ],
            events=[
                self.final_event("turn-2", 2, "event-2", "answer two"),
                self.final_event("turn-1", 1, "event-1", "answer one"),
            ],
        )

        messages = build_plain_hosted_message_history(
            store,
            session_id="session-1",
            current_turn_id="turn-current",
            current_input_text="current",
        )

        self.assertEqual([message.role for message in messages], ["user", "assistant", "user", "assistant", "user"])
        self.assertEqual([message.content for message in messages], ["first", "answer one", "second", "answer two", "current"])
        self.assertEqual(store.recent_turn_limits, [80])
        self.assertEqual(store.recent_event_limits, [1000])

    def test_latest_final_event_wins_per_turn(self) -> None:
        store = StubRuntimeStore(
            turns=[self.turn("turn-1", 1, input_text="first")],
            events=[
                self.final_event("turn-1", 3, "event-b", "newer answer"),
                self.final_event("turn-1", 2, "event-a", "older answer"),
            ],
        )

        messages = build_plain_hosted_message_history(
            store,
            session_id="session-1",
            current_turn_id="turn-current",
            current_input_text="current",
        )

        self.assertEqual(messages[1].content, "newer answer")

    def test_pages_older_events_when_recent_tail_loses_final_output(self) -> None:
        store = StubRuntimeStore(
            turns=[self.turn("turn-1", 1, input_text="first")],
            events=[self.delta_event("turn-noisy", 3, "tail-1", "noise")],
            event_pages=[[self.final_event("turn-1", 1, "event-1", "answer one")]],
        )

        messages = build_plain_hosted_message_history(
            store,
            session_id="session-1",
            current_turn_id="turn-current",
            current_input_text="current",
            max_history_turns=1,
        )

        self.assertEqual([message.content for message in messages], ["first", "answer one", "current"])
        self.assertEqual(store.recent_event_limits, [50])
        self.assertEqual(store.event_page_requests, [("tail-1", 50)])

    def test_excludes_non_completed_current_and_incomplete_turns(self) -> None:
        store = StubRuntimeStore(
            turns=[
                self.turn("failed", 1, status="failed", input_text="failed"),
                self.turn("cancelled", 2, status="cancelled", input_text="cancelled"),
                self.turn("active", 3, status="active", input_text="active"),
                self.turn("missing-output", 4, status="completed", input_text="missing"),
                self.turn("turn-current", 5, status="completed", input_text="current duplicate"),
            ],
            events=[self.final_event("failed", 1, "event-failed", "failed answer")],
        )

        messages = build_plain_hosted_message_history(
            store,
            session_id="session-1",
            current_turn_id="turn-current",
            current_input_text="current",
        )

        self.assertEqual([message.role for message in messages], ["user"])
        self.assertEqual(messages[0].content, "current")

    def test_trimming_keeps_complete_pairs_and_current_message(self) -> None:
        store = StubRuntimeStore(
            turns=[
                self.turn("turn-1", 1, input_text="old question"),
                self.turn("turn-2", 2, input_text="new question"),
            ],
            events=[
                self.final_event("turn-1", 1, "event-1", "old answer"),
                self.final_event("turn-2", 2, "event-2", "new answer"),
            ],
        )

        messages = build_plain_hosted_message_history(
            store,
            session_id="session-1",
            current_turn_id="turn-current",
            current_input_text="current",
            max_history_chars=len("new question") + len("new answer") + len("current"),
        )

        self.assertEqual([message.content for message in messages], ["new question", "new answer", "current"])

    def test_zero_character_budget_keeps_current_message(self) -> None:
        store = StubRuntimeStore(
            turns=[self.turn("turn-1", 1, input_text="first")],
            events=[self.final_event("turn-1", 1, "event-1", "answer one")],
        )

        messages = build_plain_hosted_message_history(
            store,
            session_id="session-1",
            current_turn_id="turn-current",
            current_input_text="current",
            max_history_chars=0,
        )

        self.assertEqual([message.content for message in messages], ["current"])


if __name__ == "__main__":
    unittest.main()
