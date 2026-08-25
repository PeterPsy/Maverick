from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.orchestration_control import next_control_decision
from core.inter_agent.orchestration_plan import (
    OrchestrationPlan,
    OrchestrationTaskSpec,
    parse_orchestration_plan,
)
from core.inter_agent.orchestration_runtime import prepare_generalist_handoff
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.orchestration_state import OrchestrationControlState
from core.inter_agent.orchestration_tasks import (
    OrchestrationTaskResult,
    execute_task,
    materialize_plan,
    record_plan,
)
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class OrchestrationSchedulerTest(unittest.TestCase):
    def test_paused_run_rejects_a_queued_task_before_it_starts(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        plan = OrchestrationPlan(
            summary="One queued task.",
            tasks=(
                OrchestrationTaskSpec(
                    task_id="implement",
                    label="Implementer",
                    role="implementer",
                    objective="Implement only if the scheduler generation is still active.",
                ),
            ),
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participant = materialize_plan(service, run, orchestrator, plan)["implement"]
        running = replace(run, status="running")
        store.save_run(running)
        store.pause_run_if_active(run.run_id, workspace_id="default", now=run.updated_at)
        turn_started = False

        def execute_turn(*_args) -> str:
            nonlocal turn_started
            turn_started = True
            return "This stale task must not run."

        with self.assertRaisesRegex(InterAgentOperationError, "scheduler"):
            execute_task(service, running, plan.tasks[0], participant, "Implement.", {}, execute_turn)

        persisted = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertFalse(turn_started)
        self.assertEqual(persisted.status, "idle")
        self.assertIsNone(persisted.current_task_id)
        self.assertNotIn("inter_agent.task.started", [event.event_type for event in events])
        self.assertNotIn("inter_agent.task.completed", [event.event_type for event in events])

    def test_old_scheduler_generation_cannot_start_work_after_resume(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        plan = OrchestrationPlan(
            summary="One stale task.",
            tasks=(
                OrchestrationTaskSpec(
                    task_id="implement",
                    label="Implementer",
                    role="implementer",
                    objective="Reject work owned by the previous scheduler generation.",
                ),
            ),
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participant = materialize_plan(service, run, orchestrator, plan)["implement"]
        stale_run = replace(run, status="running")
        store.save_run(replace(stale_run, recovery_generation=1))

        with self.assertRaisesRegex(InterAgentOperationError, "generation"):
            execute_task(
                service,
                stale_run,
                plan.tasks[0],
                participant,
                "Implement.",
                {},
                lambda *_args: "This stale task must not run.",
            )

        persisted = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        self.assertEqual(persisted.status, "idle")
        self.assertIsNone(persisted.current_task_id)

    def test_task_finalization_cannot_overwrite_a_persisted_interrupt(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        plan = OrchestrationPlan(
            summary="Interrupt one active task.",
            tasks=(
                OrchestrationTaskSpec(
                    task_id="implement",
                    label="Implementer",
                    role="implementer",
                    objective="Return output only if cancellation did not win.",
                ),
            ),
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participant = materialize_plan(service, run, orchestrator, plan)["implement"]
        running = replace(run, status="running")
        store.save_run(running)
        original_scheduler_mutation = store.scheduler_mutation
        mutation_count = 0

        def pause_before_finalize(**kwargs):
            nonlocal mutation_count
            mutation_count += 1
            if mutation_count == 2:
                service.interrupt_run(
                    SimpleNamespace(runtime_store=SimpleNamespace()),
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="pause_before_task_finalize",
                )
            return original_scheduler_mutation(**kwargs)

        with patch.object(store, "scheduler_mutation", side_effect=pause_before_finalize):
            result = execute_task(
                service,
                running,
                plan.tasks[0],
                participant,
                "Implement.",
                {},
                lambda *_args: "Output produced immediately before cancellation.",
            )

        persisted_run = store.get_run(run.run_id, workspace_id="default")
        persisted = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        terminal_statuses = [
            event.payload["status"]
            for event in events
            if event.event_type == "inter_agent.task.completed" and event.payload.get("task_id") == "implement"
        ]
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(persisted_run.status, "paused")
        self.assertEqual(persisted.status, "cancelled")
        self.assertIsNone(persisted.current_task_id)
        self.assertEqual(terminal_statuses, ["cancelled"])

    def test_completion_rejects_failed_security_review_despite_earlier_approval(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        plan = parse_orchestration_plan(
            '{"summary":"Implementation with two reviews.","tasks":['
            '{"id":"implement","label":"Implementation","role":"implementer",'
            '"objective":"Produce the implementation.","depends_on":[]},'
            '{"id":"review","label":"Review","role":"reviewer",'
            '"objective":"Review correctness.","depends_on":["implement"],"review_of":"implement"},'
            '{"id":"security-review","label":"Security review","role":"security_reviewer",'
            '"objective":"Review security.","depends_on":["implement"],"review_of":"implement"}]}',
            max_tasks=3,
        )
        control = OrchestrationControlState(tasks={task.task_id: task for task in plan.tasks})
        control.results.update(
            {
                "implement": OrchestrationTaskResult("implement", "implement", "completed", "Implementation"),
                "review": OrchestrationTaskResult(
                    "review",
                    "review",
                    "completed",
                    '{"approved":true,"feedback":"Correct."}',
                ),
                "security-review": OrchestrationTaskResult(
                    "security-review",
                    "security-review",
                    "failed",
                    error="Security reviewer crashed.",
                ),
            }
        )

        with self.assertRaisesRegex(InterAgentValidationError, "approved final review"):
            next_control_decision(
                service,
                run,
                orchestrator,
                control,
                input_text="Implement safely.",
                trigger_task_id="security-review",
                execute_turn=lambda _participant, _prompt, _client_message_id, _invoked_skill_ids: (
                    '{"summary":"Use the earlier approval.","tasks":[],"cancel_task_ids":[],'
                    '"complete":true,"quality_passed":true,"final_answer":"Done."}'
                ),
                runtime_state=SimpleNamespace(),
                max_participants=4,
                available_agent_type_ids=(),
            )

        self.assertEqual(control.control_step, 0)

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
            lambda _participant, _prompt, _client_message_id, _invoked_skill_ids: (
                "Persisted implementation output."
            ),
        )
        store.save_run(replace(store.get_run(run.run_id, workspace_id="default"), status="recovering", recovery_generation=1))
        calls: list[str] = []
        catalog_resolution_calls: list[str] = []

        def unavailable_catalog(agent_type_id: str):
            catalog_resolution_calls.append(agent_type_id)
            raise AssertionError("persisted specialists must not be resolved from the catalog during recovery")

        def resume_turn(
            _participant,
            _prompt: str,
            client_message_id: str,
            _invoked_skill_ids: tuple[str, ...],
        ) -> str:
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
        skill_invocations: dict[str, tuple[str, ...]] = {}

        def execute_turn(
            participant,
            prompt: str,
            client_message_id: str,
            invoked_skill_ids: tuple[str, ...],
        ) -> str:
            prompts[client_message_id] = prompt
            skill_invocations[client_message_id] = invoked_skill_ids
            outputs = {
                f"{run.run_id}:orchestrator:plan": (
                    '{"summary":"Start with implementation.","tasks":['
                    '{"id":"implement","label":"Implementer","role":"implementer",'
                    '"objective":"Implement safely.","depends_on":[],"agent_type_id":"agent-type-coder",'
                    '"invoked_skill_ids":["storage"]}]}'
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
        self.assertEqual(skill_invocations[f"{run.run_id}:orchestrator:plan"], ())
        self.assertEqual(skill_invocations[f"{run.run_id}:task:implement"], ("storage",))
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
