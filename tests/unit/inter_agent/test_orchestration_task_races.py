from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from threading import Event, Thread, current_thread
import unittest
from unittest.mock import patch

from core.inter_agent.models import ParticipantSpec
from core.inter_agent.orchestration_scheduler import execute_orchestrated_run
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class OrchestrationTaskRaceTest(unittest.TestCase):
    def test_interrupt_snapshots_participant_after_competing_task_claim(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        service = InterAgentService(store)
        run = service.create_run(orchestrated_spec())
        store.save_run(replace(run, status="running"))
        lock_held = Event()
        allow_materialization = Event()
        participant_listed = Event()
        thread_errors: list[BaseException] = []
        interrupted: dict[str, object] = {}
        original_list_participants = store.list_participants

        def observed_list_participants(run_id: str, *, workspace_id: str):
            participants = original_list_participants(run_id, workspace_id=workspace_id)
            if current_thread().name == "interrupt-after-task-claim":
                participant_listed.set()
            return participants

        def materialize_and_claim() -> None:
            try:
                with store._workspace_lock("default"):
                    lock_held.set()
                    if not allow_materialization.wait(timeout=2):
                        raise AssertionError("interrupt did not reach the participant snapshot")
                    participant = service.add_participant(
                        workspace_id="default",
                        run_id=run.run_id,
                        spec=ParticipantSpec(
                            participant_id="implement",
                            kind="agent",
                            execution_mode="child_runtime_session",
                            label="Implement",
                            agent_type_id="generalist",
                            agent_snapshot=snapshot(),
                        ),
                    )
                    store.save_participant(
                        replace(participant, status="running", current_task_id="implement")
                    )
            except BaseException as exc:
                thread_errors.append(exc)

        def interrupt() -> None:
            try:
                interrupted.update(
                    service.interrupt_run(
                        SimpleNamespace(runtime_store=SimpleNamespace()),
                        workspace_id="default",
                        run_id=run.run_id,
                        reason="pause_after_competing_task_claim",
                    )
                )
            except BaseException as exc:
                thread_errors.append(exc)

        worker = Thread(target=materialize_and_claim, name="materialize-before-pause")
        interrupter = Thread(target=interrupt, name="interrupt-after-task-claim")
        with patch.object(store, "list_participants", side_effect=observed_list_participants):
            worker.start()
            self.assertTrue(lock_held.wait(timeout=1))
            interrupter.start()
            participant_listed.wait(timeout=0.2)
            allow_materialization.set()
            worker.join(timeout=2)
            interrupter.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(interrupter.is_alive())
        self.assertEqual(thread_errors, [])
        participant = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(
            run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=200,
        ).events
        self.assertEqual(interrupted["run"].status, "paused")
        self.assertEqual(participant.status, "cancelled")
        self.assertIsNone(participant.current_task_id)
        self.assertEqual(
            [
                event.payload.get("status")
                for event in events
                if event.event_type == "inter_agent.task.completed"
                and event.payload.get("task_id") == "implement"
            ],
            ["cancelled"],
        )

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
