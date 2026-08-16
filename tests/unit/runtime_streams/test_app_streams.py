from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.apps import runtime_requests
from core.apps.runtime_root_capabilities import RuntimeRootCapabilityStore
from core.apps.errors import AppHostingError
from core.runtime.app_streams import RuntimeAppStreamError, RuntimeAppStreamRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.service import create_runtime_session, record_runtime_event, transition_runtime_session
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeAppStreamTests(unittest.TestCase):
    def _memory_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                app_streams=FakeCollection(),
                app_stream_events=FakeCollection(),
            )
        )

    def _record(self, *, stream_id: str = "stream-one", key: str = "run-one:attempt-1") -> RuntimeAppStreamRecord:
        now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
        return RuntimeAppStreamRecord(
            stream_id=stream_id,
            workspace_id="default",
            source_app_id="source-app",
            actor_id="user:admin",
            request_id="request-one",
            idempotency_key=key,
            request_fingerprint="f" * 64,
            session_id="",
            turn_id="",
            status="reserving",
            last_sequence=0,
            created_at=now,
            updated_at=now,
        )

    def test_reservation_is_idempotent_and_ownership_is_fail_closed(self) -> None:
        store = self._memory_store()
        first, inserted = store.reserve_app_stream(self._record())
        replay, replay_inserted = store.reserve_app_stream(self._record(stream_id="stream-two"))

        self.assertTrue(inserted)
        self.assertFalse(replay_inserted)
        self.assertEqual(replay.stream_id, first.stream_id)
        with self.assertRaisesRegex(RuntimeAppStreamError, "not_found"):
            store.get_app_stream("stream-one", workspace_id="other", source_app_id="source-app")
        with self.assertRaisesRegex(RuntimeAppStreamError, "idempotency_conflict"):
            store.reserve_app_stream(
                RuntimeAppStreamRecord(**{**self._record(stream_id="stream-three").__dict__, "request_fingerprint": "a" * 64})
            )

    def test_events_are_ordered_sanitized_and_include_real_file_changes(self) -> None:
        repo_root = make_temp_repo_root(self)
        project_root = repo_root / "workspaces/default/data/source-app/project"
        project_root.mkdir(parents=True)
        store = self._memory_store()
        session = create_runtime_session(
            store,
            session_id="session-one",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            requested_mode="sandbox",
            start_path=repo_root,
        )
        session = transition_runtime_session(store, session_id=session.session_id, target_status="running")
        session = store.patch_session_metadata(
            session_id=session.session_id,
            workspace_id="default",
            updates={"workdir": str(project_root)},
        )
        now = datetime(2026, 8, 5, 12, 1, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-one",
                session_id=session.session_id,
                workspace_id="default",
                status="queued",
                input_text="private prompt",
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
                failure_reason=None,
            )
        )
        store.reserve_app_stream(self._record())
        record_runtime_event(
            store,
            event_id="queued",
            session_id=session.session_id,
            turn_id="turn-one",
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"provider_id": "secret-provider"},
            now=now,
        )
        store.bind_app_stream(
            stream_id="stream-one",
            workspace_id="default",
            source_app_id="source-app",
            session_id=session.session_id,
            turn_id="turn-one",
            now=now,
        )
        record_runtime_event(
            store,
            event_id="started",
            session_id=session.session_id,
            turn_id="turn-one",
            plane="turn",
            event_type="runtime.turn.started",
            payload={"provider_id": "secret-provider"},
            now=now,
        )
        record_runtime_event(
            store,
            event_id="delta",
            session_id=session.session_id,
            turn_id="turn-one",
            plane="turn",
            event_type="runtime.output.delta",
            payload={"text": "Creating the design.", "provider_event_type": "provider.raw", "raw": {"secret": True}},
            now=now,
        )
        (project_root / "index.html").write_text("<h1>Created</h1>", encoding="utf-8")
        record_runtime_event(
            store,
            event_id="completed",
            session_id=session.session_id,
            turn_id="turn-one",
            plane="turn",
            event_type="runtime.turn.completed",
            payload={"provider_id": "secret-provider"},
            now=now,
        )

        events = store.read_app_stream_events(
            "stream-one",
            workspace_id="default",
            source_app_id="source-app",
        )
        self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(
            [event.event_type for event in events],
            [
                "runtime.turn.queued",
                "runtime.turn.started",
                "runtime.output.delta",
                "runtime.file.changed",
                "runtime.turn.completed",
            ],
        )
        self.assertEqual(events[2].payload, {"text": "Creating the design."})
        self.assertEqual(events[3].payload, {"path": "index.html", "change": "created"})
        self.assertNotIn("provider", repr(events))
        self.assertNotIn("private prompt", repr(events))
        self.assertTrue(events[-1].terminal)

    def test_persisted_stream_replays_after_store_restart_without_duplicate(self) -> None:
        repo_root = make_temp_repo_root(self)

        def store() -> RuntimeDocumentStore:
            return RuntimeDocumentStore(
                RuntimeCollections(
                    sessions=RuntimeSessionJsonCollection(start_path=repo_root, filename="session.json"),
                    turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
                    events=RuntimeEventJsonCollection(start_path=repo_root),
                    processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
                    states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
                    threads=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="threads.json"),
                    app_streams=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="app_streams.json"),
                    app_stream_events=RuntimeSessionJsonCollection(start_path=repo_root, filename="app_stream_events.json"),
                )
            )

        first = store()
        session = create_runtime_session(
            first,
            session_id="session-restart",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 5, 12, 2, tzinfo=UTC)
        first.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-restart",
                session_id=session.session_id,
                workspace_id="default",
                status="queued",
                input_text="work",
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
                failure_reason=None,
            )
        )
        first.reserve_app_stream(self._record(stream_id="stream-restart", key="restart:1"))
        first.bind_app_stream(
            stream_id="stream-restart",
            workspace_id="default",
            source_app_id="source-app",
            session_id=session.session_id,
            turn_id="turn-restart",
        )
        event = record_runtime_event(
            first,
            event_id="restart-event",
            session_id=session.session_id,
            turn_id="turn-restart",
            plane="turn",
            event_type="runtime.turn.started",
            payload={},
            now=now,
        )

        restarted = store()
        restarted.save_event(event)
        replay = restarted.read_app_stream_events(
            "stream-restart",
            workspace_id="default",
            source_app_id="source-app",
            after_sequence=0,
        )
        self.assertEqual([(item.sequence, item.event_id) for item in replay], [(1, "restart-event")])

    def test_runtime_root_capability_is_short_one_shot_and_workspace_bound(self) -> None:
        repo_root = make_temp_repo_root(self)
        app_data = repo_root / "workspaces/default/data/source-app"
        project = app_data / "generation/data/projects/project-one"
        project.mkdir(parents=True)
        store = RuntimeRootCapabilityStore()
        value = store.issue(
            workspace_id="default",
            source_app_id="source-app",
            actor_id="user:admin",
            app_data_root=app_data,
            relative_path="generation/data/projects/project-one",
        )

        self.assertEqual(store.retained_raw_values(), ())
        with self.assertRaisesRegex(AppHostingError, "ownership mismatch"):
            store.consume(value, workspace_id="other", source_app_id="source-app", actor_id="user:admin")
        self.assertEqual(
            store.consume(value, workspace_id="default", source_app_id="source-app", actor_id="user:admin"),
            project.resolve(),
        )
        with self.assertRaisesRegex(AppHostingError, "invalid or expired"):
            store.consume(value, workspace_id="default", source_app_id="source-app", actor_id="user:admin")

    def test_interrupt_requires_permission_and_exact_source_app_ownership(self) -> None:
        denied_result = {"runtime_turn_interrupt_requests": [{"turn_id": "turn-one"}]}
        denied_contract = SimpleNamespace(
            contract=SimpleNamespace(
                permissions=SimpleNamespace(runtime=SimpleNamespace(create_sessions=False)),
            )
        )
        with self.assertRaisesRegex(AppHostingError, "without declaring runtime.create_sessions"):
            runtime_requests.apply_app_runtime_requests(
                SimpleNamespace(),
                result=denied_result,
                workspace_id="default",
                app_id="source-app",
                source_root=Path("/apps/source-app"),
                backend_entrypoint=None,
                data_root="workspaces/default/data/source-app",
                parsed=denied_contract,
                start_path=Path("/repo"),
            )

        repo_root = make_temp_repo_root(self)
        store = self._memory_store()
        session = create_runtime_session(
            store,
            session_id="session-cancel",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 5, 12, 3, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-cancel",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="work",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        state = SimpleNamespace(runtime_store=store, runtime_event_bus=None)
        with self.assertRaisesRegex(AppHostingError, "owned by another source app"):
            runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": "turn-cancel"},
                workspace_id="default",
                app_id="foreign-app",
            )
        with (
            patch.object(runtime_requests, "_resolved_provider_id", return_value=None),
            patch.object(runtime_requests, "interrupt_runtime_provider_turn", return_value=True),
            patch.object(runtime_requests, "release_idle_runtime_processes"),
            patch.object(runtime_requests, "dispatch_source_app_runtime_event"),
        ):
            result = runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": "turn-cancel"},
                workspace_id="default",
                app_id="source-app",
            )

        self.assertTrue(result["interrupted"])
        self.assertEqual(store.get_turn("turn-cancel").status, "cancelled")
        self.assertEqual(store.list_events("session-cancel")[-1].event_type, "runtime.turn.cancelled")

    def test_cleanup_removes_owned_stream_and_durable_events(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = self._memory_store()
        session = create_runtime_session(
            store,
            session_id="session-cleanup",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 5, 12, 4, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-cleanup",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="work",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        store.reserve_app_stream(self._record(stream_id="stream-cleanup", key="cleanup:1"))
        store.bind_app_stream(
            stream_id="stream-cleanup",
            workspace_id="default",
            source_app_id="source-app",
            session_id=session.session_id,
            turn_id="turn-cleanup",
        )
        record_runtime_event(
            store,
            event_id="cleanup-event",
            session_id=session.session_id,
            turn_id="turn-cleanup",
            plane="turn",
            event_type="runtime.turn.started",
            payload={},
            now=now,
        )

        deleted = store.delete_session_records(session.session_id)

        self.assertEqual(deleted["app_streams"], 1)
        self.assertEqual(deleted["app_stream_events"], 1)
        with self.assertRaisesRegex(RuntimeAppStreamError, "not_found"):
            store.get_app_stream("stream-cleanup", workspace_id="default", source_app_id="source-app")


if __name__ == "__main__":
    unittest.main()
