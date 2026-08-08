"""Tests for backend restart runtime recovery behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.recovery import backend_restart
from core.recovery.backend_restart import _close_orphan_non_terminal_turn_events, _is_inter_agent_root_turn
from core.runtime.app_streams import RuntimeAppStreamRecord
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.errors import RuntimeTurnNotFoundError
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.plain_hosted_cancellation import plain_hosted_request_cancellation
from core.runtime.service import (
    create_runtime_session,
    request_runtime_turn_cancellation,
    transition_runtime_session,
)
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


@dataclass
class _FakeRuntimeStore:
    events: list[RuntimeEventRecord]
    list_events_calls: int = 0
    saved_events: list[RuntimeEventRecord] | None = None

    def __post_init__(self) -> None:
        self.saved_events = []

    def list_events(self, session_id: str) -> list[RuntimeEventRecord]:
        self.list_events_calls += 1
        return [event for event in self.events if event.session_id == session_id]

    def list_recent_events(self, session_id: str, *, limit: int) -> list[RuntimeEventRecord]:
        self.list_events_calls += 1
        return [event for event in self.events if event.session_id == session_id][-limit:]

    def get_turn(self, turn_id: str) -> None:
        raise RuntimeTurnNotFoundError(f"missing {turn_id}")

    def get_session(self, session_id: str) -> RuntimeSessionRecord:
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id="default",
            agent_id="runtime-agent",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root="/tmp/workspace",
            workdir="/tmp/workspace",
            runtime_root="/tmp/workspace/runtime/sessions/session-1",
            started_at=None,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=None,
            system_prompt="",
            skill_ids=[],
            source_app_id="source-app",
        )

    def save_event(self, record: RuntimeEventRecord) -> RuntimeEventRecord:
        assert self.saved_events is not None
        self.saved_events.append(record)
        return record


@dataclass
class _FakeState:
    runtime_store: _FakeRuntimeStore
    runtime_event_bus = None


class BackendRestartRecoveryTestCase(unittest.TestCase):
    def test_orphan_event_recovery_reads_session_events_once(self) -> None:
        store = _FakeRuntimeStore(
            events=[
                RuntimeEventRecord(
                    event_id="event-1",
                    workspace_id="default",
                    session_id="session-1",
                    plane="turn",
                    event_type="runtime.turn.queued",
                    turn_id="missing-turn",
                    process_id=None,
                    payload={},
                    created_at=NOW,
                )
            ]
        )

        closed = _close_orphan_non_terminal_turn_events(_FakeState(runtime_store=store), session_id="session-1")

        self.assertEqual(closed, 1)
        self.assertEqual(store.list_events_calls, 1)
        self.assertEqual(store.saved_events[0].event_type, "runtime.turn.cancelled")

    def test_backend_restart_detects_inter_agent_root_turns(self) -> None:
        turn = SimpleNamespace(turn_id="turn-ia-root")
        events = [
            RuntimeEventRecord(
                event_id="event-ia-root",
                workspace_id="default",
                session_id="session-1",
                plane="turn",
                event_type="runtime.turn.queued",
                turn_id="turn-ia-root",
                process_id=None,
                payload={"inter_agent_run_id": "run-1"},
                created_at=NOW,
            )
        ]

        self.assertTrue(_is_inter_agent_root_turn(turn, events))

    def test_runtime_event_recovery_query_skips_large_partition_without_removing_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "maverick"
            event_path = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "session-1" / "events.json"
            event_path.parent.mkdir(parents=True)
            event_path.write_text(json.dumps([{"event_id": f"event-{index}", "session_id": "session-1"} for index in range(20)]), encoding="utf-8")
            collection = RuntimeEventJsonCollection(start_path=repo_root)

            events = collection.find_recent({"session_id": "session-1"}, limit=5, max_scan_bytes=10)

            self.assertEqual(events, [])
            self.assertTrue(event_path.exists())
            self.assertEqual(len(list(event_path.parent.glob("events.json.quarantined-oversized-*"))), 0)

    def test_runtime_event_recovery_query_quarantines_corrupt_legacy_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "maverick"
            event_path = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "session-1" / "events.json"
            event_path.parent.mkdir(parents=True)
            event_path.write_text("[", encoding="utf-8")
            collection = RuntimeEventJsonCollection(start_path=repo_root)

            events = collection.find_recent({"session_id": "session-1"}, limit=5)

            self.assertEqual(events, [])
            self.assertFalse(event_path.exists())
            self.assertEqual(len(list(event_path.parent.glob("events.json.quarantined-malformed-*"))), 1)

    def test_app_stream_restart_closes_turn_without_queueing_duplicate(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-app-stream",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        session = transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-app-stream",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="work",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        state.runtime_store.reserve_app_stream(
            RuntimeAppStreamRecord(
                stream_id="stream-restart",
                workspace_id="default",
                source_app_id="source-app",
                actor_id="user:admin",
                request_id="request-restart",
                idempotency_key="request-restart:attempt-1",
                request_fingerprint="f" * 64,
                session_id="",
                turn_id="",
                status="reserving",
                last_sequence=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        state.runtime_store.bind_app_stream(
            stream_id="stream-restart",
            workspace_id="default",
            source_app_id="source-app",
            session_id=session.session_id,
            turn_id="turn-app-stream",
            now=NOW,
        )

        with (
            patch.object(backend_restart, "submit_runtime_turn_async") as submit,
            patch.object(backend_restart, "set_thread_availability"),
            patch.object(backend_restart, "dispatch_source_app_runtime_event"),
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            result = backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        submit.assert_not_called()
        self.assertEqual(result.queued_resume_turns, 0)
        self.assertEqual(len(state.runtime_store.list_turns(session.session_id)), 1)
        self.assertEqual(state.runtime_store.get_turn("turn-app-stream").status, "failed")
        stream = state.runtime_store.get_app_stream(
            "stream-restart",
            workspace_id="default",
            source_app_id="source-app",
        )
        self.assertEqual(stream.status, "failed")

    def test_cancel_intent_prevents_failed_event_callback_and_automatic_resume(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-cancelled-before-recovery",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-cancelled-before-recovery",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="stop before restart",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        request_runtime_turn_cancellation(
            state.runtime_store,
            turn_id="turn-cancelled-before-recovery",
            reason="cancel won before restart recovery",
            now=NOW,
        )

        with (
            patch.object(backend_restart, "submit_runtime_turn_async") as submit,
            patch.object(backend_restart, "set_thread_availability"),
            patch.object(backend_restart, "dispatch_source_app_runtime_event") as dispatch,
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            result = backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        updated = state.runtime_store.get_turn("turn-cancelled-before-recovery")
        terminal_events = [
            event
            for event in state.runtime_store.list_events(session.session_id)
            if event.turn_id == updated.turn_id and event.event_type.startswith("runtime.turn.")
        ]
        submit.assert_not_called()
        self.assertEqual(result.queued_resume_turns, 0)
        self.assertEqual(updated.status, "cancelled")
        self.assertEqual(terminal_events[-1].event_type, "runtime.turn.cancelled")
        self.assertEqual(terminal_events[-1].payload["recovery_action"], "preserve_cancelled_turn")
        self.assertEqual(dispatch.call_args.kwargs["event_type"], "runtime.turn.cancelled")

    def test_backend_restart_reconciles_crashed_hosted_owner_and_allows_new_generation(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-crashed-hosted-owner",
            workspace_id="default",
            agent_id="chat",
            runtime_mode="plain_hosted_chat",
            start_path=repo_root,
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-crashed-hosted-owner",
                session_id=session.session_id,
                workspace_id="default",
                status="queued",
                input_text="retry provider request",
                created_at=NOW,
                updated_at=NOW,
                started_at=None,
                completed_at=None,
                failure_reason=None,
            )
        )
        state.runtime_store.mark_turn_provider_request_started(
            turn_id="turn-crashed-hosted-owner",
            owner_id="backend:2147483647:dead",
            generation="dead-request-generation",
            owner_kind="process",
            owner_host_id=socket.gethostname(),
            owner_pid=2147483647,
            owner_process_start="dead-process-start",
            now=NOW,
        )

        with (
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        reconciled = state.runtime_store.get_turn("turn-crashed-hosted-owner")
        self.assertIsNotNone(reconciled.provider_request_finished_at)

        with plain_hosted_request_cancellation(
            session_id=session.session_id,
            turn_id=reconciled.turn_id,
            store=state.runtime_store,
        ):
            restarted = state.runtime_store.get_turn(reconciled.turn_id)
            self.assertNotEqual(restarted.provider_request_owner_id, "backend:2147483647:dead")
            self.assertNotEqual(restarted.provider_request_generation, "dead-request-generation")
            self.assertIsNone(restarted.provider_request_finished_at)
            state.runtime_store.mark_turn_provider_request_finished(
                turn_id=restarted.turn_id,
                owner_id="backend:2147483647:dead",
                generation="dead-request-generation",
                now=NOW,
            )
            self.assertIsNone(state.runtime_store.get_turn(restarted.turn_id).provider_request_finished_at)

        self.assertIsNotNone(state.runtime_store.get_turn(reconciled.turn_id).provider_request_finished_at)


if __name__ == "__main__":
    unittest.main()
