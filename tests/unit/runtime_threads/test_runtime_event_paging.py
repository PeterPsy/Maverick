"""Directional event paging through the document store contract."""

from datetime import UTC, datetime, timedelta
import unittest

from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


class RuntimeEventPagingTest(unittest.TestCase):
    def test_forward_store_fallback_preserves_exclusive_cursor_and_tail_flags(self) -> None:
        store = RuntimeDocumentStore(RuntimeCollections(**{
            name: FakeCollection() for name in ("sessions", "turns", "events", "processes", "states", "threads")
        }))
        for index in range(5):
            store.save_event(RuntimeEventRecord(
                event_id=f"event-{index}", session_id="session", workspace_id="default",
                turn_id=None, process_id=None, plane="turn", event_type="runtime.output.delta", payload={},
                created_at=datetime(2026, 9, 20, tzinfo=UTC) + timedelta(seconds=index),
            ))
        page = store.list_event_page("session", after_event_id="event-1", limit=2)
        self.assertEqual([event.event_id for event in page.events], ["event-2", "event-3"])
        self.assertTrue(page.has_more_before)
        self.assertTrue(page.has_more_after)
        tail = store.list_event_page("session", after_event_id="event-4", limit=2)
        self.assertEqual(tail.events, [])
        self.assertTrue(tail.has_more_before)
        self.assertFalse(tail.has_more_after)
        missing = store.list_event_page("session", after_event_id="unknown", limit=2)
        self.assertEqual(missing.events, [])
        self.assertFalse(missing.has_more_before or missing.has_more_after)
        self.assertEqual(store.find_event("session", "event-2").event_id, "event-2")
        self.assertIsNone(store.find_event("other-session", "event-2"))
        with self.assertRaises(ValueError):
            store.list_event_page("session", before_event_id="event-1", after_event_id="event-3")
