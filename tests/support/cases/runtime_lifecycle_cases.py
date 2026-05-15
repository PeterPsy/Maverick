"""Tests for runtime-domain behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest

from core.api.runtime_cleanup import RuntimeCleanupError, _delete_runtime_root, cleanup_runtime_session
from core.runtime.service import (
    build_runtime_routing,
    create_child_runtime_session,
    create_runtime_process,
    create_runtime_session,
    queue_runtime_turn,
    record_runtime_event,
    reconcile_runtime_session_policy,
    transition_runtime_process,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.process_control import register_runtime_process
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_thread import RuntimeThreadRecord
from core.runtime.runtime_threads import (
    create_runtime_thread,
    list_runtime_threads,
    mark_runtime_thread_completed_response_read,
    mark_runtime_thread_response_completed,
    mark_runtime_thread_user_message,
    thread_payload,
    update_runtime_thread,
    update_runtime_thread_availability,
)
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.session_termination import terminate_runtime_session
from core.runtime.store import MAX_RUNTIME_EVENTS_PER_SESSION, RuntimeDocumentStore, RuntimeCollections
from core.runtime.thread_catalog_events import mark_thread_response_completed, mark_thread_user_message_queued, set_thread_availability
from core.runtime.turn_submission import _complete_output_text, _missing_final_suffix, release_idle_runtime_processes
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from core.shared.json_file_collection import JsonFileCollection
from core.workspaces.service import default_workspace_governance
from tests.support.collections import FakeCollection


class PruneReadErrorCollection(FakeCollection):
    """Collection that accepts writes but fails retention reads."""

    def find(self, query: dict) -> list[dict]:
        raise ValueError("Unable to read malformed JSON collection")


class CapturingThreadEventBus:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, *, workspace_id: str, event: dict) -> None:
        self.events.append({"workspace_id": workspace_id, **event})


class RuntimeLifecycleTestCase(unittest.TestCase):
    """Verify workspace-aware runtime routing and lifecycle records."""

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

    def make_json_store(self, repo_root: Path) -> RuntimeDocumentStore:
        state_root = repo_root / ".maverick" / "local-state" / "runtime"
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=RuntimeSessionJsonCollection(start_path=repo_root, filename="session.json"),
                turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
                events=RuntimeEventJsonCollection(start_path=repo_root),
                processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
                states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
                threads=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="threads.json"),
                api_tokens=JsonFileCollection(state_root / "api_tokens.json"),
            )
        )

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        (repo_root / "core").mkdir(parents=True)
        (repo_root / "apps").mkdir()
        (repo_root / "workspaces").mkdir()
        (repo_root / "docs" / "architecture").mkdir(parents=True)
        (repo_root / "scripts").mkdir()
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def test_create_runtime_session_persists_authoritative_workspace_and_state(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)

        session = create_runtime_session(
            store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            system_prompt="You are a focused test agent.",
            skill_ids=["agents-ops"],
            skill_catalog_app_id="custom-skills",
            source_app_id="source-app",
            now=now,
            start_path=repo_root,
        )

        self.assertEqual(session.workspace_id, "acme")
        self.assertEqual(session.agent_id, "agent-1")
        self.assertEqual(session.effective_mode, "sandbox")
        self.assertEqual(Path(session.workspace_root), repo_root / "workspaces" / "acme")
        self.assertEqual(Path(session.workdir), repo_root / "workspaces" / "acme")
        self.assertEqual(Path(session.runtime_root), repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1")
        self.assertEqual(session.system_prompt, "You are a focused test agent.")
        self.assertEqual(session.skill_ids, ["agents-ops"])
        self.assertEqual(session.skill_catalog_app_id, "custom-skills")
        self.assertEqual(session.source_app_id, "source-app")
        self.assertIsNone(session.provider_thread_id)
        self.assertEqual(store.get_state("sess-1").session_status, "created")

    def test_runtime_policy_reconcile_preserves_session_partitioned_root(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            store,
            session_id="sess-reconcile",
            workspace_id="acme",
            agent_id="test-agent",
            start_path=repo_root,
        )
        drifted = store.save_session(
            replace(
                session,
                runtime_root=str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "drifted-session"),
            )
        )

        reconciled = reconcile_runtime_session_policy(
            store,
            drifted,
            governance=default_workspace_governance("acme"),
            platform_allows_full_access=False,
            start_path=repo_root,
        )

        self.assertEqual(
            Path(reconciled.runtime_root),
            repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-reconcile",
        )

    def test_runtime_cleanup_refuses_to_delete_unexpected_runtime_root(self) -> None:
        repo_root = self.make_repo_root()
        unsafe_root = repo_root / ".maverick" / "local-state"
        unsafe_root.mkdir(parents=True, exist_ok=True)
        marker = unsafe_root / "do-not-delete.txt"
        marker.write_text("keep\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeCleanupError, "Refusing to delete runtime root"):
            _delete_runtime_root(
                unsafe_root,
                workspace_id="acme",
                session_id="sess-1",
                start_path=repo_root,
            )

        self.assertTrue(marker.is_file())

    def test_runtime_cleanup_deletes_canonical_root_when_session_record_drifted(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_json_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="sess-drift-cleanup",
            workspace_id="acme",
            agent_id="test-agent",
            start_path=repo_root,
        )
        canonical_root = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-drift-cleanup"
        drift_root = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "drifted-session"
        (canonical_root / "codex-home").mkdir(parents=True)
        (canonical_root / "codex-home" / "marker.txt").write_text("delete me\n", encoding="utf-8")
        drift_root.mkdir(parents=True)
        (drift_root / "shared.txt").write_text("keep me\n", encoding="utf-8")
        store.save_session(replace(session, runtime_root=str(drift_root)))
        state = SimpleNamespace(
            runtime_store=store,
            app_store=SimpleNamespace(list_workspace_app_bindings=lambda workspace_id: []),
            runtime_event_bus=None,
            observability_store=None,
            repository_root=repo_root,
        )

        cleanup = cleanup_runtime_session(
            state,
            session_id=session.session_id,
            reason="test_drift_cleanup",
            start_path=repo_root,
        )

        self.assertTrue(cleanup["runtime_root_deleted"])
        self.assertFalse(canonical_root.exists())
        self.assertTrue((drift_root / "shared.txt").is_file())

    def test_runtime_event_store_keeps_only_latest_500_events_per_session(self) -> None:
        store = self.make_json_store(self.make_repo_root())
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-retention",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=store.collections.events.start_path,
        )

        for index in range(750):
            record_runtime_event(
                store,
                event_id=f"event-{index:03d}",
                session_id="sess-retention",
                plane="runtime",
                event_type="runtime.output.delta",
                payload={"index": index},
                now=now.replace(microsecond=index),
            )

        events = store.list_events("sess-retention")
        event_ids = [event.event_id for event in events]

        self.assertEqual(len(events), 500)
        self.assertEqual(event_ids[0], "event-250")
        self.assertEqual(event_ids[-1], "event-749")
        self.assertNotIn("event-000", event_ids)

    def test_runtime_event_pruning_does_not_fail_event_save_when_event_file_is_malformed(self) -> None:
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=PruneReadErrorCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        now = datetime.now(tz=UTC)
        record = RuntimeEventRecord(
            event_id="evt-1",
            workspace_id="acme",
            session_id="sess-malformed-events",
            plane="runtime",
            event_type="runtime.output.delta",
            turn_id=None,
            process_id=None,
            payload={"text": "hello"},
            created_at=now,
        )

        self.assertIs(store.save_event(record), record)
        self.assertEqual(store.collections.events.documents[0]["event_id"], "evt-1")

    def test_runtime_turn_lifecycle_updates_runtime_state(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        queued = queue_runtime_turn(store, turn_id="turn-1", session_id="sess-1", input_text="do work", now=now)
        active = transition_runtime_turn(store, turn_id="turn-1", target_status="active", now=now)
        completed = transition_runtime_turn(store, turn_id="turn-1", target_status="completed", now=now)

        self.assertEqual(queued.status, "queued")
        self.assertEqual(active.status, "active")
        self.assertEqual(completed.status, "completed")
        self.assertIsNone(store.get_state("sess-1").current_turn_id)
        self.assertIsNone(store.get_state("sess-1").turn_status)

    def test_runtime_event_is_structured_and_attributed(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        event = record_runtime_event(
            store,
            event_id="evt-1",
            session_id="sess-1",
            plane="turn",
            event_type="turn.started",
            payload={"source": "runtime"},
            turn_id="turn-1",
            now=now,
        )

        self.assertEqual(event.workspace_id, "acme")
        self.assertEqual(event.plane, "turn")
        self.assertEqual(store.list_events("sess-1")[0].event_type, "turn.started")

    def test_runtime_final_output_is_empty_when_stream_already_emitted_everything(self) -> None:
        self.assertEqual(_missing_final_suffix("hello from codex", "hello from codex"), "")

    def test_runtime_final_output_keeps_only_missing_stream_suffix(self) -> None:
        self.assertEqual(_missing_final_suffix("hello from codex", "hello"), "from codex")

    def test_runtime_final_output_deduplicates_whitespace_only_stream_difference(self) -> None:
        self.assertEqual(_missing_final_suffix("hello\n\nfrom codex", "hello from codex"), "")

    def test_runtime_app_output_uses_streamed_text_when_final_event_is_empty(self) -> None:
        self.assertEqual(_complete_output_text("", "reviewer handoff"), "reviewer handoff")

    def test_runtime_app_output_keeps_full_provider_text_when_stream_was_duplicate(self) -> None:
        self.assertEqual(_complete_output_text("hello from codex", "hello from codex"), "hello from codex")

    def test_json_runtime_store_keeps_history_across_bootstrap_instances(self) -> None:
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        first_store = self.make_json_store(repo_root)

        create_runtime_session(first_store, session_id="sess-1", workspace_id="acme", agent_id="runtime-agent", now=now, start_path=repo_root)
        queue_runtime_turn(first_store, turn_id="turn-1", session_id="sess-1", input_text="hello", now=now)
        record_runtime_event(
            first_store,
            event_id="evt-1",
            session_id="sess-1",
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"input_text": "hello"},
            turn_id="turn-1",
            now=now,
        )

        second_store = self.make_json_store(repo_root)

        self.assertEqual(second_store.get_session("sess-1").workspace_id, "acme")
        self.assertEqual(second_store.list_turns("sess-1")[0].input_text, "hello")
        self.assertEqual(second_store.list_events("sess-1")[0].event_type, "runtime.turn.queued")
        self.assertEqual(second_store.get_state("sess-1").session_status, "created")
        session_root = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1"
        self.assertTrue((session_root / "session.json").is_file())
        self.assertTrue((session_root / "turns.json").is_file())
        self.assertTrue((session_root / "events.json").is_file())
        self.assertTrue((session_root / "state.json").is_file())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "sessions.json").exists())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "turns.json").exists())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "events.json").exists())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "states.json").exists())

    def test_json_event_history_is_bounded_per_session_partition(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_json_store(repo_root)
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-bounded-events",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        for index in range(MAX_RUNTIME_EVENTS_PER_SESSION + 5):
            record_runtime_event(
                store,
                event_id=f"evt-{index:04d}",
                session_id="sess-bounded-events",
                plane="runtime",
                event_type="runtime.output.delta",
                payload={"text": str(index)},
                now=now,
            )

        events = store.list_events("sess-bounded-events")

        self.assertEqual(len(events), MAX_RUNTIME_EVENTS_PER_SESSION)
        self.assertEqual(events[0].event_id, "evt-0005")
        self.assertEqual(events[-1].event_id, f"evt-{MAX_RUNTIME_EVENTS_PER_SESSION + 4:04d}")

    def test_workspace_runtime_threads_are_persisted_under_workspace_runtime_root(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_json_store(repo_root)
        now = datetime.now(tz=UTC)

        create_runtime_session(
            store,
            session_id="sess-thread",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        store.save_thread(
            RuntimeThreadRecord(
                thread_id="thread-1",
                workspace_id="acme",
                runtime_session_id="sess-thread",
                title="Runtime chat",
                agent_label="agent-1",
                agent_type_id="",
                agent_role_id="",
                source_app_id="chat",
                system_prompt="",
                project_id=None,
                archived=False,
                availability="free",
                created_at=now,
                updated_at=now,
            )
        )

        second_store = self.make_json_store(repo_root)

        self.assertEqual(second_store.get_thread("thread-1").runtime_session_id, "sess-thread")
        self.assertEqual(second_store.list_threads("acme")[0].thread_id, "thread-1")
        self.assertTrue((repo_root / "workspaces" / "acme" / "runtime" / "threads.json").is_file())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "threads.json").exists())

    def test_runtime_threads_are_ordered_by_latest_user_message_only(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_session(
            store,
            session_id="session-b",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="A",
            now=now,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-b",
            runtime_session_id="session-b",
            title="B",
            now=now + timedelta(minutes=1),
        )

        mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            now=now + timedelta(minutes=2),
        )
        update_runtime_thread(
            store,
            thread_id="thread-b",
            workspace_id="acme",
            updates={"availability": "busy"},
            now=now + timedelta(minutes=3),
        )

        self.assertEqual(
            [thread.thread_id for thread in list_runtime_threads(store, workspace_id="acme")],
            ["thread-a", "thread-b"],
        )

    def test_runtime_thread_list_backfills_latest_user_message_from_turns(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session_a = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        session_b = create_runtime_session(
            store,
            session_id="session-b",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session_a.session_id,
            title="A",
            now=now,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-b",
            runtime_session_id=session_b.session_id,
            title="B",
            now=now + timedelta(minutes=3),
        )
        latest_turn = queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id=session_a.session_id,
            input_text="newer work",
            now=now + timedelta(minutes=5),
        )

        threads = list_runtime_threads(store, workspace_id="acme")

        self.assertEqual([thread.thread_id for thread in threads], ["thread-a", "thread-b"])
        self.assertEqual(threads[0].last_user_message_at, latest_turn.created_at)

    def test_runtime_thread_user_message_updates_recency_and_busyness_together(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="A",
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id="session-a",
            input_text="hello",
            now=now + timedelta(seconds=30),
        )

        queued_at = now + timedelta(minutes=1)
        queued = mark_runtime_thread_user_message(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            now=queued_at,
        )

        self.assertIsNotNone(queued)
        self.assertEqual(queued.availability, "queued")
        self.assertEqual(queued.last_user_message_at, queued_at)

        free = update_runtime_thread_availability(
            store,
            workspace_id="acme",
            runtime_session_id="session-a",
            availability="free",
            now=queued_at + timedelta(minutes=1),
        )

        self.assertIsNotNone(free)
        self.assertEqual(free.availability, "free")
        self.assertEqual(free.last_user_message_at, queued_at)

    def test_runtime_thread_completed_response_tracks_unread_per_user(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session.session_id,
            title="A",
            now=now,
        )
        turn = queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id=session.session_id,
            input_text="hello",
            now=now + timedelta(seconds=1),
        )
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active", now=now + timedelta(seconds=2))
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="completed", now=now + timedelta(seconds=3))
        completed_at = now + timedelta(seconds=4)

        completed = mark_runtime_thread_response_completed(
            store,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            turn_id=turn.turn_id,
            now=completed_at,
        )

        self.assertIsNotNone(completed)
        assert completed is not None
        self.assertEqual(completed.availability, "free")
        self.assertEqual(completed.last_completed_response_at, completed_at)
        self.assertEqual(completed.last_completed_turn_id, turn.turn_id)
        self.assertTrue(thread_payload(completed, viewer_user_id="user-a")["has_unread_completed_response"])
        self.assertNotIn("completed_response_read_at_by_user_id", thread_payload(completed, viewer_user_id="user-a"))

        read = mark_runtime_thread_completed_response_read(
            store,
            thread_id=completed.thread_id,
            workspace_id="acme",
            user_id="user-a",
            now=completed_at + timedelta(seconds=1),
        )

        self.assertIsNotNone(read)
        assert read is not None
        self.assertFalse(thread_payload(read, viewer_user_id="user-a")["has_unread_completed_response"])
        self.assertTrue(thread_payload(read, viewer_user_id="user-b")["has_unread_completed_response"])

    def test_runtime_thread_list_reconciles_stale_busyness_from_turns(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session.session_id,
            title="A",
            now=now,
        )
        update_runtime_thread_availability(
            store,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            availability="active",
            now=now + timedelta(minutes=1),
        )

        self.assertEqual(list_runtime_threads(store, workspace_id="acme")[0].availability, "free")

        turn = queue_runtime_turn(store, turn_id="turn-a", session_id=session.session_id, input_text="hello")
        self.assertEqual(list_runtime_threads(store, workspace_id="acme")[0].availability, "queued")

        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active")
        self.assertEqual(list_runtime_threads(store, workspace_id="acme")[0].availability, "active")

        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="completed")
        self.assertEqual(list_runtime_threads(store, workspace_id="acme")[0].availability, "free")

    def test_thread_catalog_event_creates_missing_thread_before_marking_busy(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        event_bus = CapturingThreadEventBus()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        turn = queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id=session.session_id,
            input_text="work on this",
            now=now + timedelta(seconds=1),
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=event_bus)

        thread = mark_thread_user_message_queued(
            state,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            now=turn.created_at,
        )

        self.assertIsNotNone(thread)
        assert thread is not None
        self.assertEqual(thread.thread_id, session.session_id)
        self.assertEqual(thread.title, "Work On This")
        self.assertEqual(thread.availability, "queued")
        self.assertEqual(thread.last_user_message_at, turn.created_at)
        self.assertEqual(event_bus.events[-1]["thread"]["availability"], "queued")

    def test_thread_catalog_free_update_reconciles_other_queued_turns(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        event_bus = CapturingThreadEventBus()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        first = queue_runtime_turn(store, turn_id="turn-a", session_id=session.session_id, input_text="first", now=now)
        second = queue_runtime_turn(store, turn_id="turn-b", session_id=session.session_id, input_text="second", now=now + timedelta(seconds=1))
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session.session_id,
            title="A",
            now=now,
        )
        transition_runtime_turn(store, turn_id=first.turn_id, target_status="active")
        transition_runtime_turn(store, turn_id=first.turn_id, target_status="completed")
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=event_bus)

        updated = set_thread_availability(
            state,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            availability="free",
            now=now + timedelta(seconds=2),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(second.status, "queued")
        self.assertEqual(updated.availability, "queued")
        self.assertEqual(event_bus.events[-1]["thread"]["availability"], "queued")

    def test_thread_catalog_completed_response_publishes_read_needed_metadata(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        event_bus = CapturingThreadEventBus()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        turn = queue_runtime_turn(store, turn_id="turn-a", session_id=session.session_id, input_text="first", now=now)
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active", now=now + timedelta(seconds=1))
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="completed", now=now + timedelta(seconds=2))
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session.session_id,
            title="A",
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=event_bus)

        updated = mark_thread_response_completed(
            state,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            turn_id=turn.turn_id,
            now=now + timedelta(seconds=3),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.last_completed_turn_id, turn.turn_id)
        self.assertEqual(event_bus.events[-1]["thread"]["last_completed_turn_id"], turn.turn_id)
        self.assertIn("has_unread_completed_response", event_bus.events[-1]["thread"])

    def test_thread_catalog_event_preserves_user_renamed_title(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        event_bus = CapturingThreadEventBus()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-a",
            session_id=session.session_id,
            input_text="first prompt should not replace title",
            now=now + timedelta(seconds=1),
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session.session_id,
            title="Original title",
            now=now,
        )
        update_runtime_thread(
            store,
            thread_id="thread-a",
            workspace_id="acme",
            updates={"title": "User renamed title"},
            now=now + timedelta(seconds=2),
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=event_bus)

        updated = set_thread_availability(
            state,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            availability="queued",
            now=now + timedelta(seconds=3),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "User renamed title")
        self.assertEqual(store.get_thread("thread-a").title, "User renamed title")
        self.assertEqual(event_bus.events[-1]["thread"]["title"], "User renamed title")

    def test_thread_catalog_user_message_uses_active_availability_without_downgrade(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        event_bus = CapturingThreadEventBus()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        session = create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        first = queue_runtime_turn(store, turn_id="turn-a", session_id=session.session_id, input_text="first", now=now)
        transition_runtime_turn(store, turn_id=first.turn_id, target_status="active")
        second = queue_runtime_turn(
            store,
            turn_id="turn-b",
            session_id=session.session_id,
            input_text="second",
            now=now + timedelta(seconds=1),
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id=session.session_id,
            title="A",
            now=now,
        )
        state = SimpleNamespace(runtime_store=store, runtime_thread_event_bus=event_bus)

        updated = mark_thread_user_message_queued(
            state,
            workspace_id="acme",
            runtime_session_id=session.session_id,
            now=second.created_at,
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.availability, "active")
        self.assertEqual(store.get_thread("thread-a").availability, "active")
        self.assertEqual(event_bus.events[-1]["thread"]["availability"], "active")

    def test_thread_patch_does_not_mutate_core_owned_availability(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime(2026, 4, 19, 10, 0, tzinfo=UTC)
        create_runtime_session(
            store,
            session_id="session-a",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        create_runtime_thread(
            store,
            workspace_id="acme",
            thread_id="thread-a",
            runtime_session_id="session-a",
            title="A",
            now=now,
        )

        updated = update_runtime_thread(
            store,
            thread_id="thread-a",
            workspace_id="acme",
            updates={"availability": "active"},
            now=now + timedelta(minutes=1),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.availability, "free")
        self.assertEqual(updated.updated_at, now)

    def test_runtime_session_collection_rejects_non_array_payload(self) -> None:
        repo_root = self.make_repo_root()
        path = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-bad" / "turns.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"turn_id": "turn-1"}\n', encoding="utf-8")
        collection = RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json")

        with self.assertRaisesRegex(ValueError, "must contain a JSON array"):
            collection.find({"workspace_id": "acme", "session_id": "sess-bad"})

    def test_runtime_session_collection_rejects_non_object_items(self) -> None:
        repo_root = self.make_repo_root()
        path = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-bad" / "turns.json"
        path.parent.mkdir(parents=True)
        path.write_text('[{"turn_id": "turn-1"}, "bad"]\n', encoding="utf-8")
        collection = RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json")

        with self.assertRaisesRegex(ValueError, "must contain only JSON objects"):
            collection.find({"workspace_id": "acme", "session_id": "sess-bad"})

    def test_runtime_process_lifecycle_tracks_exit_and_timeout(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        created = create_runtime_process(store, process_id="proc-1", session_id="sess-1", command=["codex", "run"], now=now)
        running = transition_runtime_process(
            store,
            process_id="proc-1",
            target_status="running",
            stdin_open=True,
            stdout_open=True,
            now=now,
        )
        exited = transition_runtime_process(store, process_id="proc-1", target_status="exited", exit_code=0, now=now)

        created_timeout = create_runtime_process(
            store,
            process_id="proc-2",
            session_id="sess-1",
            command=["codex", "run"],
            now=now,
        )
        running_timeout = transition_runtime_process(
            store,
            process_id="proc-2",
            target_status="running",
            stdin_open=True,
            stdout_open=True,
            now=now,
        )
        timed_out = transition_runtime_process(
            store,
            process_id="proc-2",
            target_status="timed-out",
            failure_reason="watchdog timeout",
            now=now,
        )

        self.assertEqual(created.status, "created")
        self.assertEqual(running.status, "running")
        self.assertTrue(running.stdin_open)
        self.assertEqual(exited.exit_code, 0)
        self.assertEqual(created_timeout.status, "created")
        self.assertEqual(running_timeout.status, "running")
        self.assertEqual(timed_out.status, "timed-out")
        self.assertEqual(timed_out.failure_reason, "watchdog timeout")

    def test_workspace_aware_routing_enforces_sandbox_and_full_access(self) -> None:
        repo_root = self.make_repo_root()
        sandbox_route = build_runtime_routing(
            session_id="sess-sandbox",
            workspace_id="acme",
            agent_id="agent-1",
            requested_mode="full-access",
            start_path=repo_root,
        )
        full_access_route = build_runtime_routing(
            session_id="sess-full-access",
            workspace_id="default",
            agent_id="agent-ops",
            requested_mode="full-access",
            governance=default_workspace_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        default_route = build_runtime_routing(
            session_id="sess-default",
            workspace_id="default",
            agent_id="agent-ops",
            governance=default_workspace_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        explicit_sandbox_route = build_runtime_routing(
            session_id="sess-explicit-sandbox",
            workspace_id="default",
            agent_id="agent-ops",
            requested_mode="sandbox",
            governance=default_workspace_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )

        self.assertEqual(sandbox_route.effective_mode, "sandbox")
        self.assertEqual(sandbox_route.readable_roots, [str(repo_root / "workspaces" / "acme")])
        self.assertEqual(sandbox_route.writable_roots, [str(repo_root / "workspaces" / "acme")])
        self.assertEqual(sandbox_route.runtime_root, str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-sandbox"))
        self.assertFalse(sandbox_route.allows_outside_workspace_root)
        self.assertEqual(full_access_route.effective_mode, "full-access")
        self.assertEqual(full_access_route.readable_roots, ["/"])
        self.assertEqual(full_access_route.writable_roots, ["/"])
        self.assertTrue(full_access_route.allows_outside_workspace_root)
        self.assertEqual(default_route.effective_mode, "full-access")
        self.assertEqual(default_route.readable_roots, ["/"])
        self.assertEqual(default_route.writable_roots, ["/"])
        self.assertTrue(default_route.allows_outside_workspace_root)
        self.assertEqual(explicit_sandbox_route.effective_mode, "sandbox")

    def test_child_runtime_session_inherits_parent_workspace_boundary(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        parent = create_runtime_session(
            store,
            session_id="parent",
            workspace_id="acme",
            agent_id="agent-parent",
            now=now,
            start_path=repo_root,
        )

        child = create_child_runtime_session(
            store,
            parent_session_id="parent",
            child_session_id="child",
            child_agent_id="agent-child",
            now=now,
        )

        self.assertEqual(child.workspace_id, parent.workspace_id)
        self.assertEqual(child.workspace_root, parent.workspace_root)
        self.assertEqual(child.workdir, parent.workdir)
        self.assertEqual(Path(child.runtime_root), Path(parent.runtime_root).parent / "child")
        self.assertNotEqual(child.runtime_root, parent.runtime_root)
        self.assertEqual(child.effective_mode, parent.effective_mode)

    def test_runtime_session_transition_updates_state(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        running = transition_runtime_session(store, session_id="sess-1", target_status="running", now=now)
        stopped = transition_runtime_session(
            store,
            session_id="sess-1",
            target_status="stopping",
            forced_stop_reason="shutdown requested",
            now=now,
        )
        final = transition_runtime_session(store, session_id="sess-1", target_status="stopped", now=now)

        self.assertEqual(running.status, "running")
        self.assertEqual(stopped.status, "stopping")
        self.assertEqual(final.status, "stopped")
        self.assertEqual(store.get_state("sess-1").session_status, "stopped")
        self.assertEqual(store.get_state("sess-1").forced_stop_reason, "shutdown requested")

    def test_created_runtime_session_can_be_stopped_and_purged(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-created",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        queue_runtime_turn(store, turn_id="turn-1", session_id="sess-created", input_text="queued", now=now)
        record_runtime_event(
            store,
            event_id="event-1",
            session_id="sess-created",
            plane="session",
            event_type="runtime.session.test",
            payload={},
            now=now,
        )

        termination = terminate_runtime_session(store, session_id="sess-created", reason="cleanup")
        deleted = store.delete_session_records("sess-created")

        self.assertTrue(termination["found"])
        self.assertEqual(deleted["sessions"], 1)
        self.assertEqual(deleted["turns"], 1)
        self.assertEqual(deleted["events"], 2)
        self.assertEqual(store.list_all_sessions(), [])

    def test_idle_runtime_process_is_terminated_after_terminal_turn(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-idle-process",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        turn = queue_runtime_turn(store, turn_id="turn-terminal", session_id="sess-idle-process", input_text="done", now=now)
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active", now=now)
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="completed", now=now)
        process = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            register_runtime_process("sess-idle-process", process)
            terminated = release_idle_runtime_processes(
                SimpleNamespace(runtime_store=store, runtime_event_bus=None),
                session_id="sess-idle-process",
                provider_id="codex",
                reason="test_idle",
            )

            self.assertEqual(terminated, 1)
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIsNotNone(process.poll())
            self.assertIn("runtime.process.idle_reaped", [event.event_type for event in store.list_events("sess-idle-process")])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)

    def test_idle_reaper_keeps_process_for_queued_turn(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-queued-process",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        queue_runtime_turn(store, turn_id="turn-queued", session_id="sess-queued-process", input_text="pending", now=now)
        process = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            register_runtime_process("sess-queued-process", process)
            terminated = release_idle_runtime_processes(
                SimpleNamespace(runtime_store=store, runtime_event_bus=None),
                session_id="sess-queued-process",
                provider_id="codex",
                reason="test_queued",
            )

            self.assertEqual(terminated, 0)
            self.assertIsNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)

    def test_session_partitioned_runtime_files_are_removed_with_runtime_records(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_json_store(repo_root)
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-json-delete",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        record_runtime_event(
            store,
            event_id="event-json-delete",
            session_id="sess-json-delete",
            plane="session",
            event_type="runtime.session.test",
            payload={},
            now=now,
        )
        queue_runtime_turn(store, turn_id="turn-json-delete", session_id="sess-json-delete", input_text="queued", now=now)
        create_runtime_process(store, process_id="proc-json-delete", session_id="sess-json-delete", command=["codex"], now=now)

        session_root = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-json-delete"
        deleted = store.delete_session_records("sess-json-delete")

        self.assertEqual(deleted["events"], 1)
        self.assertEqual(deleted["turns"], 1)
        self.assertEqual(deleted["processes"], 1)
        self.assertEqual(deleted["states"], 1)
        self.assertFalse((session_root / "events.json").exists())
        self.assertFalse((session_root / "turns.json").exists())
        self.assertFalse((session_root / "processes.json").exists())
        self.assertFalse((session_root / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
