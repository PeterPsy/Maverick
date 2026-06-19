"""Regression tests for runtime thread title metadata races."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.runtime.runtime_threads import (
    create_runtime_thread,
    mark_runtime_thread_user_message,
    reconcile_runtime_thread_availability,
)
from core.runtime.service import create_runtime_session, queue_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_title_jobs import thread_title_input_hash
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE
from tests.support.collections import FakeCollection


class RuntimeThreadTitleRaceTest(unittest.TestCase):
    def make_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def test_stale_reconcile_preserves_pending_ai_title_generation(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        stale_thread = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=message, now=now + timedelta(seconds=1))
        pending = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=message,
            title_generation_input_hash=input_hash,
            now=now + timedelta(seconds=1),
        )
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertTrue(pending.title_pending)

        reconciled = reconcile_runtime_thread_availability(
            store,
            workspace_id="acme",
            thread=stale_thread,
            now=now + timedelta(seconds=2),
        )
        stored = store.get_thread("thread-a")

        self.assertEqual(reconciled.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(reconciled.title_pending)
        self.assertEqual(reconciled.title_source, "pending")
        self.assertEqual(reconciled.title_generation_input_hash, input_hash)
        self.assertTrue(stored.title_pending)
        self.assertEqual(stored.title_source, "pending")
        self.assertEqual(stored.title_generation_input_hash, input_hash)


if __name__ == "__main__":
    unittest.main()
