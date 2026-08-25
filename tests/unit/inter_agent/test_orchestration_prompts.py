from __future__ import annotations

import unittest

from core.inter_agent.orchestration_plan import OrchestrationTaskSpec
from core.inter_agent.orchestration_prompts import control_prompt, planning_prompt
from core.inter_agent.orchestration_tasks import OrchestrationTaskResult


class OrchestrationPromptsTest(unittest.TestCase):
    def test_control_ledger_exposes_bounded_failure_cause(self) -> None:
        task = OrchestrationTaskSpec(
            task_id="storage-task",
            label="Storage task",
            role="implementer",
            objective="Store the generated report.",
        )
        prompt = control_prompt(
            "Generate and store a report.",
            (task,),
            {
                task.task_id: OrchestrationTaskResult(
                    task.task_id,
                    task.task_id,
                    "failed",
                    "",
                    error="Skill invocation is outside the session allowlist.",
                )
            },
            trigger_task_id=task.task_id,
            directives=[],
            available_agent_types=[
                "storage-agent: Storage Agent [skill mode=explicit; allowed skill ids=storage-ops]"
            ],
        )

        self.assertIn("error=Skill invocation is outside the session allowlist.", prompt)
        self.assertIn("skill mode=explicit; allowed skill ids=storage-ops", prompt)

    def test_planning_contract_explains_explicit_catalog_capabilities(self) -> None:
        prompt = planning_prompt(
            "Store the report.",
            "Delegate storage work.",
            "multi",
            [],
            ["storage-agent: Storage Agent [skill mode=explicit; allowed skill ids=storage-ops]"],
        )

        self.assertIn("For an explicit agent", prompt)
        self.assertIn("exact task-required IDs", prompt)


if __name__ == "__main__":
    unittest.main()
