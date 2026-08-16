from __future__ import annotations

import unittest

from core.runtime.service import create_runtime_session, queue_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RecordingCollection(FakeCollection):
    def __init__(self) -> None:
        super().__init__()
        self.find_one_queries: list[dict] = []
        self.insert_one_if_absent_queries: list[dict] = []
        self.update_one_queries: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        self.find_one_queries.append(dict(query))
        return super().find_one(query)

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        self.update_one_queries.append(dict(query))
        return super().update_one(query, update, upsert=upsert)

    def insert_one_if_absent(self, query: dict, document: dict) -> tuple[dict, bool]:
        self.insert_one_if_absent_queries.append(dict(query))
        return super().insert_one_if_absent(query, document)


class RuntimeStorePartitionIndexTestCase(unittest.TestCase):
    def test_recent_turn_and_state_reads_use_indexed_session_partition_queries(self) -> None:
        sessions = RecordingCollection()
        turns = RecordingCollection()
        states = RecordingCollection()
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=sessions,
                turns=turns,
                events=FakeCollection(),
                processes=FakeCollection(),
                states=states,
                threads=FakeCollection(),
            )
        )
        repo_root = make_temp_repo_root(self)
        session = create_runtime_session(
            store,
            session_id="sess-indexed",
            workspace_id="acme",
            agent_id="agent-1",
            start_path=repo_root,
        )
        turn = queue_runtime_turn(store, turn_id="turn-indexed", session_id=session.session_id, input_text="hello")

        self.assertIn({"session_id": session.session_id, "workspace_id": "acme"}, sessions.update_one_queries)
        self.assertIn({"session_id": session.session_id, "workspace_id": "acme"}, states.update_one_queries)
        self.assertEqual(
            turns.insert_one_if_absent_queries,
            [{"turn_id": turn.turn_id, "workspace_id": "acme", "session_id": session.session_id}],
        )

        turns.find_one_queries.clear()
        states.find_one_queries.clear()

        self.assertEqual(store.get_turn(turn.turn_id).turn_id, turn.turn_id)
        self.assertEqual(store.get_state(session.session_id).session_id, session.session_id)

        self.assertEqual(
            turns.find_one_queries,
            [{"turn_id": turn.turn_id, "workspace_id": "acme", "session_id": session.session_id}],
        )
        self.assertEqual(states.find_one_queries, [{"session_id": session.session_id, "workspace_id": "acme"}])


if __name__ == "__main__":
    unittest.main()
