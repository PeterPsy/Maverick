"""Tests for Phase 6 runtime-domain behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from core.api.platform_state import _migrate_legacy_runtime_partition
from core.runtime.service import (
    build_runtime_routing,
    create_child_runtime_session,
    create_runtime_process,
    create_runtime_session,
    queue_runtime_turn,
    record_runtime_event,
    transition_runtime_process,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.session_termination import terminate_runtime_session
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.runtime.turn_submission import _missing_final_suffix
from core.shared.json_file_collection import JsonFileCollection
from core.workspaces.service import default_workspace_governance


class FakeCollection:
    """Small in-memory collection for runtime store tests."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    def find(self, query: dict) -> list[dict]:
        return [dict(document) for document in self.documents if all(document.get(key) == value for key, value in query.items())]

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents[index] = {**document, **payload}
                return
        if upsert:
            self.documents.append({**query, **payload})

    def delete_one(self, query: dict) -> None:
        self.documents = [
            document
            for document in self.documents
            if not all(document.get(key) == value for key, value in query.items())
        ]


class Phase6RuntimeTestCase(unittest.TestCase):
    """Verify workspace-aware runtime routing and lifecycle records."""

    def make_store(self) -> MongoRuntimeStore:
        return MongoRuntimeStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
            )
        )

    def make_json_store(self, repo_root: Path) -> MongoRuntimeStore:
        state_root = repo_root / ".maverick" / "local-state" / "runtime"
        return MongoRuntimeStore(
            RuntimeCollections(
                sessions=JsonFileCollection(state_root / "sessions.json"),
                turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
                events=RuntimeEventJsonCollection(start_path=repo_root),
                processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
                states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
            )
        )

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
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
            source_app_id="agents",
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
        self.assertEqual(session.source_app_id, "agents")
        self.assertIsNone(session.provider_thread_id)
        self.assertEqual(store.get_state("sess-1").session_status, "created")

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

    def test_json_runtime_store_keeps_history_across_bootstrap_instances(self) -> None:
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        first_store = self.make_json_store(repo_root)

        create_runtime_session(first_store, session_id="sess-1", workspace_id="acme", agent_id="chat", now=now, start_path=repo_root)
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
        self.assertTrue((session_root / "turns.json").is_file())
        self.assertTrue((session_root / "events.json").is_file())
        self.assertTrue((session_root / "state.json").is_file())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "turns.json").exists())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "events.json").exists())
        self.assertFalse((repo_root / ".maverick" / "local-state" / "runtime" / "states.json").exists())

    def test_legacy_global_turns_are_migrated_into_session_partition(self) -> None:
        repo_root = self.make_repo_root()
        legacy_path = repo_root / ".maverick" / "local-state" / "runtime" / "turns.json"
        JsonFileCollection(legacy_path).update_one(
            {"turn_id": "turn-legacy"},
            {
                "$set": {
                    "turn_id": "turn-legacy",
                    "session_id": "sess-legacy",
                    "workspace_id": "acme",
                    "status": "queued",
                    "input_text": "hello",
                    "created_at": datetime.now(tz=UTC),
                    "updated_at": datetime.now(tz=UTC),
                    "started_at": None,
                    "completed_at": None,
                    "failure_reason": None,
                }
            },
            upsert=True,
        )
        collection = RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json")

        _migrate_legacy_runtime_partition(
            legacy_path=legacy_path,
            collection=collection,
            identity_field="turn_id",
        )

        self.assertEqual(JsonFileCollection(legacy_path).find({}), [])
        self.assertEqual(collection.find_one({"turn_id": "turn-legacy"})["input_text"], "hello")
        self.assertTrue((repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-legacy" / "turns.json").is_file())

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
