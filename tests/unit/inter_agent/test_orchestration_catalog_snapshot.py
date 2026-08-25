from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.orchestration_planner_catalog import OrchestrationPlannerCatalog
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class OrchestrationCatalogSnapshotTest(unittest.TestCase):
    def test_refreshes_at_safe_point_and_materializes_from_decision_snapshot(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        prompts: dict[str, str] = {}
        refresh_count = 0

        def catalog_provider():
            nonlocal refresh_count
            refresh_count += 1
            revision = f"revision-{refresh_count}"
            selected = replace(
                snapshot(),
                agent_type_id="agent-type-coder",
                label=f"Coder {revision}",
                revision_id=revision,
            )
            return SimpleNamespace(
                planner_catalog=OrchestrationPlannerCatalog.from_text_entries(
                    (f"agent-type-coder: Coder {revision}",)
                ),
                available_agent_type_ids=("agent-type-coder",),
                resolve=lambda _agent_type_id, value=selected: value,
            )

        def execute_turn(_participant, prompt, client_message_id, _invoked_skill_ids):
            prompts[client_message_id] = prompt
            if client_message_id.endswith(":orchestrator:plan"):
                return (
                    '{"summary":"Implement once.","tasks":['
                    '{"id":"implement","label":"Implement","role":"implementer",'
                    '"objective":"Implement.","depends_on":[],"agent_type_id":"agent-type-coder"}]}'
                )
            if client_message_id.endswith(":task:implement"):
                return "Implemented."
            raise InterAgentOperationError("stop after refreshed control prompt")

        runtime_event = SimpleNamespace(
            event_id="generalist-final",
            turn_id=run.source_runtime_turn_id,
            event_type="runtime.output.final",
            payload={"text": "Delegate the implementation."},
        )
        runtime_state = SimpleNamespace(
            runtime_store=SimpleNamespace(
                get_turn=lambda _turn_id: SimpleNamespace(
                    turn_id=run.source_runtime_turn_id,
                    status="completed",
                    input_text="Implement.",
                ),
                list_events=lambda _session_id: [runtime_event],
            )
        )

        with self.assertRaisesRegex(InterAgentOperationError, "refreshed control"):
            execute_orchestrated_run(
                service,
                runtime_state,
                workspace_id="default",
                run_id=run.run_id,
                turn_executor=execute_turn,
                catalog_snapshot_provider=catalog_provider,
            )

        participant = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        self.assertEqual(refresh_count, 2)
        self.assertIn("revision-1", prompts[f"{run.run_id}:orchestrator:plan"])
        self.assertIn("revision-2", prompts[f"{run.run_id}:orchestrator:control:1"])
        self.assertEqual(participant.agent_snapshot["revision_id"], "revision-1")


if __name__ == "__main__":
    unittest.main()
