from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.orchestration_plan import parse_control_decision, parse_orchestration_plan
from core.inter_agent.orchestration_decisions import record_control_decision
from core.inter_agent.orchestration_runtime import prepare_generalist_handoff
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.orchestration_tasks import execute_task, materialize_plan, record_plan
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationDecisionRecoveryTest(unittest.TestCase):
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
            lambda _participant, _prompt, _client_message_id: "Persisted implementation.",
        )
        execute_task(
            service,
            running,
            plan.tasks[1],
            participants["review"],
            "Recover completion.",
            {"implement": implement_result.output_text},
            lambda _participant, _prompt, _client_message_id: (
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
            lambda _participant, _prompt, _client_message_id: "Selected implementation.",
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

        def resume_turn(_participant, _prompt: str, client_message_id: str) -> str:
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


if __name__ == "__main__":
    unittest.main()
