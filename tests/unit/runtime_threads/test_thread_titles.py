"""Tests for contextual runtime thread titles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from core.runtime.runtime_threads import (
    create_runtime_thread,
    mark_runtime_thread_user_message,
    reconcile_runtime_thread_availability,
    update_runtime_thread,
)
from core.runtime.service import create_runtime_session, queue_runtime_turn
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_catalog_events import mark_thread_user_message_queued
from core.runtime.thread_title_jobs import (
    thread_title_input_hash,
)
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE, derive_thread_title, runtime_thread_title_for_session
from tests.support.collections import FakeCollection


class CapturingThreadEventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, *, workspace_id: str, event: dict[str, object]) -> None:
        self.events.append({"workspace_id": workspace_id, **event})


class RuntimeThreadTitleTest(unittest.TestCase):
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

    def test_derives_contextual_title_from_storage_reference_message(self) -> None:
        title = derive_thread_title("Puoi analizzare @Q1 Report [ref:storage/file/file_1] e trovare anomalie?")

        self.assertEqual(title, "Analisi Q1 Report Anomalie")

    def test_derives_short_topic_instead_of_first_words(self) -> None:
        title = derive_thread_title("ho un problema con il drag and drop nello storage")

        self.assertEqual(title, "Problema Drag Drop Storage")

    def test_derives_improvement_topic_instead_of_setup_words(self) -> None:
        title = derive_thread_title(
            "è stato implementato un sistema per nomenclatura chat coerente con il primo messaggio. "
            "ma non funziona molto bene. mette le prime parole praticamente togliendo punteggiatura al massimo. "
            "invece dovrebbe mettere una frase di 4 o 5 parole che facciano capire di cosa si parla baste sul primo messaggio. "
            "fai una attenta analisi e fai un report per poter migliorare la cosa"
        )

        self.assertEqual(title, "Migliorare Nomenclatura Chat")

    def test_derives_app_store_fix_topic_from_prompt_preamble(self) -> None:
        title = derive_thread_title(
            "lavoriamo su @App Store . sono state fatte modifiche. voglio però che fai dei fix: "
            "ci sono le cartelle delle app ma tutte le app sono dentro frontend."
        )

        self.assertEqual(title, "Fix Cartelle App Store Frontend")

    def test_derives_storage_loading_topic_from_prompt_preamble(self) -> None:
        title = derive_thread_title(
            "lavoriamo su @Storage . quando entro in una cartella con dentro files voglio che parta "
            "il caricamento a skeleton invece di dirmi no folders or files here yet"
        )

        self.assertEqual(title, "Cartella Caricamento Skeleton Storage")

    def test_derives_conversion_topic_from_research_request(self) -> None:
        title = derive_thread_title(
            "fai una ricerca su web e trova il miglior strumento per trasformare doc pdf in md "
            "per farli utilizzare agli agenti"
        )

        self.assertEqual(title, "Conversione DOC PDF Markdown Agenti")

    def test_uses_reference_labels_when_message_is_generic(self) -> None:
        title = derive_thread_title(
            "analizza questo",
            app_references=[
                {
                    "type": "entity",
                    "app_id": "storage",
                    "entity_type": "file",
                    "entity_id": "file_1",
                    "label": "Budget 2026",
                }
            ],
        )

        self.assertEqual(title, "Analisi Budget 2026")

    def test_uses_attachment_names_for_attachment_only_turns(self) -> None:
        title = derive_thread_title("", attachments=[{"name": "fatture aprile.xlsx"}])

        self.assertEqual(title, "Fatture Aprile")

    def test_session_title_uses_first_meaningful_turn(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="chat",
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id=session.session_id, input_text="ciao", now=now)
        queue_runtime_turn(
            store,
            turn_id="turn-b",
            session_id=session.session_id,
            input_text="perche i test frontend di chat falliscono?",
            now=now + timedelta(seconds=1),
        )

        self.assertEqual(runtime_thread_title_for_session(store, session), "Test Frontend Chat Falliscono")

    def test_first_user_message_without_ai_hash_keeps_placeholder_title(self) -> None:
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
            input_text="Scrivi una mail di follow up per il cliente Rossi",
            now=now + timedelta(seconds=1),
        )

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text="Scrivi una mail di follow up per il cliente Rossi",
            now=now + timedelta(seconds=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertEqual(updated.title_source, "placeholder")
        self.assertFalse(updated.title_pending)

        update_runtime_thread(
            store,
            thread_id="thread-a",
            workspace_id="acme",
            updates={"title": "Titolo manuale"},
            now=now + timedelta(seconds=2),
        )
        queue_runtime_turn(
            store,
            turn_id="turn-b",
            session_id="session-a",
            input_text="nuovo argomento contabile",
            now=now + timedelta(seconds=3),
        )
        renamed = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text="nuovo argomento contabile",
            now=now + timedelta(seconds=3),
        )

        self.assertIsNotNone(renamed)
        assert renamed is not None
        self.assertEqual(renamed.title, "Titolo manuale")

    def test_first_user_message_marks_default_thread_title_pending_when_hash_is_provided(self) -> None:
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
        message = "analizza il budget vendite mensili del cliente Rossi"
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=message, now=now + timedelta(seconds=1))

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=message,
            title_generation_input_hash=thread_title_input_hash(message),
            now=now + timedelta(seconds=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(updated.title_pending)
        self.assertEqual(updated.title_source, "pending")

    def test_thread_catalog_event_creates_missing_pending_thread_when_hash_is_provided(self) -> None:
        store = self.make_store()
        event_bus = CapturingThreadEventBus()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        session = create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        turn = queue_runtime_turn(store, turn_id="turn-a", session_id=session.session_id, input_text=message, now=now + timedelta(seconds=1))
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=event_bus)

        updated = mark_thread_user_message_queued(
            state,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            input_text=message,
            title_generation_input_hash=input_hash,
            now=turn.created_at,
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(updated.title_pending)
        self.assertEqual(updated.title_source, "pending")
        self.assertEqual(updated.title_generation_input_hash, input_hash)
        self.assertTrue(event_bus.events[-1]["thread"]["title_pending"])

    def test_thread_metadata_upsert_preserves_pending_ai_title_generation(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=message, now=now + timedelta(seconds=1))
        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=message,
            title_generation_input_hash=input_hash,
            now=now + timedelta(seconds=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertTrue(updated.title_pending)
        upserted = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            agent_label="chat",
            project_id="project-1",
            now=now + timedelta(seconds=2),
        )

        self.assertEqual(upserted.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(upserted.title_pending)
        self.assertEqual(upserted.title_source, "pending")
        self.assertEqual(upserted.title_generation_input_hash, input_hash)
        self.assertEqual(upserted.project_id, "project-1")

        placeholder_upserted = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            title_source="placeholder",
            project_id="project-2",
            now=now + timedelta(seconds=3),
        )

        self.assertEqual(placeholder_upserted.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(placeholder_upserted.title_pending)
        self.assertEqual(placeholder_upserted.title_source, "pending")
        self.assertEqual(placeholder_upserted.title_generation_input_hash, input_hash)
        self.assertEqual(placeholder_upserted.project_id, "project-2")

    def test_thread_metadata_upsert_preserves_ai_title_metadata(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        input_hash = thread_title_input_hash("analizza il budget vendite mensili del cliente Rossi")
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Analisi Budget Vendite Mensili",
            title_source="ai",
            title_generation_input_hash=input_hash,
            now=now,
        )

        upserted = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Analisi Budget Vendite Mensili",
            agent_label="chat",
            project_id="project-1",
            now=now + timedelta(seconds=1),
        )

        self.assertEqual(upserted.title, "Analisi Budget Vendite Mensili")
        self.assertFalse(upserted.title_pending)
        self.assertEqual(upserted.title_source, "ai")
        self.assertEqual(upserted.title_generation_input_hash, input_hash)
        self.assertEqual(upserted.project_id, "project-1")

    def test_first_user_message_marks_placeholder_agent_title_pending_when_hash_is_provided(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "analizza il budget vendite mensili del cliente Rossi"
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Backend Systems Engineer",
            title_source="placeholder",
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=message, now=now + timedelta(seconds=1))

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=message,
            title_generation_input_hash=thread_title_input_hash(message),
            now=now + timedelta(seconds=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(updated.title_pending)
        self.assertEqual(updated.title_source, "pending")

    def test_reconcile_keeps_default_title_until_ai_generation_is_pending(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "questo è un test per testare che il naming della chat con ai funzioni davvero"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        thread = create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title=DEFAULT_THREAD_TITLE,
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=message, now=now + timedelta(seconds=1))
        reconciled = reconcile_runtime_thread_availability(
            store,
            workspace_id="acme",
            thread=thread,
            now=now + timedelta(seconds=2),
        )
        self.assertEqual(reconciled.title, DEFAULT_THREAD_TITLE)
        self.assertFalse(reconciled.title_pending)
        self.assertEqual(reconciled.title_source, "placeholder")
        self.assertEqual(reconciled.title_generation_input_hash, "")

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=message,
            title_generation_input_hash=input_hash,
            now=now + timedelta(seconds=3),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(updated.title_pending)
        self.assertEqual(updated.title_source, "pending")
        self.assertEqual(updated.title_generation_input_hash, input_hash)

    def test_first_user_message_can_recover_from_existing_early_deterministic_title(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        message = "questo è un test per testare che il naming della chat con ai funzioni davvero"
        input_hash = thread_title_input_hash(message)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Test Naming Chat Ai",
            title_source="deterministic",
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-a", session_id="session-a", input_text=message, now=now + timedelta(seconds=1))

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=message,
            title_generation_input_hash=input_hash,
            now=now + timedelta(seconds=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, DEFAULT_THREAD_TITLE)
        self.assertTrue(updated.title_pending)
        self.assertEqual(updated.title_source, "pending")
        self.assertEqual(updated.title_generation_input_hash, input_hash)

    def test_later_user_message_does_not_reopen_deterministic_title_generation(self) -> None:
        store = self.make_store()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(store, session_id="session-a", workspace_id="acme", agent_id="chat", now=now)
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="Fix Test Naming Title Chat",
            title_source="deterministic",
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="questo è un test per testare che il naming della chat con ai funzioni davvero",
            now=now + timedelta(seconds=1),
        )
        second_message = "niente il nome è ancora deterministico"
        queue_runtime_turn(store, turn_id="turn-b", session_id="session-a", input_text=second_message, now=now + timedelta(seconds=2))

        updated = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            input_text=second_message,
            title_generation_input_hash=thread_title_input_hash(second_message),
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Fix Test Naming Title Chat")
        self.assertFalse(updated.title_pending)
        self.assertEqual(updated.title_source, "deterministic")
        self.assertEqual(updated.title_generation_input_hash, "")

if __name__ == "__main__":
    unittest.main()
