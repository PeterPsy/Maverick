from __future__ import annotations

import unittest

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import (
    parse_control_decision,
    parse_completion_decision,
    parse_orchestration_plan,
    parse_review_decision,
)


class OrchestrationPlanTest(unittest.TestCase):
    def test_parses_dependency_plan_and_quality_decisions(self) -> None:
        plan = parse_orchestration_plan(
            """```json
            {
              "summary": "Implement then review.",
              "tasks": [
                {"id": "implement", "label": "Implementer", "role": "implementer", "objective": "Build it.", "depends_on": []},
                {"id": "review", "label": "Reviewer", "role": "reviewer", "objective": "Review it.", "depends_on": ["implement"], "review_of": "implement"}
              ]
            }
            ```""",
            max_tasks=4,
        )
        review = parse_review_decision('{"approved": false, "feedback": "Add a regression test."}')
        completion = parse_completion_decision(
            '{"complete": true, "quality_passed": true, "summary": "Accepted.", "final_answer": "Ready."}'
        )

        self.assertEqual([task.task_id for task in plan.tasks], ["implement", "review"])
        self.assertFalse(review.approved)
        self.assertTrue(completion.complete)

        control = parse_control_decision(
            '{"summary":"Add revision.","tasks":['
            '{"id":"implement-r2","label":"Implementer R2","role":"implementer","objective":"Revise.",'
            '"depends_on":["review"],"agent_type_id":"coder"},'
            '{"id":"review-r2","label":"Reviewer R2","role":"reviewer","objective":"Review again.",'
            '"depends_on":["implement-r2"],"review_of":"implement-r2"}],'
            '"cancel_task_ids":[],"complete":false,"quality_passed":false,"final_answer":""}',
            existing_tasks=plan.tasks,
            max_new_tasks=2,
        )
        self.assertEqual([task.task_id for task in control.tasks], ["implement-r2", "review-r2"])
        self.assertEqual(control.tasks[0].agent_type_id, "coder")

    def test_rejects_unknown_dependencies_cycles_and_missing_review_gate(self) -> None:
        cases = [
            (
                '{"tasks":[{"id":"implement","label":"Implementer","role":"implementer","objective":"Build.","depends_on":["missing"]}]}',
                "unknown dependencies",
            ),
            (
                '{"tasks":['
                '{"id":"implement","label":"Implementer","role":"implementer","objective":"Build.","depends_on":["review"]},'
                '{"id":"review","label":"Reviewer","role":"reviewer","objective":"Review.","depends_on":["implement"],"review_of":"implement"}'
                "]}",
                "cycle",
            ),
            (
                '{"tasks":[{"id":"research","label":"Researcher","role":"researcher","objective":"Research.","depends_on":[]}]}',
                "quality gate",
            ),
        ]
        for payload, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(InterAgentValidationError, message):
                parse_orchestration_plan(payload, max_tasks=4)


if __name__ == "__main__":
    unittest.main()
