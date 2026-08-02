from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationSchedulerTest(unittest.TestCase):
    def test_dynamic_scheduler_runs_dependencies_revision_loop_and_orchestrator_gate(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        prompts: dict[str, str] = {}

        def execute_turn(participant, prompt: str, client_message_id: str) -> str:
            prompts[client_message_id] = prompt
            outputs = {
                f"{run.run_id}:orchestrator:plan": (
                    '{"summary":"Implement and review.","tasks":['
                    '{"id":"implement","label":"Implementer","role":"implementer","objective":"Implement safely.","depends_on":[]},'
                    '{"id":"review","label":"Reviewer","role":"reviewer","objective":"Review the implementation.",'
                    '"depends_on":["implement"],"review_of":"implement"}]}'
                ),
                f"{run.run_id}:task:implement": "First implementation.",
                f"{run.run_id}:task:review": '{"approved":false,"feedback":"Add the missing regression coverage."}',
                f"{run.run_id}:task:implement-r2": "Corrected implementation with regression coverage.",
                f"{run.run_id}:task:review-r2": '{"approved":true,"feedback":"All requirements pass."}',
                f"{run.run_id}:orchestrator:completion": (
                    '{"complete":true,"quality_passed":true,"summary":"Reviewed and accepted.",'
                    '"final_answer":"The implementation is complete and verified."}'
                ),
            }
            return outputs[client_message_id]

        generalist_event = SimpleNamespace(
            event_id="generalist-final-1",
            turn_id="generalist-turn-1",
            event_type="runtime.output.final",
            payload={"text": "Preserve the public API and prioritize regression coverage."},
        )
        source_turn = SimpleNamespace(
            turn_id="generalist-turn-1",
            status="active",
            input_text="Implement the requested redesign.",
        )

        class RuntimeStore:
            polls = 0

            def get_turn(self, _turn_id):
                self.polls += 1
                if self.polls > 1:
                    source_turn.status = "completed"
                return source_turn

            def list_events(self, _session_id):
                return [generalist_event] if self.polls > 1 else []

        result = execute_orchestrated_run(
            service,
            SimpleNamespace(runtime_store=RuntimeStore()),
            workspace_id="default",
            run_id=run.run_id,
            turn_executor=execute_turn,
        )

        participants = store.list_participants(run.run_id, workspace_id="default")
        edges = store.list_edges(run.run_id, workspace_id="default")
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertEqual(result.run.status, "completed")
        self.assertEqual(result.final_answer, "The implementation is complete and verified.")
        self.assertEqual(
            [participant.participant_id for participant in participants],
            ["orchestrator", "implement", "review", "implement-r2", "review-r2"],
        )
        self.assertEqual(len(edges), 4)
        self.assertIn("Preserve the public API", prompts[f"{run.run_id}:orchestrator:plan"])
        self.assertIn("Implement the requested redesign", prompts[f"{run.run_id}:orchestrator:plan"])
        self.assertIn("Reviewer feedback", prompts[f"{run.run_id}:task:implement-r2"])
        self.assertIn("inter_agent.completion.decided", [event.event_type for event in events])
        self.assertIn("inter_agent.generalist.handoff_prepared", [event.event_type for event in events])
        self.assertEqual(
            next(event for event in events if event.event_type == "inter_agent.run.completed").participant_id,
            "orchestrator",
        )


if __name__ == "__main__":
    unittest.main()
