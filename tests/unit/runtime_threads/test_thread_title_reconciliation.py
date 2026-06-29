"""Tests for runtime thread title reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from core.runtime.runtime_threads import (
    create_runtime_thread,
    mark_runtime_thread_user_message,
    reconcile_runtime_thread_availability,
)
from core.runtime.service import create_runtime_session, queue_runtime_turn, record_runtime_event
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE
from tests.support.collections import FakeCollection


class RuntimeThreadTitleReconciliationTest(unittest.TestCase):
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

    def test_later_user_message_preserves_existing_non_default_thread_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        first_prompt = (
            "è stato implementato un sistema per nomenclatura chat coerente con il primo messaggio. "
            "ma non funziona molto bene. mette le prime parole praticamente togliendo punteggiatura al massimo. "
            "invece dovrebbe mettere una frase di 4 o 5 parole che facciano capire di cosa si parla baste sul primo messaggio. "
            "fai una attenta analisi e fai un report per poter migliorare la cosa"
        )
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Stato Implementato Sistema Nomenclatura",
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=first_prompt, now=now + timedelta(seconds=1))
        queue_runtime_turn(
            store,
            turn_id="turn-b",
            session_id="session-a",
            input_text="continua da dove eri rimasto",
            now=now + timedelta(seconds=2),
        )

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text="continua da dove eri rimasto",
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Stato Implementato Sistema Nomenclatura")

    def test_reconcile_preserves_existing_non_default_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        thread = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Titolo manuale",
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="è stato implementato un sistema per nomenclatura chat coerente con il primo messaggio",
            now=now + timedelta(seconds=1),
        )

        reconciled = reconcile_runtime_thread_availability(store, workspace_id="acme", thread=thread, now=now + timedelta(seconds=2))

        self.assertEqual(reconciled.title, "Titolo manuale")

    def test_non_meaningful_first_message_keeps_default_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="ciao",
            now=now + timedelta(seconds=1),
        )

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text="ciao",
            now=now + timedelta(seconds=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)

    def test_mark_without_ai_hash_keeps_default_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="Analizza il report vendite",
            now=now + timedelta(seconds=1),
        )
        queue_runtime_turn(
            store,
            turn_id="turn-b",
            session_id="session-a",
            input_text="nuovo argomento contabile",
            now=now + timedelta(seconds=2),
        )

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text="nuovo argomento contabile",
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertEqual(updated.title_source, "placeholder")
        self.assertFalse(updated.title_pending)

    def test_reconcile_keeps_default_thread_title_from_stored_turn(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        thread = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="questo è un test per la verifica della nomenclatura contestuale della chat in titolo",
            now=now + timedelta(seconds=1),
        )

        reconciled = reconcile_runtime_thread_availability(
            store,
            workspace_id="acme",
            thread=thread,
            now=now + timedelta(seconds=2),
        )

        self.assertEqual(reconciled.title, DEFAULT_THREAD_TITLE)
        self.assertEqual(reconciled.title_source, "placeholder")

    def test_reconcile_does_not_use_queued_event_references_for_early_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        thread = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="analizza questo",
            now=now + timedelta(seconds=1),
        )
        record_runtime_event(
            store,
            event_id="event-a",
            session_id="session-a",
            turn_id="turn-a",
            plane="turn",
            event_type="runtime.turn.queued",
            payload={
                "input_text": "analizza questo",
                "app_references": [
                    {
                        "type": "entity",
                        "app_id": "storage",
                        "entity_type": "file",
                        "entity_id": "file_1",
                        "label": "Budget 2026",
                    }
                ],
            },
            now=now + timedelta(seconds=1),
        )

        reconciled = reconcile_runtime_thread_availability(
            store,
            workspace_id="acme",
            thread=thread,
            now=now + timedelta(seconds=2),
        )

        self.assertEqual(reconciled.title, DEFAULT_THREAD_TITLE)
        self.assertEqual(reconciled.title_source, "placeholder")

    def test_reconcile_does_not_backfill_when_older_queued_event_is_missing(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        thread = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="test nomenclatura contestuale chat",
            now=now + timedelta(seconds=1),
        )
        queue_runtime_turn(
            store,
            turn_id="turn-b",
            session_id="session-a",
            input_text="ok fixa allora perché era stato implementato questo",
            now=now + timedelta(seconds=2),
        )
        record_runtime_event(
            store,
            event_id="event-b",
            session_id="session-a",
            turn_id="turn-b",
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"input_text": "ok fixa allora perché era stato implementato questo"},
            now=now + timedelta(seconds=2),
        )

        reconciled = reconcile_runtime_thread_availability(
            store,
            workspace_id="acme",
            thread=thread,
            now=now + timedelta(seconds=3),
        )

        self.assertEqual(reconciled.title, DEFAULT_THREAD_TITLE)
        self.assertEqual(reconciled.title_source, "placeholder")


if __name__ == "__main__":
    unittest.main()
