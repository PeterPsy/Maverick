"""Tests for contextual runtime thread titles."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import signal
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.runtime.runtime_threads import (
    create_runtime_thread,
    mark_runtime_thread_user_message,
    reconcile_runtime_thread_availability,
    update_runtime_thread,
)
from core.runtime.service import create_runtime_session, queue_runtime_turn, record_runtime_event
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.thread_catalog_events import mark_thread_user_message_queued
from core.runtime.thread_title_jobs import (
    ThreadTitleGenerationError,
    _run_codex_title_command,
    fallback_thread_title,
    run_runtime_thread_title_generation,
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

    def test_first_user_message_updates_only_default_thread_title(self) -> None:
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
        self.assertEqual(updated.title, "Mail Follow Up Cliente Rossi")

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

    def test_ai_title_job_completes_pending_thread_title(self) -> None:
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
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: "Analisi Budget Vendite Mensili",
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Analisi Budget Vendite Mensili")
        self.assertFalse(updated.title_pending)
        self.assertEqual(updated.title_source, "ai")
        self.assertIsNone(updated.title_generation_failure)

    def test_ai_title_job_falls_back_to_deterministic_title_when_model_title_is_invalid(self) -> None:
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
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: "Budget",
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertFalse(updated.title_pending)
        self.assertEqual(updated.title_source, "deterministic")
        self.assertEqual(updated.title, fallback_thread_title(message))
        self.assertTrue(updated.title_generation_failure)

    def test_ai_title_job_does_not_overwrite_manual_rename(self) -> None:
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
            title_pending=True,
            title_source="pending",
            title_generation_input_hash=input_hash,
            now=now,
        )
        update_runtime_thread(
            store,
            thread_id="thread-a",
            workspace_id="acme",
            updates={"title": "Titolo scelto manualmente"},
            now=now + timedelta(seconds=1),
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=None)

        updated = run_runtime_thread_title_generation(
            state=state,
            workspace_id="acme",
            runtime_session_id="session-a",
            title_generation_input_hash=input_hash,
            input_text=message,
            title_generator=lambda **_: "Analisi Budget Vendite Mensili",
        )

        self.assertIsNone(updated)
        thread = store.get_thread("thread-a")
        self.assertEqual(thread.title, "Titolo scelto manualmente")
        self.assertFalse(thread.title_pending)
        self.assertEqual(thread.title_source, "manual")

    def test_ai_title_command_timeout_terminates_process_group(self) -> None:
        class TimeoutProcess:
            pid = 1234
            args = ["codex"]
            returncode = None

            def __init__(self) -> None:
                self.input_text = ""
                self.wait_timeout = None

            def communicate(self, *, input: str | None = None, timeout: int | None = None) -> tuple[str, str]:
                self.input_text = input or ""
                raise subprocess.TimeoutExpired(self.args, timeout)

            def poll(self) -> int | None:
                return self.returncode

            def wait(self, *, timeout: float | None = None) -> int:
                self.wait_timeout = timeout
                self.returncode = -signal.SIGTERM
                return self.returncode

            def terminate(self) -> None:
                self.returncode = -signal.SIGTERM

            def kill(self) -> None:
                self.returncode = -signal.SIGKILL

        process = TimeoutProcess()

        with patch("core.runtime.thread_title_jobs.subprocess.Popen", return_value=process) as popen, patch(
            "core.runtime.thread_title_jobs.os.killpg"
        ) as killpg:
            with self.assertRaises(ThreadTitleGenerationError):
                _run_codex_title_command(["codex", "exec"], prompt="title prompt", timeout_seconds=3)

        self.assertEqual(process.input_text, "title prompt")
        self.assertEqual(process.wait_timeout, 1.0)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(1234, signal.SIGTERM)

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

    def test_late_backfill_prefers_first_meaningful_turn(self) -> None:
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
        self.assertEqual(updated.title, "Analisi Report Vendite")

    def test_reconcile_backfills_default_thread_title_from_stored_turn(self) -> None:
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

        self.assertEqual(reconciled.title, "Verifica Test Nomenclatura Contestuale Chat")

    def test_reconcile_backfills_title_from_queued_event_references(self) -> None:
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

        self.assertEqual(reconciled.title, "Analisi Budget 2026")

    def test_reconcile_uses_first_turn_when_older_queued_event_is_missing(self) -> None:
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

        self.assertEqual(reconciled.title, "Test Nomenclatura Contestuale Chat")


if __name__ == "__main__":
    unittest.main()
