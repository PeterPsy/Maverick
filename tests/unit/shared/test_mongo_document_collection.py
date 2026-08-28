"""Tests for Mongo document collection adapter behavior."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import unittest
from unittest.mock import patch
from typing import Any

from core.shared.mongo_document_collection import MongoDocumentCollection


class FakeMongoCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for document in self.documents:
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        return [deepcopy(document) for document in self.documents if _matches(document, query)]

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False):
        self.updates.append({"query": deepcopy(query), "update": deepcopy(update), "upsert": upsert})
        payload = deepcopy(update.get("$set", {}))
        insert_payload = deepcopy(update.get("$setOnInsert", {}))
        unset_payload = deepcopy(update.get("$unset", {}))
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                updated = {**document, **payload}
                for field in unset_payload:
                    updated.pop(field, None)
                self.documents[index] = updated
                return FakeUpdateResult(None, matched_count=1)
        if upsert:
            inserted_id = f"fake-{len(self.documents)}"
            self.documents.append({"_id": inserted_id, **deepcopy(query), **insert_payload, **payload})
            return FakeUpdateResult(inserted_id, matched_count=0)
        return FakeUpdateResult(None, matched_count=0)

    def delete_one(self, query: dict[str, Any]) -> None:
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                del self.documents[index]
                return

    def delete_many(self, query: dict[str, Any]):
        retained = [document for document in self.documents if not _matches(document, query)]
        deleted_count = len(self.documents) - len(retained)
        self.documents = retained
        return FakeDeleteResult(deleted_count)

    def insert_many(self, documents: list[dict[str, Any]]) -> None:
        self.documents.extend(deepcopy(documents))


class MongoDocumentCollectionTestCase(unittest.TestCase):
    def test_compare_and_set_reports_match_and_rejects_stale_revision(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.append({"record_id": "one", "revision": 0})
        collection = MongoDocumentCollection(fake)

        self.assertTrue(
            collection.compare_and_set(
                {"record_id": "one", "revision": 0},
                {"$set": {"revision": 1}},
            )
        )
        self.assertFalse(
            collection.compare_and_set(
                {"record_id": "one", "revision": 0},
                {"$set": {"revision": 2}},
            )
        )
        self.assertEqual(collection.find_one({"record_id": "one"})["revision"], 1)

    def test_deadline_cas_uses_server_time_in_the_update_predicate(self) -> None:
        fake = FakeMongoCollection()
        collection = MongoDocumentCollection(fake)

        with patch.object(
            fake,
            "update_one",
            return_value=FakeUpdateResult(None, matched_count=1),
        ) as update_one:
            applied = collection.compare_and_set_if_datetime_future(
                {"record_id": "one", "revision": 3},
                {"$set": {"revision": 4, "state": "succeeded"}},
                field="execution_lease_expires_at",
            )

        self.assertTrue(applied)
        query = update_one.call_args.args[0]
        self.assertEqual(query["record_id"], "one")
        self.assertEqual(query["revision"], 3)
        self.assertEqual(
            query["execution_lease_expires_at"],
            {"$type": "date"},
        )
        self.assertEqual(
            query["$expr"],
            {"$gt": ["$execution_lease_expires_at", "$$NOW"]},
        )

    def test_insert_one_if_absent_is_idempotent(self) -> None:
        collection = MongoDocumentCollection(FakeMongoCollection())

        first, inserted = collection.insert_one_if_absent({"identity": "one"}, {"value": 1})
        replay, replay_inserted = collection.insert_one_if_absent({"identity": "one"}, {"value": 2})

        self.assertTrue(inserted)
        self.assertFalse(replay_inserted)
        self.assertEqual(first, {"identity": "one", "value": 1})
        self.assertEqual(replay, first)

    def test_insert_one_if_absent_reraises_an_unrelated_unique_collision(self) -> None:
        collision = RuntimeError("other unique index collided")

        class CollidingCollection(FakeMongoCollection):
            def update_one(self, query, update, *, upsert=False):
                raise collision

        collection = MongoDocumentCollection(CollidingCollection())
        with patch("core.shared.mongo_document_collection._is_duplicate_key_error", return_value=True):
            with self.assertRaises(RuntimeError) as raised:
                collection.insert_one_if_absent({"identity": "one"}, {"value": 1})

        self.assertIs(raised.exception, collision)

    def test_upsert_merges_query_fields_into_insert_payload(self) -> None:
        fake = FakeMongoCollection()
        collection = MongoDocumentCollection(fake)

        collection.update_one({"workspace_id": "default"}, {"$set": {"title": "Default"}}, upsert=True)

        self.assertEqual(fake.updates[0]["update"]["$set"], {"workspace_id": "default", "title": "Default"})
        self.assertEqual(collection.find_one({"workspace_id": "default"}), {"workspace_id": "default", "title": "Default"})

    def test_reads_strip_mongo_id_and_return_copies(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.append({"_id": "mongo-id", "user_id": "u1", "profile": {"name": "Ada"}})
        collection = MongoDocumentCollection(fake)

        document = collection.find_one({"user_id": "u1"})
        assert document is not None
        document["profile"]["name"] = "Changed"

        self.assertEqual(document, {"user_id": "u1", "profile": {"name": "Changed"}})
        self.assertEqual(collection.find_one({"user_id": "u1"}), {"user_id": "u1", "profile": {"name": "Ada"}})

    def test_replace_all_requires_object_documents(self) -> None:
        collection = MongoDocumentCollection(FakeMongoCollection())

        with self.assertRaisesRegex(ValueError, "only store object documents"):
            collection.replace_all([{"ok": True}, "bad"])  # type: ignore[list-item]

    def test_replace_all_replaces_collection_documents(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.append({"old": True})
        collection = MongoDocumentCollection(fake)

        collection.replace_all([{"new": True}])

        self.assertEqual(collection.find({}), [{"new": True}])

    def test_update_supports_unset_for_migrations(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.append({"_id": "mongo-id", "secret_id": "s1", "raw_value": "secret"})
        collection = MongoDocumentCollection(fake)

        collection.update_one(
            {"secret_id": "s1"},
            {"$set": {"value_format": "mvr3secret1"}, "$unset": {"raw_value": ""}},
        )

        self.assertEqual(collection.find_one({"secret_id": "s1"}), {"secret_id": "s1", "value_format": "mvr3secret1"})

    def test_delete_many_returns_the_native_deleted_count(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.extend(
            [
                {"session_id": "session-1"},
                {"session_id": "session-2"},
                {"session_id": "session-3"},
            ]
        )
        collection = MongoDocumentCollection(fake)

        deleted = collection.delete_many({"session_id": {"$in": ["session-1", "session-3"]}})

        self.assertEqual(deleted, 2)
        self.assertEqual(collection.find({}), [{"session_id": "session-2"}])

    def test_delete_many_documents_returns_the_matched_snapshot(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.extend(
            [
                {"_id": "one", "session_id": "session-1"},
                {"_id": "two", "session_id": "session-2"},
            ]
        )
        collection = MongoDocumentCollection(fake)

        deleted = collection.delete_many_documents({"session_id": "session-1"})

        self.assertEqual(deleted, [{"session_id": "session-1"}])
        self.assertEqual(collection.find({}), [{"session_id": "session-2"}])

    def test_reads_normalize_naive_datetimes_to_utc(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.append({"_id": "mongo-id", "session_id": "s1", "expires_at": datetime(2026, 4, 30, 8, 0, 0)})
        collection = MongoDocumentCollection(fake)

        document = collection.find_one({"session_id": "s1"})

        assert document is not None
        self.assertEqual(document["expires_at"].tzinfo, UTC)


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict) and set(expected) == {"$in"}:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class FakeUpdateResult:
    def __init__(self, upserted_id: str | None, *, matched_count: int = 0) -> None:
        self.upserted_id = upserted_id
        self.matched_count = matched_count


class FakeDeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


if __name__ == "__main__":
    unittest.main()
