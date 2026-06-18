from __future__ import annotations

import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.runtime.service import queue_runtime_turn, record_runtime_event, transition_runtime_turn
from tests.unit.api.inter_agent_api_f4_support import InterAgentApiF4Fixture, run_payload_without_snapshot


class InterAgentRuntimeCancelTestCase(InterAgentApiF4Fixture, unittest.TestCase):
    def test_runtime_turn_interrupt_cancels_linked_inter_agent_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            state = self._bootstrap_state(repo_root)
            self._create_root_session(state, repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, _create_payload, _headers = self._invoke(
                app,
                path="/api/inter-agent/runs",
                method="POST",
                body=run_payload_without_snapshot(run_id="run-root-stop"),
                cookie=cookie,
            )
            turn = queue_runtime_turn(
                state.runtime_store,
                turn_id="turn-root-stop",
                session_id="root-session",
                input_text="Stop this multi-agent run.",
            )
            record_runtime_event(
                state.runtime_store,
                event_id="event-root-stop-queued",
                session_id="root-session",
                turn_id=turn.turn_id,
                plane="turn",
                event_type="runtime.turn.queued",
                payload={"input_text": turn.input_text, "inter_agent_run_id": "run-root-stop"},
                event_bus=state.runtime_event_bus,
            )
            transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")

            interrupt_status, interrupt_payload, _headers = self._invoke(
                app,
                path="/api/runtime/turns/turn-root-stop/interrupt",
                method="POST",
                cookie=cookie,
            )
            run = state.inter_agent_store.get_run("run-root-stop", workspace_id="default")
            event_types = [
                event.event_type
                for event in state.inter_agent_store.list_event_page(
                    "run-root-stop",
                    workspace_id="default",
                    visibility_plane="summary",
                    limit=50,
                ).events
            ]

        self.assertEqual(create_status, 201)
        self.assertEqual(interrupt_status, 200)
        self.assertTrue(interrupt_payload["interrupted"])
        self.assertEqual(interrupt_payload["inter_agent_cleanup"][0]["run"]["status"], "cancelled")
        self.assertEqual(run.status, "cancelled")
        self.assertIn("inter_agent.run.cancelled", event_types)


if __name__ == "__main__":
    unittest.main()
