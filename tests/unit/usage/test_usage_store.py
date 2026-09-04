"""Usage document-store persistence behavior."""

from __future__ import annotations

import unittest

from core.usage.store import UsageCollections, UsageDocumentStore
from tests.support.collections import FakeCollection


class _RecordingCollection(FakeCollection):
    def __init__(self) -> None:
        super().__init__()
        self.delete_many_documents_queries: list[dict] = []

    def delete_many_documents(self, query: dict) -> list[dict]:
        self.delete_many_documents_queries.append(query)
        return super().delete_many_documents(query)


class UsageDocumentStoreTest(unittest.TestCase):
    def test_delete_sessions_removes_all_samples_with_one_collection_mutation(self) -> None:
        samples = _RecordingCollection()
        samples.documents = [
            {"sample_id": "sample-1", "session_id": "session-1"},
            {"sample_id": "sample-2", "session_id": "session-1"},
            {"sample_id": "sample-3", "session_id": "session-2"},
            {"sample_id": "sample-4", "session_id": "session-kept"},
        ]
        store = UsageDocumentStore(
            UsageCollections(
                samples=samples,
                buckets=FakeCollection(),
                quota_snapshots=FakeCollection(),
            )
        )

        deleted = store.delete_sessions(["session-1", "session-2", "session-1"])

        self.assertEqual(deleted, {"session-1": 2, "session-2": 1})
        self.assertEqual(
            samples.delete_many_documents_queries,
            [{"session_id": {"$in": ["session-1", "session-2"]}}],
        )
        self.assertEqual(samples.documents, [{"sample_id": "sample-4", "session_id": "session-kept"}])


if __name__ == "__main__":
    unittest.main()
