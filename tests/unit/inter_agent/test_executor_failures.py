from __future__ import annotations

import unittest

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.models import BudgetPolicySpec, EdgeSpec, InterAgentRunSpec
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_executor import (
    NOW,
    _participant,
    _root_session,
    _run_spec,
    _runtime_state,
    _runtime_store,
    _state,
)


class InterAgentExecutorFailureTest(unittest.TestCase):
    def _stores(self):
        repo_root = make_temp_repo_root(self)
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        runtime_store.save_session(_root_session(repo_root))
        runtime_store.save_state(_runtime_state())
        return repo_root, inter_agent_store, runtime_store

    def test_controlled_budget_failure_releases_running_reservation(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        spec = _run_spec(
            run_id="budget-failure-release",
            participants=[
                _participant("researcher", "Researcher"),
                _participant("reviewer", "Reviewer"),
            ],
        )
        spec = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "budget": BudgetPolicySpec(
                    max_participants=5,
                    max_concurrent_participants=2,
                    max_total_turns=1,
                    max_turns_per_participant=1,
                ),
            }
        )
        run = service.create_run(spec, now=NOW)

        with self.assertRaisesRegex(InterAgentOperationError, "max_total_turns"):
            execute_inter_agent_run(
                service,
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                controlled_participants={
                    "researcher": {"output_text": "first"},
                    "reviewer": {"output_text": "second"},
                },
                allow_synthetic_participants=True,
                project_summaries=False,
                now=NOW,
            )
        ledger = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        run_failed = next(event for event in events if event.event_type == "inter_agent.run.failed")

        self.assertEqual(ledger.running_participants, 0)
        self.assertEqual(ledger.turns_used, 1)
        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "failed")
        self.assertTrue(run_failed.payload.get("synthetic"))
        self.assertEqual(run_failed.payload.get("synthetic_source"), "controlled_payload")

    def test_handoff_execution_remains_schema_only(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="handoff",
                run_id="handoff-schema-only",
                edges=[EdgeSpec(source_id="orchestrator", target_id="researcher", kind="handed_off")],
            ),
            now=NOW,
        )

        with self.assertRaisesRegex(InterAgentOperationError, "schema/event-only"):
            execute_inter_agent_run(
                service,
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                input_text="Try handoff.",
                now=NOW,
            )

        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "created")
        self.assertEqual(runtime_store.list_sessions("default"), [runtime_store.get_session("root-session")])


if __name__ == "__main__":
    unittest.main()
