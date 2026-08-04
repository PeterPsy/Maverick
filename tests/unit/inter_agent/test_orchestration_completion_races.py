from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationCompletionRaceTest(unittest.TestCase):
    def test_completion_rejects_a_run_that_is_already_paused(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        store.save_run(replace(run, status="running"))
        store.pause_run_if_active(run.run_id, workspace_id="default", now=run.updated_at)

        with self.assertRaisesRegex(InterAgentOperationError, "paused"):
            service.decide_completion(
                workspace_id="default",
                run_id=run.run_id,
                participant_id="orchestrator",
                complete=True,
                quality_passed=True,
                summary="This stale completion must be rejected.",
                final_answer="Stale final answer.",
            )

        persisted_run = store.get_run(run.run_id, workspace_id="default")
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertEqual(persisted_run.status, "paused")
        self.assertEqual(orchestrator.status, "idle")
        self.assertNotIn("inter_agent.run.completed", [event.event_type for event in events])

    def test_pause_between_completion_decision_and_commit_wins_atomically(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        store.save_run(replace(run, status="running"))
        original_record_event = service.record_event
        paused = False

        def record_then_pause(event_run, **kwargs):
            nonlocal paused
            event = original_record_event(event_run, **kwargs)
            if kwargs["event_type"] == "inter_agent.completion.decided" and not paused:
                paused = True
                store.pause_run_if_active(run.run_id, workspace_id="default", now=event.created_at)
            return event

        with (
            patch.object(service, "record_event", side_effect=record_then_pause),
            self.assertRaisesRegex(InterAgentOperationError, "paused"),
        ):
            service.decide_completion(
                workspace_id="default",
                run_id=run.run_id,
                participant_id="orchestrator",
                complete=True,
                quality_passed=True,
                summary="Pause before committing completion.",
                final_answer="This answer must remain unapplied.",
            )

        persisted_run = store.get_run(run.run_id, workspace_id="default")
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertTrue(paused)
        self.assertEqual(persisted_run.status, "paused")
        self.assertEqual(orchestrator.status, "idle")
        self.assertNotIn("inter_agent.run.completed", [event.event_type for event in events])


if __name__ == "__main__":
    unittest.main()
