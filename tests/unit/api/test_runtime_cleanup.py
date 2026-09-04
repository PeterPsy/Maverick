from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.api.runtime_cleanup import RuntimeCleanupError, cleanup_runtime_session
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.paths import runtime_session_root
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.session_root_cleanup import runtime_session_deletion_quarantine_root
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeCleanupTest(unittest.TestCase):
    def test_cleanup_rejects_unsafe_session_id_before_deleting_records(self) -> None:
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        repo_root = make_temp_repo_root(self)
        now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
        runtime_store.save_session(
            RuntimeSessionRecord(
                session_id="../escape",
                workspace_id="default",
                agent_id="chat",
                status="running",
                requested_mode=None,
                effective_mode="sandbox",
                workspace_root=str(repo_root / "workspaces" / "default"),
                workdir=str(repo_root / "workspaces" / "default"),
                runtime_root="/tmp/evil",
                started_at=now,
                updated_at=now,
                ended_at=None,
                last_progress_at=now,
            )
        )
        state = SimpleNamespace(runtime_store=runtime_store, repository_root=repo_root)

        with self.assertRaisesRegex(RuntimeCleanupError, "runtime_session_id_unsafe"):
            cleanup_runtime_session(state, session_id="../escape", reason="test", start_path=repo_root)

        self.assertEqual(runtime_store.get_session("../escape").status, "running")

    def test_cleanup_allows_hidden_prepared_chat_only_with_explicit_flag(self) -> None:
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        repo_root = make_temp_repo_root(self)
        now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
        session_id = "prepared-hidden"
        runtime_store.save_session(
            RuntimeSessionRecord(
                session_id=session_id,
                workspace_id="default",
                agent_id="chat",
                status="running",
                requested_mode=None,
                effective_mode="sandbox",
                workspace_root=str(repo_root / "workspaces" / "default"),
                workdir=str(repo_root / "workspaces" / "default"),
                runtime_root=str(runtime_session_root(workspace_id="default", session_id=session_id, start_path=repo_root)),
                started_at=now,
                updated_at=now,
                ended_at=None,
                last_progress_at=now,
                session_kind="chat_root",
                thread_visibility="hidden",
                owner_user_id="user:admin",
            )
        )
        runtime_store.save_state(
            RuntimeStateRecord(
                session_id=session_id,
                workspace_id="default",
                current_turn_id=None,
                session_status="running",
                turn_status=None,
                last_progress_at=now,
                watchdog_deadline_at=None,
                forced_stop_reason=None,
                last_error_detail=None,
                updated_at=now,
            )
        )
        root = runtime_session_root(workspace_id="default", session_id=session_id, start_path=repo_root)
        root.mkdir(parents=True, exist_ok=True)
        (root / "marker.txt").write_text("prepared", encoding="utf-8")
        state = SimpleNamespace(
            runtime_store=runtime_store,
            repository_root=repo_root,
            inter_agent_store=SimpleNamespace(list_runs=lambda _workspace_id: []),
            app_store=SimpleNamespace(list_workspace_app_bindings=lambda _workspace_id: []),
            runtime_event_bus=None,
            observability_store=None,
        )

        with self.assertRaisesRegex(RuntimeCleanupError, "runtime_session_hidden"):
            cleanup_runtime_session(state, session_id=session_id, reason="test", start_path=repo_root)

        result = cleanup_runtime_session(
            state,
            session_id=session_id,
            reason="test",
            start_path=repo_root,
            allow_hidden_prepared_chat_cleanup=True,
        )

        self.assertTrue(result["found"])
        self.assertTrue(result["runtime_root_deleted"])
        self.assertTrue(result["runtime_root_purge_pending"])
        self.assertFalse(root.exists())
        quarantined_roots = list(
            runtime_session_deletion_quarantine_root("default", start_path=repo_root).iterdir()
        )
        self.assertEqual(len(quarantined_roots), 1)
        self.assertEqual((quarantined_roots[0] / "marker.txt").read_text(encoding="utf-8"), "prepared")
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session(session_id)


if __name__ == "__main__":
    unittest.main()
