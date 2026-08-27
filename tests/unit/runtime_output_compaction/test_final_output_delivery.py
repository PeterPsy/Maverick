"""Stable hosted final-output event delivery regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_state import bootstrap_platform_state
from core.runtime.execution_events import RuntimeExecutionEvent
from core.runtime.service import create_runtime_session, queue_runtime_turn
from core.runtime.turn_submission_service_events import _record_final_output
from core.runtime.turn_submission_service_output_text import _RuntimeTurnOutputRecorder


class FinalOutputDeliveryTest(unittest.TestCase):
    def test_hosted_final_delivery_id_is_persisted_once_across_restarts(self) -> None:
        state, session = self._state_and_session()
        queue_runtime_turn(
            state.runtime_store,
            turn_id="turn-final-outbox",
            session_id=session.session_id,
            input_text="synthetic fixture input",
        )
        payload = {
            "text": "durable answer",
            "complete_text": "durable answer",
            "provider_id": "test-provider",
            "exit_code": 0,
            "delivery_id": "delivery-final-outbox",
        }
        first = self._record(state, session.session_id, payload)
        replayed = self._record(state, session.session_id, payload)
        with self.assertRaisesRegex(RuntimeError, "runtime_final_output_identity_conflict"):
            self._record(state, session.session_id, {**payload, "text": "conflict"})
        with self.assertRaisesRegex(RuntimeError, "runtime_final_output_identity_conflict"):
            self._record(
                state,
                session.session_id,
                {**payload, "delivery_id": "conflicting-delivery-id"},
            )
        state.runtime_store.collections.events.delete_one(
            {
                "workspace_id": session.workspace_id,
                "session_id": session.session_id,
                "event_id": "delivery-final-outbox",
            }
        )
        replayed_from_history = self._record(state, session.session_id, payload)
        completion = {
            "output_text": "durable answer",
            "exit_code": 0,
            "delivery_id": "delivery-final-outbox",
        }
        for _attempt in range(2):
            _RuntimeTurnOutputRecorder(
                state,
                session_id=session.session_id,
                turn_id="turn-final-outbox",
            ).record(RuntimeExecutionEvent("provider.execution.completed", completion))
        completed = _record_final_output(
            state,
            session_id=session.session_id,
            turn_id="turn-final-outbox",
            provider_id="test-provider",
            output_text="durable answer",
            complete_text="durable answer",
            exit_code=0,
        )

        self.assertEqual(first.event_id, "delivery-final-outbox")
        self.assertEqual(replayed, first)
        self.assertEqual(replayed_from_history, first)
        self.assertEqual(completed, first)
        event_types = [
            event.event_type
            for event in state.runtime_store.list_events(session.session_id)
        ]
        self.assertEqual(event_types.count("runtime.output.final"), 1)
        self.assertEqual(event_types.count("provider.execution.completed"), 1)

    @staticmethod
    def _record(state, session_id: str, payload: dict[str, object]):
        return _RuntimeTurnOutputRecorder(
            state,
            session_id=session_id,
            turn_id="turn-final-outbox",
        ).record(RuntimeExecutionEvent("runtime.output.final", payload))

    def _state_and_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(
                start_path=repo_root,
                install_builtin_apps=False,
            )
        session = create_runtime_session(
            state.runtime_store,
            session_id="sess-final-outbox",
            workspace_id="default",
            agent_id="test-agent",
            start_path=repo_root,
            now=datetime(2026, 6, 15, tzinfo=UTC),
        )
        return state, session


if __name__ == "__main__":
    unittest.main()
