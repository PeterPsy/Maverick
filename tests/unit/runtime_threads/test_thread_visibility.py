from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import tempfile
import unittest

from core.api.runtime_thread_websocket import runtime_thread_snapshot_frame
from core.runtime.errors import RuntimeSessionHiddenError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.service import create_child_runtime_session
from core.runtime.runtime_threads import (
    create_runtime_thread,
    ensure_runtime_threads_for_sessions,
    list_runtime_threads,
)
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class RuntimeThreadVisibilityTest(unittest.TestCase):
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

    def session(
        self,
        session_id: str,
        *,
        session_kind: str = "chat_root",
        thread_visibility: str = "user",
    ) -> RuntimeSessionRecord:
        now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode=None,
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root=f"/workspace/runtime/sessions/{session_id}",
            started_at=now,
            updated_at=now,
            ended_at=None,
            last_progress_at=now,
            session_kind=session_kind,  # type: ignore[arg-type]
            thread_visibility=thread_visibility,  # type: ignore[arg-type]
        )

    def test_legacy_session_document_defaults_to_chat_root_user_thread(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
        store.collections.sessions.update_one(
            {"session_id": "legacy"},
            {
                "$set": {
                    "workspace_id": "default",
                    "agent_id": "chat",
                    "status": "running",
                    "requested_mode": None,
                    "effective_mode": "sandbox",
                    "workspace_root": "/workspace",
                    "workdir": "/workspace",
                    "runtime_root": "/workspace/runtime/sessions/legacy",
                    "started_at": now,
                    "updated_at": now,
                    "ended_at": None,
                    "last_progress_at": now,
                }
            },
            upsert=True,
        )

        session = store.get_session("legacy")

        self.assertEqual(session.session_kind, "chat_root")
        self.assertEqual(session.thread_visibility, "user")

    def test_thread_reconciliation_skips_hidden_sessions(self) -> None:
        store = self.make_store()
        visible = self.session("visible")
        hidden = self.session(
            "hidden",
            session_kind="inter_agent_participant",
            thread_visibility="hidden",
        )
        store.save_session(visible)
        store.save_session(hidden)

        threads = ensure_runtime_threads_for_sessions(
            store,
            workspace_id="default",
            sessions=[visible, hidden],
        )

        self.assertEqual([thread.runtime_session_id for thread in threads], ["visible"])
        self.assertEqual(store.get_thread("visible").runtime_session_id, "visible")
        with self.assertRaises(RuntimeSessionHiddenError):
            create_runtime_thread(
                store,
                workspace_id="default",
                runtime_session_id="hidden",
                title="Hidden participant",
            )

    def test_child_runtime_session_helper_marks_hidden_participant_session(self) -> None:
        store = self.make_store()
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = replace(
                self.session("parent"),
                runtime_root=f"{temp_dir}/runtime/sessions/parent",
            )
            store.save_session(parent)

            child = create_child_runtime_session(
                store,
                parent_session_id="parent",
                child_session_id="child",
                child_agent_id="child-agent",
            )

        self.assertEqual(child.session_kind, "inter_agent_participant")
        self.assertEqual(child.thread_visibility, "hidden")

    def test_stale_hidden_threads_are_filtered_from_lists_and_websocket_snapshots(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
        store.save_session(self.session("visible"))
        store.save_session(
            self.session(
                "hidden",
                session_kind="inter_agent_participant",
                thread_visibility="hidden",
            )
        )
        store.save_thread(
            RuntimeThreadRecord(
                thread_id="stale-hidden",
                workspace_id="default",
                runtime_session_id="hidden",
                title="Hidden participant",
                agent_label="child",
                agent_type_id="",
                agent_role_id="",
                source_app_id="chat",
                system_prompt="",
                project_id=None,
                archived=False,
                availability="free",
                created_at=now,
                updated_at=now,
            )
        )

        threads = ensure_runtime_threads_for_sessions(
            store,
            workspace_id="default",
            sessions=store.list_sessions("default"),
        )
        frame = runtime_thread_snapshot_frame(SimpleNamespace(runtime_store=store), workspace_id="default")

        self.assertEqual([thread.runtime_session_id for thread in threads], ["visible"])
        self.assertEqual([thread.runtime_session_id for thread in list_runtime_threads(store, workspace_id="default")], ["visible"])
        self.assertEqual([thread["runtime_session_id"] for thread in frame["threads"]], ["visible"])


if __name__ == "__main__":
    unittest.main()
