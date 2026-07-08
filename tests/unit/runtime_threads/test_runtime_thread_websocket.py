"""Unit coverage for runtime thread WebSocket catalog snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from core.api.runtime_thread_websocket import runtime_thread_snapshot_frame
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class RuntimeThreadWebSocketFrameTest(unittest.TestCase):
    def make_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def test_snapshot_reconciles_stale_thread_availability(self) -> None:
        store = self.make_store()
        state = SimpleNamespace(runtime_store=store)
        started_at = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        completed_at = started_at + timedelta(seconds=2)
        store.save_session(
            RuntimeSessionRecord(
                session_id="session-1",
                workspace_id="default",
                agent_id="test-agent",
                status="running",
                requested_mode=None,
                effective_mode="sandbox",
                workspace_root="/workspace",
                workdir="/workspace",
                runtime_root="/workspace/.maverick/runtime/session-1",
                started_at=started_at,
                updated_at=started_at,
                ended_at=None,
                last_progress_at=started_at,
            )
        )
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-completed",
                session_id="session-1",
                workspace_id="default",
                status="completed",
                input_text="done",
                created_at=started_at,
                updated_at=completed_at,
                started_at=started_at + timedelta(milliseconds=100),
                completed_at=completed_at,
                failure_reason=None,
            )
        )
        store.save_thread(
            RuntimeThreadRecord(
                thread_id="thread-stale",
                workspace_id="default",
                runtime_session_id="session-1",
                title="Stale thread",
                agent_label="test-agent",
                agent_type_id="",
                agent_role_id="",
                source_app_id="test-agent",
                system_prompt="",
                project_id=None,
                archived=False,
                availability="active",
                created_at=started_at,
                updated_at=started_at,
            )
        )

        frame = runtime_thread_snapshot_frame(state, workspace_id="default", viewer_user_id=None)

        self.assertEqual(frame["threads"][0]["availability"], "free")
        self.assertEqual(frame["threads"][0]["last_completed_turn_id"], "turn-completed")
        self.assertEqual(store.get_thread("thread-stale").availability, "free")

    def test_snapshot_covers_current_thread_catalog_under_cap(self) -> None:
        store = self.make_store()
        state = SimpleNamespace(runtime_store=store)
        started_at = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        for index in range(55):
            updated_at = started_at + timedelta(minutes=index)
            store.save_session(
                RuntimeSessionRecord(
                    session_id=f"session-{index:02d}",
                    workspace_id="default",
                    agent_id="test-agent",
                    status="running",
                    requested_mode=None,
                    effective_mode="sandbox",
                    workspace_root="/workspace",
                    workdir="/workspace",
                    runtime_root=f"/workspace/.maverick/runtime/session-{index:02d}",
                    started_at=started_at,
                    updated_at=updated_at,
                    ended_at=None,
                    last_progress_at=updated_at,
                )
            )

        frame = runtime_thread_snapshot_frame(state, workspace_id="default", viewer_user_id=None)

        self.assertEqual(len(frame["threads"]), 55)
        self.assertEqual(frame["threads_page"]["items"], frame["threads"])
        self.assertEqual(frame["threads_page"]["limit"], 250)
        self.assertFalse(frame["threads_page"]["has_more"])
        self.assertIsNone(frame["threads_page"]["cursor"])
        self.assertEqual(frame["threads_page"]["sort"], "recency_desc")


if __name__ == "__main__":
    unittest.main()
