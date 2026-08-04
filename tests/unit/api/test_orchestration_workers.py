from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.api.orchestration_workers import resume_orchestrated_execution_worker, resume_recovering_orchestrations
from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationWorkerRecoveryTest(unittest.TestCase):
    def test_resume_waits_for_previous_owner_before_starting_replacement(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        store.save_run(run.__class__(**{**run.__dict__, "status": "paused"}))
        state = SimpleNamespace(inter_agent_store=store)
        lifecycle: list[str] = []

        resumed = resume_orchestrated_execution_worker(
            state,
            service,
            workspace_id="default",
            run_id=run.run_id,
            reason="test_resume",
            wait_worker=lambda **_kwargs: lifecycle.append("wait") or True,
            start_worker=lambda *_args, **_kwargs: lifecycle.append("start") or True,
        )

        self.assertEqual(resumed.status, "running")
        self.assertEqual(lifecycle, ["wait", "start"])

    def test_resume_keeps_run_paused_when_previous_owner_does_not_stop(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        store.save_run(run.__class__(**{**run.__dict__, "status": "paused"}))

        with self.assertRaisesRegex(InterAgentOperationError, "still stopping"):
            resume_orchestrated_execution_worker(
                SimpleNamespace(inter_agent_store=store),
                service,
                workspace_id="default",
                run_id=run.run_id,
                reason="test_resume",
                wait_worker=lambda **_kwargs: False,
                start_worker=lambda *_args, **_kwargs: True,
            )

        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "paused")

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
