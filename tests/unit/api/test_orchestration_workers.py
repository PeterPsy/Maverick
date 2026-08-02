from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.api.orchestration_workers import resume_recovering_orchestrations
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationWorkerRecoveryTest(unittest.TestCase):
    def test_enqueues_recovering_orchestrated_runs_only(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        store.save_run(run.__class__(**{**run.__dict__, "status": "recovering"}))
        state = SimpleNamespace(
            inter_agent_store=store,
            workspace_store=SimpleNamespace(list_workspaces=lambda: [SimpleNamespace(workspace_id="default")]),
        )
        starts: list[tuple[str, str]] = []

        resumed = resume_recovering_orchestrations(
            state,
            start_worker=lambda _state, *, workspace_id, run_id: (
                starts.append((workspace_id, run_id)) or True
            ),
        )

        self.assertEqual(resumed, (run.run_id,))
        self.assertEqual(starts, [("default", run.run_id)])


if __name__ == "__main__":
    unittest.main()
