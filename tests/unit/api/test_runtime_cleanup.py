from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.api.runtime_cleanup import RuntimeCleanupError, cleanup_runtime_session
from core.runtime.runtime_session import RuntimeSessionRecord
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


if __name__ == "__main__":
    unittest.main()
