"""Runtime interrupt surface race regressions."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.api.runtime_api as runtime_api
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import (
    create_runtime_session,
    request_runtime_turn_cancellation,
    transition_runtime_turn,
)
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeInterruptRaceTestCase(unittest.TestCase):
    def test_api_reports_not_interrupted_when_completion_wins_before_cancel_intent(self) -> None:
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        repo_root = make_temp_repo_root(self)
        session = create_runtime_session(
            runtime_store,
            session_id="api-completion-wins",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="api-completion-wins-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="finish now",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            runtime_event_bus=None,
            workspace_store=object(),
        )
        response_status: list[str] = []

        def completion_wins(store, *, turn_id: str, reason: str, now=None):
            transition_runtime_turn(store, turn_id=turn_id, target_status="completed")
            return request_runtime_turn_cancellation(store, turn_id=turn_id, reason=reason, now=now)

        def start_response(status: str, _headers: list[tuple[str, str]]) -> None:
            response_status.append(status)

        with (
            patch.object(runtime_api, "require_runtime_session_operation"),
            patch.object(runtime_api, "request_runtime_turn_cancellation", side_effect=completion_wins),
            patch.object(runtime_api, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_api, "interrupt_runtime_provider_turn") as interrupt_provider,
            patch.object(runtime_api, "set_thread_availability"),
            patch.object(runtime_api, "release_idle_runtime_processes"),
            patch.object(runtime_api, "dispatch_source_app_runtime_event") as dispatch,
        ):
            response = runtime_api._handle_turn_interrupt(
                state,
                SimpleNamespace(workspace_id="default", user=SimpleNamespace()),
                "api-completion-wins-turn",
                start_response,
                start_path=repo_root,
            )

        payload = json.loads(b"".join(response).decode("utf-8"))
        self.assertEqual(response_status, ["200 OK"])
        self.assertFalse(payload["interrupted"])
        self.assertEqual(payload["turn"]["status"], "completed")
        self.assertNotIn("event", payload)
        self.assertNotIn(
            "runtime.turn.cancelled",
            [event.event_type for event in runtime_store.list_events(session.session_id)],
        )
        interrupt_provider.assert_not_called()
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
