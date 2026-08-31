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
from core.runtime.turn_terminalization import terminalize_runtime_turn_cancellation
from core.runtime.service import (
    create_runtime_session,
    record_runtime_event,
    request_runtime_turn_cancellation,
    transition_runtime_session,
    transition_runtime_turn,
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
    def test_cancel_terminalization_failure_is_isolated_to_one_turn(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-isolated-cancel-recovery",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        for turn_id in ("turn-corrupt-cancel", "turn-recoverable-cancel"):
            state.runtime_store.save_turn(
                RuntimeTurnRecord(
                    turn_id=turn_id,
                    session_id=session.session_id,
                    workspace_id="default",
                    status="active",
                    input_text=turn_id,
                    created_at=NOW,
                    updated_at=NOW,
                    started_at=NOW,
                    completed_at=None,
                    failure_reason=None,
                )
            )

        request_runtime_turn_cancellation(
            state.runtime_store,
            turn_id="turn-corrupt-cancel",
            reason="corrupt cancellation",
            now=NOW,
        )
        corrupt = transition_runtime_turn(
            state.runtime_store,
            turn_id="turn-corrupt-cancel",
            target_status="cancelled",
            failure_reason="corrupt cancellation",
            now=NOW,
        )
        state.runtime_store.claim_turn_terminalization(
            turn_id=corrupt.turn_id,
            event_id="outbox-event",
            event_type="runtime.turn.cancelled",
            payload={"reason": "corrupt cancellation"},
            now=NOW,
        )
        record_runtime_event(
            state.runtime_store,
            event_id="worker-event",
            session_id=session.session_id,
            turn_id=corrupt.turn_id,
            plane="turn",
            event_type="runtime.turn.cancelled",
            payload={"reason": "corrupt cancellation"},
            now=NOW,
        )
        recoverable = terminalize_runtime_turn_cancellation(
            state.runtime_store,
            turn_id="turn-recoverable-cancel",
            reason="recoverable cancellation",
            event_payload={"reason": "recoverable cancellation"},
            callback=lambda _session, _turn, _event: (_ for _ in ()).throw(RuntimeError("callback crash")),
            now=NOW,
        )

        with (
            patch.object(backend_restart, "dispatch_source_app_runtime_event") as dispatch,
            self.assertLogs(backend_restart.logger, level="ERROR"),
        ):
            recovered = backend_restart._recover_pending_cancelled_turn_terminalizations(state)

        self.assertEqual(recovered, 1)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["runtime_event_id"], recoverable.event.event_id)
        self.assertIsNone(state.runtime_store.get_turn(corrupt.turn_id).terminalization_event_persisted_at)
        self.assertIsNotNone(
            state.runtime_store.get_turn(recoverable.turn.turn_id).terminalization_callback_delivered_at
        )

    def test_backend_restart_drains_pending_cancel_callback_with_same_event_id(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-pending-cancel-callback",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-pending-cancel-callback",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="cancel before restart",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        seeded = terminalize_runtime_turn_cancellation(
            state.runtime_store,
            turn_id="turn-pending-cancel-callback",
            reason="cancel before restart",
            event_payload={"reason": "cancel before restart"},
            callback=lambda _session, _turn, _event: (_ for _ in ()).throw(RuntimeError("crash")),
            now=NOW,
        )
        self.assertTrue(seeded.callback_pending)

        with (
            patch.object(backend_restart, "dispatch_source_app_runtime_event") as dispatch,
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        persisted = state.runtime_store.get_turn(seeded.turn.turn_id)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["runtime_event_id"], seeded.event.event_id)
        self.assertIsNotNone(persisted.terminalization_callback_delivered_at)

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

    def test_backend_restart_reinjects_interrupted_turn_skill_ids_into_resume(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-explicit-skill-recovery",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            skill_ids=["storage-ops"],
            skill_activation_mode="explicit",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-explicit-skill-recovery",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="$storage-ops continue the report",
                invoked_skill_ids=["storage-ops"],
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )

        with (
            patch.object(
                backend_restart,
                "admit_runtime_session",
                return_value=SimpleNamespace(session=session),
            ),
            patch.object(backend_restart, "submit_runtime_turn_async") as submit,
            patch.object(backend_restart, "set_thread_availability"),
            patch.object(backend_restart, "dispatch_source_app_runtime_event"),
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            result = backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        self.assertEqual(result.queued_resume_turns, 1)
        self.assertEqual(submit.call_args.kwargs["invoked_skill_ids"], ["storage-ops"])

    def test_backend_restart_blocks_resume_before_queue_when_authority_is_invalid(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-invalid-recovery-authority",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            runtime_mode="agentic",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-invalid-recovery-authority",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="continue after restart",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
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
        blocked = [
            event
            for event in state.runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.recovery.resume_blocked"
        ]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].payload["blocked_reason"], "runtime_profile_upgrade_required")
        self.assertEqual(blocked[0].payload["detail_code"], "runtime_execution_binding_missing")

    def test_interrupted_recovery_resume_is_retried_with_visible_failure(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-idempotent-resume",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        resume_turn = RuntimeTurnRecord(
            turn_id="turn-idempotent-resume",
            session_id=session.session_id,
            workspace_id="default",
            status="queued",
            input_text=backend_restart.BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
            client_message_id=(
                f"{backend_restart.RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:source-turn"
            ),
            created_at=NOW,
            updated_at=NOW,
            started_at=None,
            completed_at=None,
            failure_reason=None,
        )
        state.runtime_store.save_turn(resume_turn)
        record_runtime_event(
            state.runtime_store,
            event_id="resume-queued-event",
            session_id=session.session_id,
            turn_id=resume_turn.turn_id,
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"client_message_id": resume_turn.client_message_id},
            now=NOW,
        )
        record_runtime_event(
            state.runtime_store,
            event_id="resume-recovery-event",
            session_id=session.session_id,
            turn_id=resume_turn.turn_id,
            plane="runtime",
            event_type="runtime.recovery.resume_queued",
            payload={"reason": "backend_restart"},
            now=NOW,
        )
        record_runtime_event(
            state.runtime_store,
            event_id="unrelated-old-resume",
            session_id=session.session_id,
            turn_id="unrelated-old-resume-turn",
            plane="turn",
            event_type="runtime.turn.queued",
            payload={
                "client_message_id": (
                    f"{backend_restart.RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:unrelated-source"
                )
            },
            now=NOW,
        )

        with (
            patch.object(
                backend_restart,
                "admit_runtime_session",
                return_value=SimpleNamespace(session=session),
            ),
            patch.object(backend_restart, "submit_runtime_turn_async") as submit,
            patch.object(backend_restart, "set_thread_availability"),
            patch.object(backend_restart, "dispatch_source_app_runtime_event"),
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            result = backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        submit.assert_called_once()
        self.assertEqual(result.queued_resume_turns, 1)
        self.assertEqual(
            state.runtime_store.get_turn(resume_turn.turn_id).status,
            "failed",
        )
        terminal_event = state.runtime_store.find_turn_event(
            turn_id=resume_turn.turn_id,
            event_type="runtime.turn.failed",
        )
        self.assertEqual(terminal_event.payload["recovery_action"], "retry_resume_turn")
        self.assertEqual(terminal_event.payload["resume_attempts"], 1)
        self.assertEqual(
            terminal_event.payload["max_resume_attempts"],
            backend_restart.MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_CHAIN,
        )
        self.assertIn("recovery resume retry queued", terminal_event.payload["error"])
        self.assertEqual(
            submit.call_args.kwargs["client_message_id"],
            (
                f"{backend_restart.RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:"
                f"{resume_turn.turn_id}:attempt-2"
            ),
        )
        recovery_event = [
            event
            for event in state.runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.recovery.resume_queued"
        ][-1]
        self.assertEqual(recovery_event.payload["resume_attempt"], 2)
        self.assertEqual(
            recovery_event.payload["max_resume_attempts"],
            backend_restart.MAX_BACKEND_RESTART_RESUME_ATTEMPTS_PER_CHAIN,
        )

    def test_interrupted_recovery_resume_stops_with_visible_failure_at_retry_limit(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-resume-limit",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        resume_turn = RuntimeTurnRecord(
            turn_id="turn-resume-limit",
            session_id=session.session_id,
            workspace_id="default",
            status="active",
            input_text=backend_restart.BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
            client_message_id=(
                f"{backend_restart.RESUME_CLIENT_MESSAGE_ID_PREFIX}{session.session_id}:"
                "turn-resume-limit-2:attempt-3"
            ),
            created_at=NOW,
            updated_at=NOW,
            started_at=NOW,
            completed_at=None,
            failure_reason=None,
        )
        state.runtime_store.save_turn(resume_turn)
        record_runtime_event(
            state.runtime_store,
            event_id="resume-limit-queued-3",
            session_id=session.session_id,
            turn_id=resume_turn.turn_id,
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"client_message_id": resume_turn.client_message_id},
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
        self.assertEqual(state.runtime_store.get_turn(resume_turn.turn_id).status, "failed")
        terminal_event = state.runtime_store.find_turn_event(
            turn_id=resume_turn.turn_id,
            event_type="runtime.turn.failed",
        )
        self.assertEqual(terminal_event.payload["recovery_action"], "close_resume_turn")
        self.assertIn("retry limit reached", terminal_event.payload["error"])
        blocked = [
            event
            for event in state.runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.recovery.resume_blocked"
        ]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].payload["blocked_reason"], "resume_retry_limit_reached")

    def test_nonzero_final_output_does_not_suppress_restart_resume(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-failed-final",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        turn = RuntimeTurnRecord(
            turn_id="turn-failed-final",
            session_id=session.session_id,
            workspace_id="default",
            status="active",
            input_text="finish the implementation",
            created_at=NOW,
            updated_at=NOW,
            started_at=NOW,
            completed_at=None,
            failure_reason=None,
        )
        state.runtime_store.save_turn(turn)
        record_runtime_event(
            state.runtime_store,
            event_id="failed-final-output",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.output.final",
            payload={"text": "partial progress", "complete_text": "partial progress", "exit_code": 1},
            now=NOW,
        )

        with (
            patch.object(
                backend_restart,
                "admit_runtime_session",
                return_value=SimpleNamespace(session=session),
            ),
            patch.object(backend_restart, "submit_runtime_turn_async") as submit,
            patch.object(backend_restart, "set_thread_availability"),
            patch.object(backend_restart, "dispatch_source_app_runtime_event"),
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            result = backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        submit.assert_called_once()
        self.assertEqual(result.queued_resume_turns, 1)
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "failed")
        event_types = [event.event_type for event in state.runtime_store.list_events(session.session_id)]
        self.assertIn("runtime.turn.failed", event_types)
        self.assertNotIn("runtime.turn.completed", event_types)
        failed_event = state.runtime_store.find_turn_event(
            turn_id=turn.turn_id,
            event_type="runtime.turn.failed",
        )
        self.assertIn("automatic resume turn queued", failed_event.payload["error"])

    def test_zero_exit_final_output_still_reconciles_completed_without_resume(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-successful-final",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="running",
        )
        turn = RuntimeTurnRecord(
            turn_id="turn-successful-final",
            session_id=session.session_id,
            workspace_id="default",
            status="active",
            input_text="finish successfully",
            created_at=NOW,
            updated_at=NOW,
            started_at=NOW,
            completed_at=None,
            failure_reason=None,
        )
        state.runtime_store.save_turn(turn)
        record_runtime_event(
            state.runtime_store,
            event_id="successful-final-output",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.output.final",
            payload={"text": "done", "complete_text": "done", "exit_code": 0},
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
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "completed")
        event_types = [event.event_type for event in state.runtime_store.list_events(session.session_id)]
        self.assertIn("runtime.turn.completed", event_types)
        self.assertNotIn("runtime.turn.failed", event_types)

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
