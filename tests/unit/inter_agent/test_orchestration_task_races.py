from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest

from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationTaskRaceTest(unittest.TestCase):
    def test_queued_future_cannot_start_or_fail_after_run_pause(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        spec = orchestrated_spec()
        spec = replace(
            spec,
            budget=replace(spec.budget, max_concurrent_participants=1),
            idempotency_key="queued-future-pause-race",
        )
        run = service.create_run(spec)
        generalist_event = SimpleNamespace(
            event_id="generalist-final-pause-race",
            turn_id=run.source_runtime_turn_id,
            event_type="runtime.output.final",
            payload={"text": "Schedule both independent tasks."},
        )
        runtime_store = SimpleNamespace(
            get_turn=lambda _turn_id: SimpleNamespace(
                turn_id=run.source_runtime_turn_id,
                status="completed",
                input_text="Run both tasks.",
            ),
            list_events=lambda _session_id: [generalist_event],
        )
        runtime_state = SimpleNamespace(runtime_store=runtime_store)
        calls: list[str] = []

        def execute_turn(_participant, _prompt: str, client_message_id: str) -> str:
            calls.append(client_message_id)
            if client_message_id == f"{run.run_id}:orchestrator:plan":
                return (
                    '{"summary":"Two independent tasks.","tasks":['
                    '{"id":"first","label":"First","role":"implementer",'
                    '"objective":"Run first.","depends_on":[]},'
                    '{"id":"second","label":"Second","role":"researcher",'
                    '"objective":"Stay queued until first finishes.","depends_on":[]}]}'
                )
            if client_message_id == f"{run.run_id}:task:first":
                service.interrupt_run(
                    runtime_state,
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="pause_while_second_future_is_queued",
                )
                return "First output lost to the persisted pause."
            raise AssertionError(f"stale queued work executed: {client_message_id}")

        result = execute_orchestrated_run(
            service,
            runtime_state,
            workspace_id="default",
            run_id=run.run_id,
            turn_executor=execute_turn,
        )

        first = store.get_participant("first", workspace_id="default", run_id=run.run_id)
        second = store.get_participant("second", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertEqual(result.run.status, "paused")
        self.assertEqual(first.status, "cancelled")
        self.assertEqual(second.status, "idle")
        self.assertIsNone(second.current_task_id)
        self.assertEqual(
            calls,
            [f"{run.run_id}:orchestrator:plan", f"{run.run_id}:task:first"],
        )
        self.assertNotIn("inter_agent.run.failed", [event.event_type for event in events])
        self.assertFalse(
            any(
                event.event_type == "inter_agent.task.completed"
                and event.payload.get("task_id") == "second"
                for event in events
            )
        )


if __name__ == "__main__":
    unittest.main()
