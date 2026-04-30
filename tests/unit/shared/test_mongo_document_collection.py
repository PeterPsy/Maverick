"""Tests for Mongo document collection adapter behavior."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import unittest
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

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        self.updates.append({"query": deepcopy(query), "update": deepcopy(update), "upsert": upsert})
        payload = deepcopy(update.get("$set", {}))
        unset_payload = deepcopy(update.get("$unset", {}))
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                updated = {**document, **payload}
                for field in unset_payload:
                    updated.pop(field, None)
                self.documents[index] = updated
                return
        if upsert:
            self.documents.append({"_id": f"fake-{len(self.documents)}", **payload})

    def delete_one(self, query: dict[str, Any]) -> None:
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                del self.documents[index]
                return

    def delete_many(self, query: dict[str, Any]) -> None:
        self.documents = [document for document in self.documents if not _matches(document, query)]

    def insert_many(self, documents: list[dict[str, Any]]) -> None:
        self.documents.extend(deepcopy(documents))


class MongoDocumentCollectionTestCase(unittest.TestCase):
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

    def test_reads_normalize_naive_datetimes_to_utc(self) -> None:
        fake = FakeMongoCollection()
        fake.documents.append({"_id": "mongo-id", "session_id": "s1", "expires_at": datetime(2026, 4, 30, 8, 0, 0)})
        collection = MongoDocumentCollection(fake)

        document = collection.find_one({"session_id": "s1"})

        assert document is not None
        self.assertEqual(document["expires_at"].tzinfo, UTC)


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    return all(document.get(key) == value for key, value in query.items())


if __name__ == "__main__":
    unittest.main()
