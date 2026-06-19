from __future__ import annotations

from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.api.inter_agent_api_f4_support import InterAgentApiF4Fixture, run_payload_without_snapshot


class InterAgentApiFinalProjectionTestCase(InterAgentApiF4Fixture, unittest.TestCase):
    def test_root_projection_does_not_reconstruct_final_answer_from_child_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

            def fake_submit(_state, *, session, input_text, client_message_id=None, async_requested=False):
                turn = RuntimeTurnRecord(
                    turn_id="turn-empty-child-final",
                    session_id=session.session_id,
                    workspace_id="default",
                    status="completed",
                    input_text=input_text,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    completed_at=now,
                    failure_reason=None,
                )
                delta = RuntimeEventRecord(
                    event_id="event-child-progress-delta",
                    workspace_id="default",
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.output.delta",
                    turn_id=turn.turn_id,
                    process_id=None,
                    payload={"text": "Uso `maverick3-code-skill` e mi oriento nel repository."},
                    created_at=now,
                )
                final = RuntimeEventRecord(
                    event_id="event-empty-child-final",
                    workspace_id="default",
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.output.final",
                    turn_id=turn.turn_id,
                    process_id=None,
                    payload={"text": ""},
                    created_at=now,
                )
                _state.runtime_store.save_turn(turn)
                _state.runtime_store.save_event(delta)
                _state.runtime_store.save_event(final)
                return turn, [delta, final]

            self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=run_payload_without_snapshot(run_id="run-empty-final-projection"),
                cookie=cookie,
            )
            with (
                patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit),
                patch("core.api.inter_agent_api.schedule_runtime_thread_title_generation"),
            ):
                execute_status, execute_payload, _headers = self._invoke(
                    app,
                    path="/api/inter-agent/runs/run-empty-final-projection/execute",
                    method="POST",
                    body={
                        "input_text": "Review the demo.",
                        "client_message_id": "client-empty-final",
                    },
                    cookie=cookie,
                )
            root_events = state.runtime_store.list_events("root-session")
            final_events = [event for event in root_events if event.event_type == "runtime.output.final"]

        self.assertEqual(execute_status, 200)
        self.assertEqual(execute_payload["final_answer"], "Researcher completed without a final answer.")
        self.assertEqual([event.payload["text"] for event in final_events], ["Researcher completed without a final answer."])
        self.assertEqual([event.payload["complete_text"] for event in final_events], ["Researcher completed without a final answer."])
        self.assertNotIn("maverick3-code-skill", final_events[0].payload["text"])


if __name__ == "__main__":
    unittest.main()
