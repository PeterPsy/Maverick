from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import tempfile
import unittest

from core.api.runtime_thread_websocket import runtime_thread_snapshot_frame
from core.runtime.errors import RuntimeSessionHiddenError
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord, runtime_session_allows_user_thread
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.service import create_child_runtime_session, create_runtime_session
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

    def test_inter_agent_participant_defaults_to_hidden_when_visibility_is_omitted(self) -> None:
        store = self.make_store()
        session = create_runtime_session(
            store,
            session_id="participant",
            workspace_id="default",
            agent_id="child-agent",
            session_kind="inter_agent_participant",
        )

        self.assertEqual(session.session_kind, "inter_agent_participant")
        self.assertEqual(session.thread_visibility, "hidden")
        self.assertFalse(runtime_session_allows_user_thread(session))

    def test_inter_agent_participant_rejects_user_thread_visibility(self) -> None:
        store = self.make_store()

        with self.assertRaises(ValueError):
            create_runtime_session(
                store,
                session_id="participant",
                workspace_id="default",
                agent_id="child-agent",
                session_kind="inter_agent_participant",
                thread_visibility="user",
            )

    def test_participant_document_without_visibility_hydrates_as_hidden(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
        store.collections.sessions.update_one(
            {"session_id": "participant"},
            {
                "$set": {
                    "workspace_id": "default",
                    "agent_id": "child-agent",
                    "status": "running",
                    "requested_mode": None,
                    "effective_mode": "sandbox",
                    "workspace_root": "/workspace",
                    "workdir": "/workspace",
                    "runtime_root": "/workspace/runtime/sessions/participant",
                    "started_at": now,
                    "updated_at": now,
                    "ended_at": None,
                    "last_progress_at": now,
                    "session_kind": "inter_agent_participant",
                }
            },
            upsert=True,
        )

        session = store.get_session("participant")

        self.assertEqual(session.thread_visibility, "hidden")
        self.assertFalse(runtime_session_allows_user_thread(session))

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
                system_prompt="parent prompt",
                skill_ids=["parent-skill"],
                skill_catalog_app_id="skills",
                source_app_id="chat",
                owner_user_id="parent-owner",
                created_by_user_id="parent-creator",
                grants=[
                    RuntimeSessionGrantRecord(
                        operation="interrupt",
                        grantee_kind="user",
                        grantee_id="parent-owner",
                    )
                ],
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
        self.assertIsNone(child.system_prompt)
        self.assertEqual(child.skill_ids, [])
        self.assertIsNone(child.skill_catalog_app_id)
        self.assertIsNone(child.source_app_id)
        self.assertIsNone(child.owner_user_id)
        self.assertIsNone(child.created_by_user_id)
        self.assertEqual(child.grants, [])

    def test_child_runtime_session_accepts_explicit_materialized_authority(self) -> None:
        store = self.make_store()
        grant = RuntimeSessionGrantRecord(
            operation="interrupt",
            grantee_kind="runtime_session",
            grantee_id="parent",
        )
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
                system_prompt=" materialized prompt ",
                skill_ids=["", " child-skill "],
                skill_catalog_app_id=" skills ",
                source_app_id=" chat ",
                owner_user_id=" user-child ",
                created_by_user_id=" user-creator ",
                grants=[grant],
            )

        self.assertEqual(child.system_prompt, "materialized prompt")
        self.assertEqual(child.skill_ids, ["child-skill"])
        self.assertEqual(child.skill_catalog_app_id, "skills")
        self.assertEqual(child.source_app_id, "chat")
        self.assertEqual(child.owner_user_id, "user-child")
        self.assertEqual(child.created_by_user_id, "user-creator")
        self.assertEqual(child.grants, [grant])

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

    def test_invalid_thread_visibility_fails_closed_for_thread_catalog(self) -> None:
        store = self.make_store()
        now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
        store.collections.sessions.update_one(
            {"session_id": "corrupt"},
            {
                "$set": {
                    "workspace_id": "default",
                    "agent_id": "chat",
                    "status": "running",
                    "requested_mode": None,
                    "effective_mode": "sandbox",
                    "workspace_root": "/workspace",
                    "workdir": "/workspace",
                    "runtime_root": "/workspace/runtime/sessions/corrupt",
                    "started_at": now,
                    "updated_at": now,
                    "ended_at": None,
                    "last_progress_at": now,
                    "session_kind": "chat_root",
                    "thread_visibility": "not-hidden",
                }
            },
            upsert=True,
        )
        store.save_thread(
            RuntimeThreadRecord(
                thread_id="stale-corrupt",
                workspace_id="default",
                runtime_session_id="corrupt",
                title="Corrupt visibility",
                agent_label="chat",
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

        with self.assertRaises(ValueError):
            store.get_session("corrupt")

        invalid_session = self.session("invalid", thread_visibility="not-hidden")

        self.assertEqual(store.list_sessions("default"), [])
        self.assertFalse(runtime_session_allows_user_thread(invalid_session))
        self.assertEqual(list_runtime_threads(store, workspace_id="default"), [])


if __name__ == "__main__":
    unittest.main()
