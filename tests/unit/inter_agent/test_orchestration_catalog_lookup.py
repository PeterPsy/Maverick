from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.orchestration_agent_capabilities import (
    CATALOG_AVAILABLE,
    EnabledWorkspaceSkillCatalog,
    build_orchestration_planner_catalog,
)
from core.inter_agent.orchestration_control import create_initial_plan, next_control_decision
from core.inter_agent.orchestration_plan import OrchestrationTaskSpec
from core.inter_agent.orchestration_state import OrchestrationControlState
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class OrchestrationCatalogLookupTest(unittest.TestCase):
    def test_direct_prefix_lookup_reaches_last_skill_with_constant_turns(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        skill_ids = tuple(f"skill-{index:04d}-" + "x" * 48 for index in range(600))
        catalog = _planner_catalog(skill_ids)
        scope = catalog.initial_page().skill_scope_tokens[0]
        calls: list[tuple[str, str]] = []

        def execute_turn(_participant, prompt, client_message_id, _invoked_skill_ids):
            calls.append((client_message_id, prompt))
            if len(calls) > 8:
                raise AssertionError("catalog lookup exhausted the participant turn budget")
            if client_message_id.endswith(":plan"):
                return (
                    '{"catalog_lookup":{"skill_scope":"'
                    + scope
                    + '","skill_prefix":"skill-0599-"}}'
                )
            return (
                '{"summary":"Ready.","tasks":[{"id":"implement","label":"Implement",'
                '"role":"implementer","objective":"Implement the change.","depends_on":[],'
                '"invoked_skill_ids":["'
                + skill_ids[-1]
                + '"]}]}'
            )

        plan = create_initial_plan(
            service,
            run,
            orchestrator,
            OrchestrationControlState(),
            "Implement the change.",
            "Delegate it.",
            execute_turn,
            SimpleNamespace(),
            max_initial_tasks=1,
            available_agent_type_ids=(),
            planner_catalog=catalog,
        )

        self.assertEqual(len(calls), 2)
        self.assertIn(skill_ids[-1], calls[1][1])
        self.assertEqual(plan.tasks[0].invoked_skill_ids, (skill_ids[-1],))

    def test_initial_planner_can_page_skill_catalog_before_persistable_plan(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        catalog = _planner_catalog(
            tuple(f"skill-{index:03d}-" + "x" * 48 for index in range(200))
        )
        next_cursor = next(
            cursor for cursor in catalog.initial_page().next_cursors if cursor.startswith("skills:")
        )
        calls: list[tuple[str, str]] = []

        def execute_turn(_participant, prompt, client_message_id, _invoked_skill_ids):
            calls.append((client_message_id, prompt))
            if client_message_id.endswith(":plan"):
                return '{"catalog_lookup":{"cursor":"' + next_cursor + '"}}'
            return (
                '{"summary":"Ready.","tasks":[{"id":"implement","label":"Implement",'
                '"role":"implementer","objective":"Implement the change.","depends_on":[]}]}'
            )

        plan = create_initial_plan(
            service,
            run,
            orchestrator,
            OrchestrationControlState(),
            "Implement the change.",
            "Delegate it.",
            execute_turn,
            SimpleNamespace(),
            max_initial_tasks=1,
            available_agent_type_ids=(),
            planner_catalog=catalog,
        )

        self.assertEqual(plan.tasks[0].task_id, "implement")
        self.assertEqual(
            [client_message_id for client_message_id, _prompt in calls],
            [f"{run.run_id}:orchestrator:plan", f"{run.run_id}:orchestrator:plan:catalog:1"],
        )
        self.assertIn(next_cursor.rsplit(":", 1)[1], calls[1][1])

    def test_control_lookup_does_not_resend_inline_skill_list(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        task = OrchestrationTaskSpec(
            task_id="implement",
            label="Implement",
            role="implementer",
            objective="Implement the change.",
        )
        control = OrchestrationControlState(tasks={task.task_id: task})
        catalog = _planner_catalog(("storage-ops",))
        cursor = next(item for item in catalog.index_page().next_cursors if item.startswith("skills:"))
        calls: list[tuple[str, str]] = []

        def execute_turn(_participant, prompt, client_message_id, _invoked_skill_ids):
            calls.append((client_message_id, prompt))
            if client_message_id.endswith(":control:1"):
                return '{"catalog_lookup":{"cursor":"' + cursor + '"}}'
            return (
                '{"summary":"Wait for implementation.","tasks":[],"cancel_task_ids":[],'
                '"complete":false,"quality_passed":false,"final_answer":""}'
            )

        next_control_decision(
            service,
            run,
            orchestrator,
            control,
            input_text="Implement the change.",
            trigger_task_id=None,
            execute_turn=execute_turn,
            runtime_state=SimpleNamespace(),
            max_participants=4,
            available_agent_type_ids=(),
            planner_catalog=catalog,
        )

        self.assertNotIn("storage-ops", calls[0][1])
        self.assertIn("storage-ops", calls[1][1])
        self.assertEqual(calls[1][0], f"{run.run_id}:orchestrator:control:1:catalog:1")


def _planner_catalog(skill_ids: tuple[str, ...]):
    return build_orchestration_planner_catalog(
        replace(snapshot(), skill_activation_mode="explicit", skill_ids=[]),
        [],
        enabled_skills=EnabledWorkspaceSkillCatalog(
            state=CATALOG_AVAILABLE,
            skill_ids=skill_ids,
        ),
    )


if __name__ == "__main__":
    unittest.main()
