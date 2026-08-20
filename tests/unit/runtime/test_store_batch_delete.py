from __future__ import annotations

import unittest

from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class CountingCollection(FakeCollection):
    def __init__(self) -> None:
        super().__init__()
        self.delete_many_documents_calls: list[dict] = []

    def delete_many_documents(self, query: dict) -> list[dict]:
        self.delete_many_documents_calls.append(query)
        return super().delete_many_documents(query)


class SessionCollection(FakeCollection):
    def __init__(self) -> None:
        super().__init__()
        self.find_one_calls: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        self.find_one_calls.append(query)
        return super().find_one(query)


class RuntimeStoreBatchDeleteTest(unittest.TestCase):
    def test_batch_deletes_shared_collection_records_with_one_mutation(self) -> None:
        sessions = SessionCollection()
        client_messages = CountingCollection()
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=sessions,
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                client_messages=client_messages,
            )
        )
        for session_id in ("session-1", "session-2", "session-kept"):
            sessions.update_one(
                {"session_id": session_id},
                {"$set": {"session_id": session_id, "workspace_id": "default"}},
                upsert=True,
            )
            client_messages.update_one(
                {"client_message_id": f"message-{session_id}"},
                {
                    "$set": {
                        "client_message_id": f"message-{session_id}",
                        "session_id": session_id,
                        "workspace_id": "default",
                    }
                },
                upsert=True,
            )
        store._remember_session_partition("session-1", "default")
        store._remember_session_partition("session-2", "default")

        deleted = store.delete_session_records_batch(["session-1", "session-2"])

        self.assertEqual(sessions.find_one_calls, [])
        self.assertEqual(client_messages.delete_many_documents_calls, [{"session_id": {"$in": ["session-1", "session-2"]}, "workspace_id": "default"}])
        self.assertEqual(deleted["session-1"]["client_messages"], 1)
        self.assertEqual(deleted["session-2"]["client_messages"], 1)
        self.assertEqual(
            [document["session_id"] for document in client_messages.find({})],
            ["session-kept"],
        )


if __name__ == "__main__":
    unittest.main()
