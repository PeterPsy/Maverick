from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.shared.in_memory_collection import InMemoryCollection


class InMemoryCollectionTest(unittest.TestCase):
    def test_deadline_cas_rejects_expired_document_and_accepts_live_one(self) -> None:
        collection = InMemoryCollection()
        collection.update_one(
            {"record_id": "expired"},
            {
                "$set": {
                    "record_id": "expired",
                    "expires_at": datetime.now(tz=UTC) - timedelta(seconds=1),
                    "state": "executing",
                }
            },
            upsert=True,
        )
        collection.update_one(
            {"record_id": "live"},
            {
                "$set": {
                    "record_id": "live",
                    "expires_at": datetime.now(tz=UTC) + timedelta(minutes=1),
                    "state": "executing",
                }
            },
            upsert=True,
        )

        self.assertFalse(
            collection.compare_and_set_if_datetime_future(
                {"record_id": "expired"},
                {"$set": {"state": "succeeded"}},
                field="expires_at",
            )
        )
        self.assertTrue(
            collection.compare_and_set_if_datetime_future(
                {"record_id": "live"},
                {"$set": {"state": "succeeded"}},
                field="expires_at",
            )
        )
        self.assertEqual(
            collection.find_one({"record_id": "expired"})["state"],
            "executing",
        )
        self.assertEqual(
            collection.find_one({"record_id": "live"})["state"],
            "succeeded",
        )

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
