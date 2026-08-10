"""Backend-restart recovery regressions for cancellation terminalization."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.recovery import backend_restart
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session, record_runtime_event
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


class BackendRestartCancellationTerminalizationTestCase(unittest.TestCase):
    def test_delivered_legacy_cancellation_reconciles_thread_without_callback_replay(self) -> None:
        repo_root = make_temp_repo_root(self)
        state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="session-legacy-cancellation",
            workspace_id="default",
            agent_id="chat",
            source_app_id="source-app",
            start_path=repo_root,
        )
        state.runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-legacy-cancellation",
                session_id=session.session_id,
                workspace_id="default",
                status="cancelled",
                input_text="legacy cancellation",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                failure_reason="legacy cancellation",
                cancellation_requested_at=NOW,
                cancellation_reason="legacy cancellation",
            )
        )
        legacy_event = record_runtime_event(
            state.runtime_store,
            event_id="legacy-event",
            session_id=session.session_id,
            turn_id="turn-legacy-cancellation",
            plane="turn",
            event_type="runtime.turn.cancelled",
            payload={"reason": "legacy cancellation"},
            now=NOW,
        )
        thread = create_runtime_thread(
            state.runtime_store,
            workspace_id="default",
            runtime_session_id=session.session_id,
            title="Legacy cancellation",
            agent_label="chat",
            source_app_id="source-app",
            turn_facts_known=True,
            availability="active",
            now=NOW,
        )
        self.assertEqual(thread.availability, "active")

        with (
            patch.object(backend_restart, "dispatch_source_app_runtime_event") as dispatch,
            patch.object(backend_restart, "dispatch_workspace_app_background_hooks", return_value=[]),
            patch.object(backend_restart.InterAgentService, "recover_non_terminal_runs", return_value=[]),
        ):
            backend_restart.recover_interrupted_runtime_turns_after_backend_restart(state)

        migrated = state.runtime_store.get_turn("turn-legacy-cancellation")
        dispatch.assert_not_called()
        self.assertEqual(migrated.terminalization_event_id, legacy_event.event_id)
        self.assertIsNotNone(migrated.terminalization_event_persisted_at)
        self.assertIsNotNone(migrated.terminalization_thread_released_at)
        self.assertIsNotNone(migrated.terminalization_callback_delivered_at)
        self.assertEqual(state.runtime_store.get_thread(thread.thread_id).availability, "free")


if __name__ == "__main__":
    unittest.main()
