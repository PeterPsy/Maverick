"""Tests for local JSON collection persistence behavior."""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from core.shared.json_file_collection import JsonFileCollection


def _write_json_collection_records(path_text: str, start: int, count: int) -> None:
    collection = JsonFileCollection(Path(path_text))
    for index in range(start, start + count):
        collection.update_one({"event_id": f"event-{index}"}, {"$set": {"event_id": f"event-{index}", "value": index}}, upsert=True)


class JsonFileCollectionTestCase(unittest.TestCase):
    def test_append_only_upsert_appends_without_losing_existing_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.json"
            collection = JsonFileCollection(path, append_only_upserts=True)

            collection.update_one({"event_id": "event-1"}, {"$set": {"event_id": "event-1", "value": 1}}, upsert=True)
            first_size = path.stat().st_size
            collection.update_one({"event_id": "event-2"}, {"$set": {"event_id": "event-2", "value": 2}}, upsert=True)

            self.assertGreater(path.stat().st_size, first_size)
            self.assertEqual(collection.find({"event_id": "event-1"})[0]["value"], 1)
            self.assertEqual(collection.find({"event_id": "event-2"})[0]["value"], 2)
            self.assertEqual([item["event_id"] for item in json.loads(path.read_text(encoding="utf-8"))], ["event-1", "event-2"])

    def test_malformed_collection_is_not_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.json"
            path.write_text("[\n", encoding="utf-8")
            collection = JsonFileCollection(path)

            with self.assertRaises(ValueError):
                collection.update_one({"event_id": "event-1"}, {"$set": {"event_id": "event-1"}}, upsert=True)

            self.assertEqual(path.read_text(encoding="utf-8"), "[\n")

    def test_concurrent_writers_do_not_share_temporary_paths_or_lose_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.json"
            processes = [
                multiprocessing.Process(target=_write_json_collection_records, args=(str(path), offset, 10))
                for offset in (0, 10, 20, 30)
            ]

            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)

            self.assertTrue(all(process.exitcode == 0 for process in processes))
            documents = JsonFileCollection(path).find({})
            self.assertEqual(len(documents), 40)
            self.assertEqual(sorted(document["value"] for document in documents), list(range(40)))


if __name__ == "__main__":
    unittest.main()
