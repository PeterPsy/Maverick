from __future__ import annotations

import unittest

from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class CountingCollection(FakeCollection):
    def __init__(self) -> None:
        super().__init__()
        self.delete_many_calls: list[dict] = []

    def delete_many(self, query: dict) -> int:
        self.delete_many_calls.append(query)
        return super().delete_many(query)


class RuntimeStoreBatchDeleteTest(unittest.TestCase):
    def test_batch_deletes_shared_collection_records_with_one_mutation(self) -> None:
        sessions = FakeCollection()
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

        deleted = store.delete_session_records_batch(["session-1", "session-2"])

        self.assertEqual(client_messages.delete_many_calls, [{"session_id": {"$in": ["session-1", "session-2"]}, "workspace_id": "default"}])
        self.assertEqual(deleted["session-1"]["client_messages"], 1)
        self.assertEqual(deleted["session-2"]["client_messages"], 1)
        self.assertEqual(
            [document["session_id"] for document in client_messages.find({})],
            ["session-kept"],
        )


if __name__ == "__main__":
    unittest.main()
