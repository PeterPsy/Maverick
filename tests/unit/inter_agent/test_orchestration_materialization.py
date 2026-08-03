"""Fail-closed validation for persisted dynamic task participants."""

from __future__ import annotations

from dataclasses import replace
import unittest

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.orchestration_plan import parse_orchestration_plan
from core.inter_agent.orchestration_tasks import materialize_plan
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class OrchestrationMaterializationTest(unittest.TestCase):
    def test_recovery_rejects_persisted_participant_material_mismatches(self) -> None:
        mutations = {
            "kind": lambda participant: replace(participant, kind="system"),
            "execution mode": lambda participant: replace(participant, execution_mode="embedded_executor"),
            "label": lambda participant: replace(participant, label="Different task"),
            "agent type": lambda participant: replace(participant, agent_type_id="different-agent-type"),
            "snapshot digest": lambda participant: replace(participant, agent_snapshot_digest="tampered"),
            "authority": lambda participant: replace(participant, authority_grant_ids=["invented-grant"]),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field):
                store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
                service = InterAgentService(store)
                run = service.create_run(orchestrated_spec())
                orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
                plan = parse_orchestration_plan(
                    '{"summary":"One specialist.","tasks":['
                    '{"id":"implement","label":"Implementer","role":"implementer",'
                    '"objective":"Implement safely.","depends_on":[],"agent_type_id":"coder"}]}',
                    max_tasks=1,
                    require_review_gate=False,
                )
                participants = materialize_plan(
                    service,
                    run,
                    orchestrator,
                    plan,
                    snapshot_resolver=lambda agent_type_id: replace(snapshot(), agent_type_id=agent_type_id),
                )
                store.save_participant(mutate(participants["implement"]))

                with self.assertRaisesRegex(InterAgentValidationError, "does not match materialized task"):
                    materialize_plan(
                        service,
                        run,
                        orchestrator,
                        plan,
                        snapshot_resolver=lambda _agent_type_id: (_ for _ in ()).throw(
                            AssertionError("recovery must not consult the catalog")
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
