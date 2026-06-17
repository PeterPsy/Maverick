"""Tests for backend restart runtime recovery behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from core.recovery.backend_restart import _close_orphan_non_terminal_turn_events, _is_inter_agent_root_turn
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.errors import RuntimeTurnNotFoundError
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord


NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


@dataclass
class _FakeRuntimeStore:
    events: list[RuntimeEventRecord]
    list_events_calls: int = 0
    saved_events: list[RuntimeEventRecord] | None = None

    def __post_init__(self) -> None:
        self.saved_events = []

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        self.list_events_calls += 1
        return [event for event in self.events if event.session_id == session_id]

    def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
        self.list_events_calls += 1
        return [event for event in self.events if event.session_id == session_id][-limit:]

    def get_turn(self, turn_id: str) -> None:
        raise RuntimeTurnNotFoundError(f"missing {turn_id}")

    def get_session(self, session_id: str) -> RuntimeSessionRecord:
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id="default",
            agent_id="runtime-agent",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root="/tmp/workspace",
            workdir="/tmp/workspace",
            runtime_root="/tmp/workspace/runtime/sessions/session-1",
            started_at=None,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=None,
            system_prompt="",
            skill_ids=[],
            source_app_id="source-app",
        )

    def save_event(self, record: RuntimeEventRecord) -> RuntimeEventRecord:
        assert self.saved_events is not None
        self.saved_events.append(record)
        return record


@dataclass
class _FakeState:
    runtime_store: _FakeRuntimeStore
    runtime_event_bus = None


class BackendRestartRecoveryTestCase(unittest.TestCase):
    def test_orphan_event_recovery_reads_session_events_once(self) -> None:
        store = _FakeRuntimeStore(
            events=[
                RuntimeEventRecord(
                    event_id="event-1",
                    workspace_id="default",
                    session_id="session-1",
                    plane="turn",
                    event_type="runtime.turn.queued",
                    turn_id="missing-turn",
                    process_id=None,
                    payload={},
                    created_at=NOW,
                )
            ]
        )

        closed = _close_orphan_non_terminal_turn_events(_FakeState(runtime_store=store), session_id="session-1")

        self.assertEqual(closed, 1)
        self.assertEqual(store.list_events_calls, 1)
        self.assertEqual(store.saved_events[0].event_type, "runtime.turn.cancelled")

    def test_backend_restart_detects_inter_agent_root_turns(self) -> None:
        turn = SimpleNamespace(turn_id="turn-ia-root")
        events = [
            RuntimeEventRecord(
                event_id="event-ia-root",
                workspace_id="default",
                session_id="session-1",
                plane="turn",
                event_type="runtime.turn.queued",
                turn_id="turn-ia-root",
                process_id=None,
                payload={"inter_agent_run_id": "run-1"},
                created_at=NOW,
            )
        ]

        self.assertTrue(_is_inter_agent_root_turn(turn, events))

    def test_runtime_event_recovery_query_skips_large_partition_without_removing_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "maverick"
            event_path = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "session-1" / "events.json"
            event_path.parent.mkdir(parents=True)
            event_path.write_text(json.dumps([{"event_id": f"event-{index}", "session_id": "session-1"} for index in range(20)]), encoding="utf-8")
            collection = RuntimeEventJsonCollection(start_path=repo_root)

            events = collection.find_recent({"session_id": "session-1"}, limit=5, max_scan_bytes=10)

            self.assertEqual(events, [])
            self.assertTrue(event_path.exists())
            self.assertEqual(len(list(event_path.parent.glob("events.json.quarantined-oversized-*"))), 0)

    def test_runtime_event_recovery_query_quarantines_corrupt_legacy_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "maverick"
            event_path = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "session-1" / "events.json"
            event_path.parent.mkdir(parents=True)
            event_path.write_text("[", encoding="utf-8")
            collection = RuntimeEventJsonCollection(start_path=repo_root)

            events = collection.find_recent({"session_id": "session-1"}, limit=5)

            self.assertEqual(events, [])
            self.assertFalse(event_path.exists())
            self.assertEqual(len(list(event_path.parent.glob("events.json.quarantined-malformed-*"))), 1)


if __name__ == "__main__":
    unittest.main()
