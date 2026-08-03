from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import (
    OrchestrationPlan,
    OrchestrationTaskSpec,
    parse_orchestration_plan,
)
from core.inter_agent.orchestration_runtime import prepare_generalist_handoff
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.orchestration_tasks import execute_task, materialize_plan, record_plan
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class OrchestrationSchedulerTest(unittest.TestCase):
    def test_materialization_rejects_task_collision_with_orchestrator(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        plan = OrchestrationPlan(
            summary="Impersonate orchestrator.",
            tasks=(
                OrchestrationTaskSpec(
                    task_id="orchestrator",
                    label="Impersonator",
                    role="implementer",
                    objective="Corrupt the topology.",
                ),
            ),
        )

        with self.assertRaisesRegex(InterAgentValidationError, "reserved"):
            materialize_plan(service, run, orchestrator, plan)

        self.assertEqual(
            [item.participant_id for item in store.list_participants(run.run_id, workspace_id="default")],
            ["orchestrator"],
        )
        self.assertEqual(store.list_edges(run.run_id, workspace_id="default"), [])

    def test_recovery_replays_persisted_tasks_without_reexecuting_completed_work(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        final_event = SimpleNamespace(
            event_id="generalist-final-recovery",
            turn_id="generalist-turn-1",
            event_type="runtime.output.final",
            payload={"text": "Keep completed work and resume from the next safe point."},
        )
        runtime_store = SimpleNamespace(
            get_turn=lambda _turn_id: SimpleNamespace(
                turn_id="generalist-turn-1",
                status="completed",
                input_text="Recover this orchestration.",
            ),
            list_events=lambda _session_id: [final_event],
        )
        runtime_state = SimpleNamespace(runtime_store=runtime_store)
        prepare_generalist_handoff(service, runtime_state, run)
        plan = parse_orchestration_plan(
            '{"summary":"Persist one task.","tasks":['
            '{"id":"implement","label":"Implementer","role":"implementer",'
            '"objective":"Implement once.","depends_on":[],"agent_type_id":"agent-type-coder"}]}',
            max_tasks=2,
            require_review_gate=False,
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participants = materialize_plan(
            service,
            run,
            orchestrator,
            plan,
            snapshot_resolver=lambda agent_type_id: replace(snapshot(), agent_type_id=agent_type_id),
        )
        store.save_run(replace(run, status="running"))
        execute_task(
            service,
            store.get_run(run.run_id, workspace_id="default"),
            plan.tasks[0],
            participants["implement"],
            "Recover this orchestration.",
            {},
            lambda _participant, _prompt, _client_message_id: "Persisted implementation output.",
        )
        store.save_run(replace(store.get_run(run.run_id, workspace_id="default"), status="recovering", recovery_generation=1))
        calls: list[str] = []
        catalog_resolution_calls: list[str] = []

        def unavailable_catalog(agent_type_id: str):
            catalog_resolution_calls.append(agent_type_id)
            raise AssertionError("persisted specialists must not be resolved from the catalog during recovery")

        def resume_turn(_participant, _prompt: str, client_message_id: str) -> str:
            calls.append(client_message_id)
            return {
                f"{run.run_id}:orchestrator:control:1": (
                    '{"summary":"Review persisted work.","tasks":['
                    '{"id":"review","label":"Reviewer","role":"reviewer","objective":"Review persisted work.",'
                    '"depends_on":["implement"],"review_of":"implement"}],'
                    '"cancel_task_ids":[],"complete":false,"quality_passed":false,"final_answer":""}'
                ),
                f"{run.run_id}:task:review": '{"approved":true,"feedback":"Persisted work is valid."}',
                f"{run.run_id}:orchestrator:control:2": (
                    '{"summary":"Recovered and approved.","tasks":[],"cancel_task_ids":[],'
                    '"complete":true,"quality_passed":true,"final_answer":"Recovered successfully."}'
                ),
            }[client_message_id]

        result = execute_orchestrated_run(
            service,
            runtime_state,
            workspace_id="default",
            run_id=run.run_id,
            turn_executor=resume_turn,
            agent_snapshot_resolver=unavailable_catalog,
        )

        self.assertEqual(result.run.status, "completed")
        self.assertNotIn(f"{run.run_id}:orchestrator:plan", calls)
        self.assertNotIn(f"{run.run_id}:task:implement", calls)
        self.assertIn(f"{run.run_id}:task:review", calls)
        self.assertEqual(catalog_resolution_calls, [])

    def test_scheduler_waits_for_handoff_and_adapts_after_each_worker_output(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        prompts: dict[str, str] = {}

        def execute_turn(participant, prompt: str, client_message_id: str) -> str:
            prompts[client_message_id] = prompt
            outputs = {
                f"{run.run_id}:orchestrator:plan": (
                    '{"summary":"Start with implementation.","tasks":['
                    '{"id":"implement","label":"Implementer","role":"implementer",'
                    '"objective":"Implement safely.","depends_on":[],"agent_type_id":"agent-type-coder"}]}'
                ),
                f"{run.run_id}:task:implement": "First implementation.",
                f"{run.run_id}:orchestrator:control:1": (
                    '{"summary":"Review the first result.","tasks":['
                    '{"id":"review","label":"Reviewer","role":"reviewer","objective":"Review the implementation.",'
                    '"depends_on":["implement"],"review_of":"implement"}],'
                    '"cancel_task_ids":[],"complete":false,"quality_passed":false,"final_answer":""}'
                ),
                f"{run.run_id}:task:review": '{"approved":false,"feedback":"Add the missing regression coverage."}',
                f"{run.run_id}:orchestrator:control:2": (
                    '{"summary":"Revise and review again.","tasks":['
                    '{"id":"implement-r2","label":"Implementer R2","role":"implementer",'
                    '"objective":"Apply reviewer feedback.","depends_on":["review"]},'
                    '{"id":"review-r2","label":"Reviewer R2","role":"reviewer","objective":"Review the revision.",'
                    '"depends_on":["implement-r2"],"review_of":"implement-r2"}],'
                    '"cancel_task_ids":[],"complete":false,"quality_passed":false,"final_answer":""}'
                ),
                f"{run.run_id}:task:implement-r2": "Corrected implementation with regression coverage.",
                f"{run.run_id}:orchestrator:control:3": (
                    '{"summary":"Await the scheduled reviewer.","tasks":[],"cancel_task_ids":[],'
                    '"complete":false,"quality_passed":false,"final_answer":""}'
                ),
                f"{run.run_id}:task:review-r2": '{"approved":true,"feedback":"All requirements pass."}',
                f"{run.run_id}:orchestrator:control:4": (
                    '{"summary":"Reviewed and accepted.","tasks":[],"cancel_task_ids":[],'
                    '"complete":true,"quality_passed":true,'
                    '"final_answer":"The implementation is complete and verified."}'
                ),
            }
            output = outputs[client_message_id]
            if client_message_id == f"{run.run_id}:task:implement":
                service.link_generalist_directive(
                    workspace_id="default",
                    run_id=run.run_id,
                    source_runtime_turn_id="generalist-turn-2",
                )
            return output

        generalist_event = SimpleNamespace(
            event_id="generalist-final-1",
            turn_id="generalist-turn-1",
            event_type="runtime.output.final",
            payload={"text": "Preserve the public API and prioritize regression coverage."},
        )
        steering_event = SimpleNamespace(
            event_id="generalist-final-2",
            turn_id="generalist-turn-2",
            event_type="runtime.output.final",
            payload={"text": "Keep the revision small and finish quickly."},
        )
        source_turn = SimpleNamespace(
            turn_id="generalist-turn-1",
            status="active",
            input_text="Implement the requested redesign.",
        )

        class RuntimeStore:
            polls = 0

            def get_turn(self, _turn_id):
                if _turn_id == "generalist-turn-2":
                    return SimpleNamespace(turn_id=_turn_id, status="completed", input_text="Change direction.")
                self.polls += 1
                if self.polls > 1:
                    source_turn.status = "completed"
                return source_turn

            def list_events(self, _session_id):
                return [generalist_event, steering_event] if self.polls > 1 else []

        result = execute_orchestrated_run(
            service,
            SimpleNamespace(runtime_store=RuntimeStore()),
            workspace_id="default",
            run_id=run.run_id,
            turn_executor=execute_turn,
            agent_snapshot_resolver=lambda agent_type_id: replace(
                snapshot(),
                agent_type_id=agent_type_id,
                label="Coder Specialist",
            ),
            available_agent_type_ids=("agent-type-coder: Coder Specialist",),
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
        self.assertEqual(
            next(item for item in participants if item.participant_id == "implement").agent_type_id,
            "agent-type-coder",
        )
        self.assertIn("agent-type-coder: Coder Specialist", prompts[f"{run.run_id}:orchestrator:plan"])
        self.assertIn("Preserve the public API", prompts[f"{run.run_id}:orchestrator:plan"])
        self.assertIn("Implement the requested redesign", prompts[f"{run.run_id}:orchestrator:plan"])
        self.assertIn("Keep the revision small", prompts[f"{run.run_id}:orchestrator:control:1"])
        self.assertIn("Add the missing regression coverage", prompts[f"{run.run_id}:orchestrator:control:2"])
        self.assertIn("Dependency review", prompts[f"{run.run_id}:task:implement-r2"])
        self.assertIn("inter_agent.completion.decided", [event.event_type for event in events])
        self.assertIn("inter_agent.generalist.handoff_prepared", [event.event_type for event in events])
        self.assertEqual(
            [event.payload["trigger_task_id"] for event in events if event.event_type == "inter_agent.control.decision"],
            ["implement", "review", "implement-r2", "review-r2"],
        )
        self.assertEqual(
            next(event for event in events if event.event_type == "inter_agent.run.completed").participant_id,
            "orchestrator",
        )


if __name__ == "__main__":
    unittest.main()
