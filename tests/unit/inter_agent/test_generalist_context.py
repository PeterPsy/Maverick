from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.generalist_context import (
    generalist_orchestration_context,
    input_text_with_generalist_orchestration_context,
)
from core.inter_agent.orchestration_plan import parse_orchestration_plan
from core.inter_agent.orchestration_state import OrchestrationControlState
from core.inter_agent.orchestration_tasks import OrchestrationTaskResult, execute_task, materialize_plan, record_plan
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class GeneralistOrchestrationContextTest(unittest.TestCase):
    def test_projects_bounded_session_linked_status_before_the_generalist_answers(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        plan = parse_orchestration_plan(
            '{"summary":"Implement and review.","tasks":['
            '{"id":"implement","label":"Implementer","role":"implementer",'
            '"objective":"Implement the change.","depends_on":[]},'
            '{"id":"review","label":"Reviewer","role":"reviewer",'
            '"objective":"Review the implementation.","depends_on":["implement"],"review_of":"implement"}]}',
            max_tasks=2,
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
            "Implement it.",
            {},
            lambda _participant, _prompt, _client_message_id: (
                "Implementation completed with regression coverage. API_KEY=unsafe-runtime-secret"
            ),
        )
        service.record_event(
            running,
            event_type="inter_agent.artifact.created",
            participant_id="implement",
            visibility_plane="detail",
            payload={
                "artifact_refs": [
                    {
                        "file_id": "file-1",
                        "workspace_relative_path": "storage/generated/report.md",
                        "secret": "must-not-leak",
                    }
                ],
                "partial_output": "unsafe raw output",
            },
        )

        context = generalist_orchestration_context(
            store,
            workspace_id="default",
            root_runtime_session_id="root-session",
        )
        provider_input = input_text_with_generalist_orchestration_context(
            SimpleNamespace(inter_agent_store=store),
            session=SimpleNamespace(workspace_id="default", session_id="root-session"),
            input_text="Come sta andando?",
        )

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["run_id"], run.run_id)
        self.assertEqual(context["status"], "running")
        self.assertEqual(context["progress"]["completed_tasks"], 1)
        self.assertEqual(context["progress"]["pending_tasks"], 1)
        self.assertEqual(context["quality_gate"]["status"], "pending")
        self.assertEqual(
            context["tasks"][0]["result_summary"],
            "Implementation completed with regression coverage. API_KEY=<redacted>",
        )
        self.assertEqual(
            context["artifacts"],
            [{"file_id": "file-1", "workspace_relative_path": "storage/generated/report.md"}],
        )
        self.assertIn("Come sta andando?", provider_input)
        self.assertIn("Maverick governed orchestration read", provider_input)
        self.assertIn("Implementation completed with regression coverage", provider_input)
        self.assertNotIn("unsafe-runtime-secret", provider_input)
        self.assertNotIn("must-not-leak", provider_input)
        self.assertNotIn("unsafe raw output", provider_input)

    def test_approved_review_becomes_stale_after_new_material_work(self) -> None:
        plan = parse_orchestration_plan(
            '{"summary":"Revision chain.","tasks":['
            '{"id":"implement-a","label":"Implementation A","role":"implementer",'
            '"objective":"Produce A.","depends_on":[]},'
            '{"id":"review-a","label":"Review A","role":"reviewer",'
            '"objective":"Review A.","depends_on":["implement-a"],"review_of":"implement-a"},'
            '{"id":"implement-b","label":"Implementation B","role":"implementer",'
            '"objective":"Produce B.","depends_on":["review-a"]},'
            '{"id":"review-b","label":"Review B","role":"reviewer",'
            '"objective":"Review B.","depends_on":["implement-b"],"review_of":"implement-b"}]}',
            max_tasks=4,
        )
        control = OrchestrationControlState(tasks={task.task_id: task for task in plan.tasks})
        control.results.update(
            {
                "implement-a": OrchestrationTaskResult("implement-a", "implement-a", "completed", "A"),
                "review-a": OrchestrationTaskResult(
                    "review-a",
                    "review-a",
                    "completed",
                    '{"approved":true,"feedback":"A is approved."}',
                ),
                "implement-b": OrchestrationTaskResult("implement-b", "implement-b", "completed", "B"),
            }
        )

        stale = control.quality_gate_status()

        self.assertFalse(stale.passed)
        self.assertEqual(stale.frontier_task_ids, ("implement-b",))
        self.assertEqual(control.approved_review_task_ids(), ("review-a",))

        control.results["review-b"] = OrchestrationTaskResult(
            "review-b",
            "review-b",
            "completed",
            '{"approved":true,"feedback":"B is approved."}',
        )

        current = control.quality_gate_status()
        self.assertTrue(current.passed)
        self.assertEqual(current.review_task_id, "review-b")

    def test_rejected_review_vetoes_an_older_parallel_approval(self) -> None:
        plan = parse_orchestration_plan(
            '{"summary":"Parallel reviews.","tasks":['
            '{"id":"implement","label":"Implementation","role":"implementer",'
            '"objective":"Produce the implementation.","depends_on":[]},'
            '{"id":"review","label":"Review","role":"reviewer",'
            '"objective":"Review correctness.","depends_on":["implement"],"review_of":"implement"},'
            '{"id":"security-review","label":"Security review","role":"security_reviewer",'
            '"objective":"Review security.","depends_on":["implement"],"review_of":"implement"},'
            '{"id":"revision","label":"Security revision","role":"implementer",'
            '"objective":"Resolve the critical issue.","depends_on":["security-review"]},'
            '{"id":"final-review","label":"Final review","role":"security_reviewer",'
            '"objective":"Review the security revision.","depends_on":["revision"],"review_of":"revision"}]}',
            max_tasks=5,
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
                    "completed",
                    '{"approved":false,"feedback":"Critical issue."}',
                ),
            }
        )

        status = control.quality_gate_status()

        self.assertFalse(status.passed)
        self.assertEqual(status.frontier_task_ids, ("implement",))
        self.assertEqual(control.approved_review_task_ids(), ("review",))
        self.assertEqual(status.blocking_review_task_ids, ("security-review",))

        control.results["security-review"] = OrchestrationTaskResult(
            "security-review",
            "security-review",
            "completed",
            "malformed security verdict",
        )
        self.assertEqual(control.quality_gate_status().blocking_review_task_ids, ("security-review",))

        control.results["revision"] = OrchestrationTaskResult(
            "revision",
            "revision",
            "completed",
            "Critical issue resolved.",
        )
        control.results["final-review"] = OrchestrationTaskResult(
            "final-review",
            "final-review",
            "completed",
            '{"approved":true,"feedback":"Security issue resolved."}',
        )

        resolved = control.quality_gate_status()

        self.assertTrue(resolved.passed)
        self.assertEqual(resolved.frontier_task_ids, ("revision",))
        self.assertEqual(resolved.review_task_id, "final-review")
        self.assertEqual(resolved.blocking_review_task_ids, ())


if __name__ == "__main__":
    unittest.main()
