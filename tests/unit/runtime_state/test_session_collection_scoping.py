from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.workspaces.errors import InvalidWorkspaceIdError
from tests.support.collections import FakeCollection


class RecordingCollection(FakeCollection):
    def __init__(self) -> None:
        super().__init__()
        self.find_one_queries: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        self.find_one_queries.append(dict(query))
        return super().find_one(query)


class TrackingRuntimeSessionJsonCollection(RuntimeSessionJsonCollection):
    def __init__(self, *, start_path: Path, filename: str) -> None:
        super().__init__(start_path=start_path, filename=filename)
        self.read_paths: list[Path] = []

    def _read_documents(self, path: Path) -> list[dict]:
        self.read_paths.append(path)
        return super()._read_documents(path)


class RuntimeSessionCollectionScopingTest(unittest.TestCase):
    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name) / "maverick"
        for name in ("apps", "core", "workspaces"):
            (root / name).mkdir(parents=True)
        (root / "AGENTS.md").write_text("", encoding="utf-8")
        return root

    def write_session(self, root: Path, *, workspace_id: str, session_id: str) -> Path:
        path = root / "workspaces" / workspace_id / "runtime" / "sessions" / session_id / "session.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps([{"workspace_id": workspace_id, "session_id": session_id}]),
            encoding="utf-8",
        )
        return path

    def test_workspace_query_reads_only_the_requested_workspace_partition(self) -> None:
        root = self.make_repo_root()
        default_path = self.write_session(root, workspace_id="default", session_id="session-default")
        self.write_session(root, workspace_id="test", session_id="session-test")
        collection = TrackingRuntimeSessionJsonCollection(start_path=root, filename="session.json")

        documents = collection.find({"workspace_id": "default"})

        self.assertEqual([item["session_id"] for item in documents], ["session-default"])
        self.assertEqual(collection.read_paths, [default_path])

    def test_workspace_query_rejects_an_unsafe_workspace_path(self) -> None:
        collection = RuntimeSessionJsonCollection(start_path=self.make_repo_root(), filename="session.json")

        with self.assertRaises(InvalidWorkspaceIdError):
            collection.find({"workspace_id": "../default"})

    def test_list_sessions_indexes_partitions_before_provider_state_projection(self) -> None:
        sessions = FakeCollection()
        provider_states = RecordingCollection()
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=sessions,
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                provider_states=provider_states,
            )
        )
        now = datetime(2026, 8, 27, tzinfo=UTC)
        session = RuntimeSessionRecord(
            session_id="session-a",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode=None,
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/workspace/runtime/session-a",
            started_at=now,
            updated_at=now,
            ended_at=None,
            last_progress_at=now,
        )
        provider_state = RuntimeProviderState(
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            runtime_engine_id="codex",
            model_provider_id="codex",
            continuation_id="provider-thread-a",
            provider_thread_id="provider-thread-a",
            provider_request_id=None,
            provider_private_envelope=None,
            revision=1,
            turn_generation=None,
            updated_at=now,
        )
        sessions.documents.append(asdict(session))
        provider_states.documents.append(asdict(provider_state))

        listed = store.list_sessions("default")

        self.assertEqual(listed[0].provider_thread_id, "provider-thread-a")
        self.assertEqual(
            provider_states.find_one_queries,
            [{"session_id": "session-a", "workspace_id": "default"}],
        )


if __name__ == "__main__":
    unittest.main()
