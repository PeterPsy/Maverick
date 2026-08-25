from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import parse_control_decision, parse_orchestration_plan
from core.inter_agent.orchestration_decisions import record_control_decision
from core.inter_agent.orchestration_runtime import prepare_generalist_handoff
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.orchestration_state import load_control_state
from core.inter_agent.orchestration_tasks import execute_task, materialize_plan, record_plan
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationDecisionRecoveryTest(unittest.TestCase):
    def test_replays_plan_and_result_before_500_later_detail_events(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        _record_persisted_plan(
            service,
            run,
            [
                {
                    "id": "implement",
                    "label": "Implement",
                    "role": "implementer",
                    "objective": "Implement once.",
                    "depends_on": [],
                }
            ],
        )
        _record_task_result(service, run, task_id="implement", output_text="Persisted result.")
        for index in range(500):
            service.record_event(
                run,
                event_type="inter_agent.task.started",
                participant_id=run.orchestrator_participant_id,
                visibility_plane="detail",
                correlation_id=f"detail-{index}",
                idempotency_key=f"{run.run_id}:detail:{index}",
                payload={"task_id": f"detail-{index}", "participant_id": run.orchestrator_participant_id},
            )

        page = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            limit=500,
        )
        control = load_control_state(service, replace(run, status="recovering"))

        self.assertTrue(page.has_more_before)
        self.assertEqual(tuple(control.tasks), ("implement",))
        self.assertEqual(control.results["implement"].output_text, "Persisted result.")

    def test_recovery_pages_through_more_than_500_state_events(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        _record_persisted_plan(
            service,
            run,
            [
                {
                    "id": "implement",
                    "label": "Implement",
                    "role": "implementer",
                    "objective": "Implement once.",
                    "depends_on": [],
                }
            ],
        )
        for attempt in range(1, 502):
            service.record_event(
                run,
                event_type="inter_agent.task.retry_scheduled",
                participant_id="implement",
                visibility_plane="detail",
                correlation_id="implement",
                idempotency_key=f"{run.run_id}:retry:{attempt}",
                payload={"task_id": "implement", "participant_id": "implement", "attempt": attempt},
            )

        recovery_events = store.list_recovery_events(
            run.run_id,
            workspace_id=run.workspace_id,
            event_types={"inter_agent.plan.summary_created", "inter_agent.task.retry_scheduled"},
        )
        control = load_control_state(service, replace(run, status="recovering"))

        self.assertEqual(len(recovery_events), 502)
        self.assertEqual(recovery_events[0].event_type, "inter_agent.plan.summary_created")
        self.assertEqual(
            [event.sequence for event in recovery_events],
            sorted(event.sequence for event in recovery_events),
        )
        self.assertEqual(tuple(control.tasks), ("implement",))
        self.assertEqual(control.attempts["implement"], 501)

    def test_recovery_fails_closed_when_a_terminal_task_result_is_missing(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        plan = parse_orchestration_plan(
            '{"summary":"Implement once.","tasks":['
            '{"id":"implement","label":"Implement","role":"implementer",'
            '"objective":"Implement once.","depends_on":[]}]}',
            max_tasks=1,
            require_review_gate=False,
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participants = materialize_plan(service, run, orchestrator, plan)
        store.save_participant(replace(participants["implement"], status="completed"))

        with self.assertRaisesRegex(InterAgentValidationError, "missing terminal task results"):
            load_control_state(service, replace(run, status="recovering"))

    def test_scheduler_marks_run_failed_when_recovery_validation_fails(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        plan = parse_orchestration_plan(
            '{"summary":"Implement once.","tasks":['
            '{"id":"implement","label":"Implement","role":"implementer",'
            '"objective":"Implement once.","depends_on":[]}]}',
            max_tasks=1,
            require_review_gate=False,
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participants = materialize_plan(service, run, orchestrator, plan)
        store.save_participant(replace(participants["implement"], status="completed"))
        store.save_run(replace(run, status="running"))

        with self.assertRaisesRegex(InterAgentValidationError, "missing terminal task results"):
            execute_orchestrated_run(
                service,
                SimpleNamespace(),
                workspace_id="default",
                run_id=run.run_id,
            )

        failed = store.get_run(run.run_id, workspace_id="default")
        self.assertEqual(failed.status, "failed")
        self.assertIsNotNone(failed.ended_at)

    def test_recovery_rejects_persisted_reviewer_without_review_of(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        _record_persisted_plan(
            service,
            run,
            [
                {
                    "id": "security-review",
                    "label": "Security review",
                    "role": "security_reviewer",
                    "objective": "Review security.",
                    "depends_on": ["implement"],
                }
            ],
        )

        with self.assertRaisesRegex(InterAgentValidationError, "review_of"):
            load_control_state(service, replace(run, status="recovering"))

    def test_recovery_rejects_persisted_plan_with_unknown_review_target(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        _record_persisted_plan(
            service,
            run,
            [
                {
                    "id": "security-review",
                    "label": "Security review",
                    "role": "security_reviewer",
                    "objective": "Review missing work.",
                    "depends_on": ["ghost"],
                    "review_of": "ghost",
                }
            ],
        )

        with self.assertRaisesRegex(InterAgentValidationError, "unknown dependencies"):
            load_control_state(service, replace(run, status="recovering"))

    def test_recovery_rejects_persisted_plan_with_dependency_cycle(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        _record_persisted_plan(
            service,
            run,
            [
                {
                    "id": "review-a",
                    "label": "Review A",
                    "role": "reviewer",
                    "objective": "Review B.",
                    "depends_on": ["review-b"],
                    "review_of": "review-b",
                },
                {
                    "id": "review-b",
                    "label": "Review B",
                    "role": "reviewer",
                    "objective": "Review A.",
                    "depends_on": ["review-a"],
                    "review_of": "review-a",
                },
            ],
        )

        with self.assertRaisesRegex(InterAgentValidationError, "cycle"):
            load_control_state(service, replace(run, status="recovering"))

    def test_replays_persisted_completion_without_asking_the_orchestrator_again(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        runtime_state = _prepare_handoff(service, run)
        plan = parse_orchestration_plan(
            '{"summary":"Implement and review.","tasks":['
            '{"id":"implement","label":"Implementer","role":"implementer",'
            '"objective":"Implement once.","depends_on":[]},'
            '{"id":"review","label":"Reviewer","role":"reviewer",'
            '"objective":"Review the result.","depends_on":["implement"],"review_of":"implement"}]}',
            max_tasks=2,
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participants = materialize_plan(service, run, orchestrator, plan)
        running = replace(run, status="running")
        store.save_run(running)
        implement_result = execute_task(
            service,
            running,
            plan.tasks[0],
            participants["implement"],
            "Recover completion.",
            {},
            lambda _participant, _prompt, _client_message_id, _invoked_skill_ids: "Persisted implementation.",
        )
        execute_task(
            service,
            running,
            plan.tasks[1],
            participants["review"],
            "Recover completion.",
            {"implement": implement_result.output_text},
            lambda _participant, _prompt, _client_message_id, _invoked_skill_ids: (
                '{"approved":true,"feedback":"Persisted implementation is valid."}'
            ),
        )
        decision = parse_control_decision(
            '{"summary":"Persisted final decision.","tasks":[],"cancel_task_ids":[],'
            '"complete":true,"quality_passed":true,"final_answer":"Use this persisted final answer."}',
            existing_tasks=plan.tasks,
            max_new_tasks=2,
        )
        record_control_decision(service, running, decision, control_step=1, trigger_task_id="review")
        recovery = service.recover_non_terminal_runs(runtime_state.runtime_store, workspace_id="default")

        result = execute_orchestrated_run(
            service,
            runtime_state,
            workspace_id="default",
            run_id=run.run_id,
            turn_executor=lambda *_args: (_ for _ in ()).throw(AssertionError("orchestrator must not run")),
        )

        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertEqual(result.run.status, "completed")
        self.assertEqual(result.final_answer, "Use this persisted final answer.")
        self.assertEqual(recovery["recovered_runs"], 1)
        self.assertEqual(
            [event.payload["control_step"] for event in events if event.event_type == "inter_agent.control.decision_applied"],
            [1],
        )

    def test_replays_persisted_cancellation_before_scheduling_any_task(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        runtime_state = _prepare_handoff(service, run)
        plan = parse_orchestration_plan(
            '{"summary":"Keep one branch.","tasks":['
            '{"id":"implement","label":"Implementer","role":"implementer",'
            '"objective":"Implement the selected branch.","depends_on":[]},'
            '{"id":"obsolete","label":"Obsolete branch","role":"researcher",'
            '"objective":"Work that should be cancelled.","depends_on":[]}]}',
            max_tasks=2,
            require_review_gate=False,
        )
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        record_plan(service, run, plan)
        participants = materialize_plan(service, run, orchestrator, plan)
        running = replace(run, status="running")
        store.save_run(running)
        execute_task(
            service,
            running,
            plan.tasks[0],
            participants["implement"],
            "Recover cancellation.",
            {},
            lambda _participant, _prompt, _client_message_id, _invoked_skill_ids: "Selected implementation.",
        )
        decision = parse_control_decision(
            '{"summary":"Cancel obsolete work and review.","tasks":['
            '{"id":"review","label":"Reviewer","role":"reviewer",'
            '"objective":"Review selected work.","depends_on":["implement"],"review_of":"implement"}],'
            '"cancel_task_ids":["obsolete"],"complete":false,"quality_passed":false,"final_answer":""}',
            existing_tasks=plan.tasks,
            max_new_tasks=2,
        )
        record_control_decision(service, running, decision, control_step=1, trigger_task_id="implement")
        recovery = service.recover_non_terminal_runs(runtime_state.runtime_store, workspace_id="default")
        calls: list[str] = []

        def resume_turn(
            _participant,
            _prompt: str,
            client_message_id: str,
            _invoked_skill_ids: tuple[str, ...],
        ) -> str:
            calls.append(client_message_id)
            return {
                f"{run.run_id}:task:review": '{"approved":true,"feedback":"Selected work is valid."}',
                f"{run.run_id}:orchestrator:control:2": (
                    '{"summary":"Recovered and approved.","tasks":[],"cancel_task_ids":[],'
                    '"complete":true,"quality_passed":true,"final_answer":"Recovered safely."}'
                ),
            }[client_message_id]

        result = execute_orchestrated_run(
            service,
            runtime_state,
            workspace_id="default",
            run_id=run.run_id,
            turn_executor=resume_turn,
        )

        obsolete = store.get_participant("obsolete", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertEqual(result.run.status, "completed")
        self.assertEqual(obsolete.status, "cancelled")
        self.assertEqual(recovery["recovered_runs"], 1)
        self.assertNotIn(f"{run.run_id}:task:obsolete", calls)
        self.assertEqual(
            [event.payload["control_step"] for event in events if event.event_type == "inter_agent.control.decision_applied"],
            [1, 2],
        )


def _prepare_handoff(service: InterAgentService, run) -> SimpleNamespace:
    final_event = SimpleNamespace(
        event_id=f"{run.run_id}-generalist-final",
        turn_id=run.source_runtime_turn_id,
        event_type="runtime.output.final",
        payload={"text": "Persisted generalist analysis."},
    )
    runtime_store = SimpleNamespace(
        get_turn=lambda _turn_id: SimpleNamespace(
            turn_id=run.source_runtime_turn_id,
            status="completed",
            input_text="Recover this orchestration.",
        ),
        list_events=lambda _session_id: [final_event],
    )
    state = SimpleNamespace(runtime_store=runtime_store)
    prepare_generalist_handoff(service, state, run)
    return state


def _record_persisted_plan(service: InterAgentService, run, tasks: list[dict[str, object]]) -> None:
    service.record_event(
        run,
        event_type="inter_agent.plan.summary_created",
        participant_id=run.orchestrator_participant_id,
        visibility_plane="summary",
        payload={"summary": "Persisted orchestration plan.", "tasks": tasks},
    )


def _record_task_result(service: InterAgentService, run, *, task_id: str, output_text: str) -> None:
    service.record_event(
        run,
        event_type="inter_agent.task.completed",
        participant_id=task_id,
        visibility_plane="detail",
        correlation_id=task_id,
        payload={
            "task_id": task_id,
            "participant_id": task_id,
            "status": "completed",
            "output_text": output_text,
            "error": None,
        },
    )


if __name__ == "__main__":
    unittest.main()
