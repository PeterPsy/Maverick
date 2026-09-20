from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core.runtime.event_collection import RuntimeEventJsonCollection
from tests.support.repo import make_temp_repo_root


class RuntimeEventCollectionTest(unittest.TestCase):
    def test_forward_history_pages_cross_chunks_without_materializing_other_sessions(self) -> None:
        root = make_temp_repo_root(self)
        collection = RuntimeEventJsonCollection(start_path=root)
        history = root / 'workspaces/default/runtime/sessions/session-1/events-history'
        history.mkdir(parents=True)
        for chunk in range(4):
            documents = [{'event_id': f'event-{index:03}', 'workspace_id': 'default', 'session_id': 'session-1',
                'created_at': f'2026-09-20T00:00:{index:02}+00:00'} for index in range(chunk * 5, (chunk + 1) * 5)]
            (history / f'{chunk:06}.json').write_text(json.dumps(documents))
        other = root / 'workspaces/default/runtime/sessions/session-2/events-history'
        other.mkdir(parents=True)
        (other / '000000.json').write_text('Must never decode another session')
        query = {'workspace_id': 'default', 'session_id': 'session-1'}
        with patch.object(collection, '_matching_sorted_documents', wraps=collection._matching_sorted_documents) as read:
            page = collection.find_event_page(query, before_event_id=None, after_event_id='event-014', limit=3)
        self.assertEqual([item['event_id'] for item in page['documents']], ['event-015', 'event-016', 'event-017'])
        self.assertTrue(page['has_more_after'])
        self.assertLessEqual(read.call_count, 3)
        final = collection.find_event_page(query, before_event_id=None, after_event_id='event-017', limit=3)
        self.assertEqual([item['event_id'] for item in final['documents']], ['event-018', 'event-019'])
        self.assertFalse(final['has_more_after'])
        missing = collection.find_event_page(query, before_event_id=None, after_event_id='missing', limit=3)
        self.assertEqual(missing['documents'], [])
        self.assertFalse(missing['cursor_found'])

    def test_forward_hot_tail_and_exclusive_directions(self) -> None:
        collection = RuntimeEventJsonCollection(start_path=make_temp_repo_root(self))
        for index in range(4):
            self._append_event(collection, index=index, max_documents=10)
        query = {'workspace_id': 'default', 'session_id': 'session-1'}
        page = collection.find_event_page(query, before_event_id=None, after_event_id='event-1', limit=1)
        self.assertEqual([item['event_id'] for item in page['documents']], ['event-2'])
        self.assertTrue(page['has_more_after'])
        tail = collection.find_event_page(query, before_event_id=None, after_event_id='event-3', limit=1)
        self.assertTrue(tail['cursor_found'])
        self.assertTrue(tail['has_more_before'])
        self.assertFalse(tail['has_more_after'])
        with self.assertRaises(ValueError):
            collection.find_event_page(query, before_event_id='event-1', after_event_id='event-2', limit=1)

    def test_full_hot_tail_appends_between_bounded_compactions(self) -> None:
        repo_root = make_temp_repo_root(self)
        collection = RuntimeEventJsonCollection(start_path=repo_root)
        event_path = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "session-1" / "events.json"

        with patch.object(collection, "_write_documents", wraps=collection._write_documents) as rewrite:
            for index in range(6):
                self._append_event(collection, index=index, max_documents=3)

            self.assertEqual(rewrite.call_count, 0)
            self.assertEqual(len(json.loads(event_path.read_text(encoding="utf-8"))), 6)

            self._append_event(collection, index=6, max_documents=3)

            self.assertEqual(rewrite.call_count, 1)
            self.assertEqual(
                [document["event_id"] for document in json.loads(event_path.read_text(encoding="utf-8"))],
                ["event-4", "event-5", "event-6"],
            )

    def test_delete_session_partition_does_not_decode_history_archives_for_counting(self) -> None:
        repo_root = make_temp_repo_root(self)
        collection = RuntimeEventJsonCollection(start_path=repo_root)
        history_root = (
            repo_root
            / "workspaces"
            / "default"
            / "runtime"
            / "sessions"
            / "session-1"
            / "events-history"
        )
        history_root.mkdir(parents=True)
        (history_root / "000000.json").write_text("archive bytes need not be decoded", encoding="utf-8")

        with patch.object(collection, "_read_documents", side_effect=AssertionError("history decoded")):
            deleted = collection.delete_session_partition(session_id="session-1", workspace_id="default")

        self.assertEqual(deleted, 0)
        self.assertFalse(history_root.exists())

    @staticmethod
    def _append_event(collection: RuntimeEventJsonCollection, *, index: int, max_documents: int) -> None:
        collection.append_bounded_upsert(
            {"event_id": f"event-{index}"},
            {
                "$set": {
                    "event_id": f"event-{index}",
                    "workspace_id": "default",
                    "session_id": "session-1",
                    "created_at": f"2026-08-16T10:00:{index:02d}+00:00",
                }
            },
            max_documents=max_documents,
        )


if __name__ == "__main__":
    unittest.main()
