from __future__ import annotations

import unittest

from core.shared.in_memory_collection import InMemoryCollection


class InMemoryCollectionTest(unittest.TestCase):
    def test_in_query_is_consistent_for_find_and_batch_delete(self) -> None:
        collection = InMemoryCollection()
        for session_id in ("session-1", "session-2", "session-3"):
            collection.update_one(
                {"session_id": session_id},
                {"$set": {"session_id": session_id}},
                upsert=True,
            )

        query = {"session_id": {"$in": ["session-1", "session-3"]}}

        self.assertEqual(
            [document["session_id"] for document in collection.find(query)],
            ["session-1", "session-3"],
        )
        self.assertEqual(
            [document["session_id"] for document in collection.delete_many_documents(query)],
            ["session-1", "session-3"],
        )
        self.assertEqual(collection.find({}), [{"session_id": "session-2"}])


if __name__ == "__main__":
    unittest.main()
