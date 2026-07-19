from __future__ import annotations

import unittest

from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.service import InterAgentService
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    participant_spec as _participant,
    run_spec as _run_spec,
    runtime_state_namespace as _state,
)


class InterAgentExecutorSequenceTest(unittest.TestCase):
    def test_sequential_run_uses_spec_sequence_not_participant_id_order(self) -> None:
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="sequential",
                run_id="sequential-spec-order",
                participants=[
                    _participant("z_first", "First"),
                    _participant("a_second", "Second"),
                ],
            ),
            now=NOW,
        )

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Run these in sequence.",
            controlled_participants={
                "z_first": {"output_text": "First output.", "summary": "First completed."},
                "a_second": {"output_text": "Second output.", "summary": "Second completed."},
            },
            allow_synthetic_participants=True,
            now=NOW,
        )

        participants = store.list_participants(run.run_id, workspace_id="default")
        message_events = [
            event
            for event in store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
            if event.event_type == "inter_agent.message.sent"
        ]

        self.assertEqual([participant.participant_id for participant in participants], ["orchestrator", "z_first", "a_second"])
        self.assertEqual([participant.sequence_index for participant in participants], [0, 1, 2])
        self.assertEqual([item.participant_id for item in result.participant_results], ["z_first", "a_second"])
        self.assertEqual([event.participant_id for event in message_events], ["z_first", "a_second"])
        self.assertNotIn("Previous participant output", message_events[0].payload["input_text"])
        self.assertIn("Previous participant output:\nFirst output.", message_events[1].payload["input_text"])


if __name__ == "__main__":
    unittest.main()
