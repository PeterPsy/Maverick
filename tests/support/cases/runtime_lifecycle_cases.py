"""Tests for runtime-domain behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import tempfile
from threading import Barrier, Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.api.runtime_cleanup import RuntimeCleanupError, _delete_runtime_root, cleanup_runtime_session
from core.runtime.service import (
    build_runtime_routing,
    create_child_runtime_session,
    create_runtime_process,
    create_runtime_session,
    queue_runtime_turn,
    queue_runtime_turn_if_client_message_absent,
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
from core.runtime.client_message_claims import CLIENT_MESSAGE_CLAIM_LEASE_SECONDS
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
from core.runtime.turn_submission import _complete_output_text, _missing_final_suffix, release_idle_runtime_processes, submit_runtime_turn_async
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

    def make_store_with_client_messages(self, client_messages: FakeCollection | None = None) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                client_messages=client_messages or FakeCollection(),
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
                client_messages=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="client_messages.json"),
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

    def test_async_turn_submit_queues_before_provider_resolution_and_reuses_client_message_id(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            store,
            session_id="sess-fast-ack",
            workspace_id="acme",
            agent_id="agent-1",
            start_path=repo_root,
        )
        created_threads: list[object] = []

        class DeferredThread:
            def __init__(self, *, target, name, daemon) -> None:
                self.target = target
                created_threads.append(self)

            def start(self) -> None:
                return None

        resolve_backend = Mock(return_value=(SimpleNamespace(provider_id="fake-provider"), None, SimpleNamespace()))
        worker_globals = submit_runtime_turn_async.__globals__
        with patch.dict(worker_globals, {"Thread": DeferredThread, "resolve_runtime_backend_for_session": resolve_backend}), patch(
            "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
        ):
            first_turn, first_events = submit_runtime_turn_async(
                SimpleNamespace(
                    runtime_store=store,
                    provider_store=SimpleNamespace(),
                    runtime_event_bus=None,
                    runtime_thread_event_bus=None,
                ),
                session=session,
                input_text="fast ack",
                client_message_id="client-fast-ack",
            )
            second_turn, second_events = submit_runtime_turn_async(
                SimpleNamespace(
                    runtime_store=store,
                    provider_store=SimpleNamespace(),
                    runtime_event_bus=None,
                    runtime_thread_event_bus=None,
                ),
                session=session,
                input_text="fast ack retry",
                client_message_id="client-fast-ack",
            )

        resolve_backend.assert_not_called()
        self.assertEqual(first_turn.turn_id, second_turn.turn_id)
        self.assertEqual(first_turn.client_message_id, "client-fast-ack")
        self.assertEqual(len(created_threads), 1)
        self.assertEqual(first_events[0].event_type, "runtime.turn.queued")
        self.assertEqual(second_events[0].event_type, "runtime.turn.queued")
        self.assertEqual(first_events[0].payload["provider_id"], "codex")

    def test_json_runtime_turn_client_message_insert_is_atomic(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_json_store(repo_root)
        create_runtime_session(
            store,
            session_id="sess-client-atomic",
            workspace_id="acme",
            agent_id="agent-1",
            start_path=repo_root,
        )
        barrier = Barrier(6)
        results: list[tuple[str, bool]] = []
        errors: list[BaseException] = []

        def queue_once(index: int) -> None:
            try:
                barrier.wait(timeout=2)
                turn, created = queue_runtime_turn_if_client_message_absent(
                    store,
                    turn_id=f"turn-client-atomic-{index}",
                    session_id="sess-client-atomic",
                    input_text=f"hello {index}",
                    client_message_id="client-atomic",
                )
                results.append((turn.turn_id, created))
            except BaseException as error:
                errors.append(error)

        threads = [Thread(target=queue_once, args=(index,)) for index in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)

        if errors:
            raise errors[0]
        self.assertEqual(len(results), 6)
        self.assertEqual(sum(1 for _turn_id, created in results if created), 1)
        self.assertEqual(len({turn_id for turn_id, _created in results}), 1)
        turns = store.list_turns("sess-client-atomic")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].client_message_id, "client-atomic")

    def test_client_message_claim_reclaims_expired_orphan(self) -> None:
        store = self.make_store_with_client_messages()
        now = datetime(2026, 1, 1, tzinfo=UTC)

        first_claim, first_created = store.claim_client_message_id(
            workspace_id="acme",
            client_message_id="client-orphan",
            session_id="sess-first",
            turn_id="turn-first",
            now=now,
        )
        pending_claim, pending_created = store.claim_client_message_id(
            workspace_id="acme",
            client_message_id="client-orphan",
            session_id="sess-pending",
            turn_id="turn-pending",
            now=now + timedelta(seconds=1),
        )
        reclaimed_claim, reclaimed_created = store.claim_client_message_id(
            workspace_id="acme",
            client_message_id="client-orphan",
            session_id="sess-reclaimed",
            turn_id="turn-reclaimed",
            now=now + timedelta(seconds=CLIENT_MESSAGE_CLAIM_LEASE_SECONDS + 1),
        )

        self.assertTrue(first_created)
        self.assertEqual(first_claim.status, "claimed")
        self.assertEqual(first_claim.lease_expires_at, now + timedelta(seconds=CLIENT_MESSAGE_CLAIM_LEASE_SECONDS))
        self.assertFalse(pending_created)
        self.assertEqual(pending_claim.session_id, "sess-first")
        self.assertTrue(reclaimed_created)
        self.assertEqual(reclaimed_claim.session_id, "sess-reclaimed")
        self.assertEqual(reclaimed_claim.turn_id, "turn-reclaimed")

    def test_client_message_claim_keeps_expired_claim_with_persisted_turn(self) -> None:
        store = self.make_store_with_client_messages()
        repo_root = self.make_repo_root()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        create_runtime_session(
            store,
            session_id="sess-claimed-turn",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        first_claim, first_created = store.claim_client_message_id(
            workspace_id="acme",
            client_message_id="client-persisted",
            session_id="sess-claimed-turn",
            turn_id="turn-claimed",
            now=now,
        )
        queue_runtime_turn(
            store,
            turn_id="turn-claimed",
            session_id="sess-claimed-turn",
            input_text="persisted",
            client_message_id="client-persisted",
            now=now,
        )

        retry_claim, retry_created = store.claim_client_message_id(
            workspace_id="acme",
            client_message_id="client-persisted",
            session_id="sess-new",
            turn_id="turn-new",
            now=now + timedelta(seconds=CLIENT_MESSAGE_CLAIM_LEASE_SECONDS + 1),
        )

        self.assertTrue(first_created)
        self.assertEqual(first_claim.session_id, "sess-claimed-turn")
        self.assertFalse(retry_created)
        self.assertEqual(retry_claim.session_id, "sess-claimed-turn")
        self.assertEqual(retry_claim.turn_id, "turn-claimed")

    def test_async_turn_records_worker_and_provider_dispatch_lifecycle(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            store,
            session_id="sess-provider-lifecycle",
            workspace_id="acme",
            agent_id="agent-1",
            start_path=repo_root,
        )

        class ImmediateThread:
            def __init__(self, *, target, name, daemon) -> None:
                self.target = target

            def start(self) -> None:
                self.target()

        def fake_execute_runtime_turn(**kwargs):
            kwargs["on_provider_turn_start_sent"]({"provider_thread_id": "thread-provider"})
            kwargs["on_provider_accepted"]({"provider_thread_id": "thread-provider", "provider_turn_id": "turn-provider"})
            return SimpleNamespace(output_text="", exit_code=0)

        worker_globals = submit_runtime_turn_async.__globals__
        with patch.dict(
            worker_globals,
            {
                "Thread": ImmediateThread,
                "resolve_runtime_backend_for_session": Mock(
                    return_value=(SimpleNamespace(provider_id="fake-provider"), None, SimpleNamespace())
                ),
                "_build_launch_spec_for_execution": Mock(return_value=SimpleNamespace()),
                "execute_runtime_turn": fake_execute_runtime_turn,
                "release_idle_runtime_processes": Mock(return_value=0),
            },
        ), patch("core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"):
            turn, _events = submit_runtime_turn_async(
                SimpleNamespace(
                    runtime_store=store,
                    provider_store=SimpleNamespace(),
                    runtime_event_bus=None,
                    runtime_thread_event_bus=None,
                    repository_root=repo_root,
                ),
                session=session,
                input_text="lifecycle",
                client_message_id="client-lifecycle",
            )

        event_types = [event.event_type for event in store.list_events(session.session_id) if event.turn_id == turn.turn_id]
        self.assertIn("runtime.turn.worker_started", event_types)
        self.assertIn("runtime.provider.dispatching", event_types)
        self.assertIn("runtime.provider.turn_start_sent", event_types)
        self.assertIn("runtime.provider.accepted", event_types)
        self.assertLess(event_types.index("runtime.provider.turn_start_sent"), event_types.index("runtime.provider.accepted"))
        accepted = next(event for event in store.list_events(session.session_id) if event.event_type == "runtime.provider.accepted")
        self.assertEqual(accepted.payload["provider_id"], "fake-provider")
        self.assertEqual(accepted.payload["provider_thread_id"], "thread-provider")
        self.assertEqual(accepted.payload["provider_turn_id"], "turn-provider")
        self.assertEqual(accepted.payload["elapsed_from"], "provider_turn_start_sent")
        self.assertIn("turn_start_to_ack_ms", accepted.payload)

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

        latest_page = store.list_event_page("sess-bounded-events", limit=MAX_RUNTIME_EVENTS_PER_SESSION)
        self.assertTrue(latest_page.has_more_before)
        self.assertEqual(len(latest_page.events), MAX_RUNTIME_EVENTS_PER_SESSION)
        self.assertEqual(latest_page.oldest_event_id, "evt-0005")

        older_page = store.list_event_page(
            "sess-bounded-events",
            before_event_id=latest_page.oldest_event_id,
            limit=10,
        )
        self.assertFalse(older_page.has_more_before)
        self.assertEqual([event.event_id for event in older_page.events], ["evt-0000", "evt-0001", "evt-0002", "evt-0003", "evt-0004"])

        missing_cursor_page = store.list_event_page(
            "sess-bounded-events",
            before_event_id="evt-missing",
            limit=10,
        )
        self.assertFalse(missing_cursor_page.has_more_before)
        self.assertEqual(missing_cursor_page.events, [])

        history_root = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-bounded-events" / "events-history"
        self.assertTrue(history_root.is_dir())
        self.assertGreaterEqual(len(list(history_root.glob("*.json"))), 2)

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
                idle_ttl_seconds=0,
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

    def test_idle_runtime_process_reap_waits_for_ttl(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-idle-process-ttl",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        turn = queue_runtime_turn(store, turn_id="turn-terminal-ttl", session_id="sess-idle-process-ttl", input_text="done", now=now)
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="active", now=now)
        transition_runtime_turn(store, turn_id=turn.turn_id, target_status="completed", now=now)
        process = subprocess.Popen(["sleep", "30"], start_new_session=True)
        try:
            register_runtime_process("sess-idle-process-ttl", process)
            terminated = release_idle_runtime_processes(
                SimpleNamespace(runtime_store=store, runtime_event_bus=None),
                session_id="sess-idle-process-ttl",
                provider_id="codex",
                reason="test_idle_ttl",
                idle_ttl_seconds=0.05,
            )

            self.assertEqual(terminated, 0)
            self.assertIsNone(process.poll())
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIsNotNone(process.poll())
            deadline = time.monotonic() + 2
            while "runtime.process.idle_reaped" not in [event.event_type for event in store.list_events("sess-idle-process-ttl")] and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIn("runtime.process.idle_reaped", [event.event_type for event in store.list_events("sess-idle-process-ttl")])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)

    def test_async_worker_failure_reaps_idle_processes_immediately(self) -> None:
        store = self.make_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        session = create_runtime_session(
            store,
            session_id="sess-async-failure",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        class ImmediateThread:
            def __init__(self, *, target, name, daemon) -> None:
                self.target = target

            def start(self) -> None:
                self.target()

        release_mock = Mock(return_value=0)
        worker_globals = submit_runtime_turn_async.__globals__
        with patch.dict(
            worker_globals,
            {
                "Thread": ImmediateThread,
                "execute_runtime_turn": Mock(side_effect=RuntimeError("provider failed")),
                "resolve_runtime_backend_for_session": Mock(
                    return_value=(SimpleNamespace(provider_id="fake-provider"), None, SimpleNamespace())
                ),
                "_build_launch_spec_for_execution": Mock(return_value=SimpleNamespace()),
                "release_idle_runtime_processes": release_mock,
            },
        ):
            turn, _events = submit_runtime_turn_async(
                SimpleNamespace(runtime_store=store, provider_store=SimpleNamespace(), runtime_event_bus=None),
                session=session,
                input_text="fail",
            )

        self.assertEqual(store.get_turn(turn.turn_id).status, "failed")
        self.assertEqual(release_mock.call_args.kwargs["reason"], "async_turn_failed")
        self.assertEqual(release_mock.call_args.kwargs["idle_ttl_seconds"], 0)

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

    def test_json_session_cleanup_keeps_same_client_message_claim_in_other_workspace(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_json_store(repo_root)
        now = datetime.now(tz=UTC)
        create_runtime_session(
            store,
            session_id="sess-json-claim-delete",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        other_claim, other_created = store.claim_client_message_id(
            workspace_id="aaa",
            client_message_id="client-shared",
            session_id="sess-other",
            turn_id="turn-other",
            now=now,
        )
        acme_claim, acme_created = store.claim_client_message_id(
            workspace_id="acme",
            client_message_id="client-shared",
            session_id="sess-json-claim-delete",
            turn_id="turn-acme",
            now=now,
        )

        deleted = store.delete_session_records("sess-json-claim-delete")

        self.assertTrue(other_created)
        self.assertTrue(acme_created)
        self.assertEqual(other_claim.workspace_id, "aaa")
        self.assertEqual(acme_claim.workspace_id, "acme")
        self.assertEqual(deleted["client_messages"], 1)
        self.assertIsNotNone(
            store.collections.client_messages.find_one(
                {"workspace_id": "aaa", "client_message_id": "client-shared", "session_id": "sess-other"}
            )
        )
        self.assertIsNone(
            store.collections.client_messages.find_one(
                {"workspace_id": "acme", "client_message_id": "client-shared", "session_id": "sess-json-claim-delete"}
            )
        )


if __name__ == "__main__":
    unittest.main()
