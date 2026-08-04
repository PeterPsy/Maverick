from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService
from core.inter_agent.models import ParticipantSpec
from core.inter_agent.orchestration_plan import OrchestrationPlan, OrchestrationTaskSpec
from core.inter_agent.orchestration_state import load_control_state
from core.inter_agent.orchestration_tasks import materialize_plan, record_plan
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.lifecycle_service_sessions import create_child_runtime_session
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.service import queue_runtime_turn, record_runtime_event
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_service_runtime import _run_spec
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec, snapshot


class InterAgentRuntimeRecoveryTest(unittest.TestCase):
    def test_interrupt_before_child_link_commit_cancels_stale_participant_write(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        state = type("State", (), {"runtime_store": runtime_store})()
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        plan = _interruptible_plan()
        record_plan(service, run, plan)
        worker = materialize_plan(service, run, orchestrator, plan)["implement"]
        store.save_participant(
            worker.__class__(**{**worker.__dict__, "status": "running", "current_task_id": "implement"})
        )
        original_claim_session = store.claim_participant_runtime_session
        pause_triggered = False

        def pause_before_link_commit(**kwargs):
            nonlocal pause_triggered
            if kwargs["runtime_session_id"] == "late-link-session" and not pause_triggered:
                pause_triggered = True
                service.interrupt_run(
                    state,
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="pause_before_link_commit",
                    now=now + timedelta(seconds=1),
                )
            return original_claim_session(**kwargs)

        with (
            patch.object(store, "claim_participant_runtime_session", side_effect=pause_before_link_commit),
            self.assertRaisesRegex(InterAgentOperationError, "paused"),
        ):
            service.spawn_participant_runtime_session(
                runtime_store,
                workspace_id="default",
                run_id=run.run_id,
                participant_id=worker.participant_id,
                child_session_id="late-link-session",
                now=now,
            )

        paused = store.get_run(run.run_id, workspace_id="default")
        cancelled_worker = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        self.assertTrue(pause_triggered)
        self.assertEqual(paused.status, "paused")
        self.assertEqual(cancelled_worker.status, "cancelled")
        self.assertIsNone(cancelled_worker.current_task_id)
        self.assertEqual(load_control_state(service, paused).results["implement"].status, "cancelled")
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session("late-link-session")

    def test_interrupt_during_child_creation_cancels_task_and_deletes_late_session(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        state = type("State", (), {"runtime_store": runtime_store})()
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        plan = _interruptible_plan()
        record_plan(service, run, plan)
        participants = materialize_plan(service, run, orchestrator, plan)
        worker = participants["implement"]
        store.save_participant(
            worker.__class__(**{**worker.__dict__, "status": "running", "current_task_id": "implement"})
        )

        def create_then_interrupt(*args, **kwargs):
            child = create_child_runtime_session(*args, **kwargs)
            service.interrupt_run(
                state,
                workspace_id="default",
                run_id=run.run_id,
                reason="pause_during_spawn",
                now=now + timedelta(seconds=1),
            )
            return child

        with (
            patch("core.inter_agent.service.create_child_runtime_session", side_effect=create_then_interrupt),
            self.assertRaisesRegex(InterAgentOperationError, "paused"),
        ):
            service.spawn_participant_runtime_session(
                runtime_store,
                workspace_id="default",
                run_id=run.run_id,
                participant_id=worker.participant_id,
                child_session_id="late-child-session",
                now=now,
            )

        paused = store.get_run(run.run_id, workspace_id="default")
        cancelled_worker = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        control = load_control_state(service, paused)
        self.assertEqual(paused.status, "paused")
        self.assertEqual(cancelled_worker.status, "cancelled")
        self.assertIsNone(cancelled_worker.current_task_id)
        self.assertIsNone(cancelled_worker.runtime_session_id)
        self.assertEqual(control.results["implement"].status, "cancelled")
        late_runtime_root = Path(runtime_store.get_session("root-session").runtime_root).parent / "late-child-session"
        self.assertFalse(late_runtime_root.exists())
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session("late-child-session")

    def test_old_generation_cannot_claim_a_late_child_session(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        plan = _interruptible_plan()
        record_plan(service, run, plan)
        worker = materialize_plan(service, run, orchestrator, plan)["implement"]
        store.save_run(replace(run, status="running"))

        def create_then_advance_generation(*args, **kwargs):
            child = create_child_runtime_session(*args, **kwargs)
            current = store.get_run(run.run_id, workspace_id="default")
            store.save_run(replace(current, recovery_generation=1))
            return child

        with (
            patch(
                "core.inter_agent.service.create_child_runtime_session",
                side_effect=create_then_advance_generation,
            ),
            self.assertRaisesRegex(InterAgentOperationError, "generation changed"),
        ):
            service.spawn_participant_runtime_session(
                runtime_store,
                workspace_id="default",
                run_id=run.run_id,
                participant_id=worker.participant_id,
                child_session_id="stale-generation-session",
                expected_recovery_generation=0,
                now=now,
            )

        persisted_run = store.get_run(run.run_id, workspace_id="default")
        persisted_worker = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        stale_runtime_root = (
            Path(runtime_store.get_session("root-session").runtime_root).parent
            / "stale-generation-session"
        )
        self.assertEqual(persisted_run.recovery_generation, 1)
        self.assertEqual(persisted_worker.status, "idle")
        self.assertIsNone(persisted_worker.runtime_session_id)
        self.assertFalse(stale_runtime_root.exists())
        with self.assertRaises(RuntimeSessionNotFoundError):
            runtime_store.get_session("stale-generation-session")

    def test_interrupt_and_immediate_resume_preserve_cancelled_task_recovery(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        plan = _interruptible_plan()
        record_plan(service, run, plan)
        participants = materialize_plan(service, run, orchestrator, plan)
        service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id=orchestrator.participant_id,
            now=now,
        )
        worker, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id=participants["implement"].participant_id,
            now=now,
        )
        store.save_participant(
            worker.__class__(**{**worker.__dict__, "status": "running", "current_task_id": "implement"})
        )
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="active-implement-turn",
                session_id=child.session_id,
                workspace_id="default",
                status="active",
                input_text="Implement the task.",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )

        interrupted = service.interrupt_run(
            type("State", (), {"runtime_store": runtime_store})(),
            workspace_id="default",
            run_id=run.run_id,
            reason="user_pause",
            now=now + timedelta(seconds=1),
        )
        resumed = service.resume_run(
            workspace_id="default",
            run_id=run.run_id,
            reason="user_resume",
            now=now + timedelta(seconds=2),
        )
        control = load_control_state(service, resumed)

        resumed_orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        cancelled_worker = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        self.assertEqual(interrupted["run"].status, "paused")
        self.assertEqual(runtime_store.get_turn("active-implement-turn").status, "cancelled")
        self.assertEqual(resumed.status, "running")
        self.assertEqual(resumed.recovery_generation, 1)
        self.assertEqual(resumed_orchestrator.status, "idle")
        self.assertIsNone(resumed_orchestrator.runtime_session_id)
        self.assertEqual(cancelled_worker.status, "cancelled")
        self.assertIsNone(cancelled_worker.current_task_id)
        self.assertEqual(control.results["implement"].status, "cancelled")

    def test_startup_recovery_resets_orchestrated_workers_for_scheduler_replay(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        worker = service.add_participant(
            workspace_id="default",
            run_id=run.run_id,
            spec=ParticipantSpec(
                participant_id="implement",
                kind="agent",
                execution_mode="child_runtime_session",
                label="Implementer",
                agent_type_id="generalist",
                agent_snapshot=snapshot(),
            ),
            now=now,
        )
        store.save_participant(
            worker.__class__(
                **{
                    **worker.__dict__,
                    "runtime_session_id": "missing-worker-session",
                    "status": "running",
                    "current_task_id": "implement",
                }
            )
        )
        store.save_run(run.__class__(**{**run.__dict__, "status": "running"}))

        result = service.recover_non_terminal_runs(
            runtime_store,
            workspace_id="default",
            now=now + timedelta(seconds=1),
        )

        recovered_run = store.get_run(run.run_id, workspace_id="default")
        recovered_worker = store.get_participant("implement", workspace_id="default", run_id=run.run_id)
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="detail", limit=200).events
        self.assertEqual(result["recovered_runs"], 1)
        self.assertEqual(result["failed_runs"], 0)
        self.assertEqual(recovered_run.status, "recovering")
        self.assertEqual(recovered_run.recovery_generation, 1)
        self.assertEqual(recovered_worker.status, "idle")
        self.assertIsNone(recovered_worker.runtime_session_id)
        self.assertIn("inter_agent.task.retry_scheduled", [event.event_type for event in events])

    def test_startup_recovery_closes_async_root_turn_for_planning_run_without_children(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="recover-async-run"), now=now)
        service.mark_run_planning(workspace_id="default", run_id=run.run_id, now=now)
        turn = queue_runtime_turn(
            runtime_store,
            turn_id="root-turn-recover-async",
            session_id="root-session",
            input_text="Run async work.",
            now=now,
        )
        record_runtime_event(
            runtime_store,
            event_id="event-root-turn-recover-async",
            session_id="root-session",
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"inter_agent_run_id": run.run_id},
            now=now,
        )
        create_runtime_thread(
            runtime_store,
            workspace_id="default",
            thread_id="root-session",
            runtime_session_id="root-session",
            title="Async run",
            agent_label="chat",
            source_app_id="chat",
            now=now,
        )

        result = service.recover_non_terminal_runs(runtime_store, workspace_id="default", now=now + timedelta(seconds=1))

        recovered_run = store.get_run(run.run_id, workspace_id="default")
        recovered_turn = runtime_store.get_turn(turn.turn_id)
        root_thread = runtime_store.get_thread("root-session")
        root_event_types = [event.event_type for event in runtime_store.list_events("root-session")]
        self.assertEqual(result["failed_runs"], 1)
        self.assertEqual(result["closed_root_turns"], 1)
        self.assertEqual(recovered_run.status, "failed")
        self.assertEqual(recovered_turn.status, "cancelled")
        self.assertEqual(root_thread.availability, "free")
        self.assertIn("runtime.turn.cancelled", root_event_types)


def _runtime_store() -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=FakeCollection(),
            turns=FakeCollection(),
            events=FakeCollection(),
            processes=FakeCollection(),
            states=FakeCollection(),
            threads=FakeCollection(),
        )
    )


def _runtime_session(session_id: str, *, repo_root: Path) -> RuntimeSessionRecord:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    workspace_root = repo_root / "workspaces" / "default"
    runtime_root = workspace_root / "runtime" / "sessions" / session_id
    runtime_root.mkdir(parents=True, exist_ok=True)
    return RuntimeSessionRecord(
        session_id=session_id,
        workspace_id="default",
        agent_id="chat",
        status="running",
        requested_mode=None,
        effective_mode="sandbox",
        workspace_root=str(workspace_root),
        workdir=str(workspace_root),
        runtime_root=str(runtime_root),
        started_at=now,
        updated_at=now,
        ended_at=None,
        last_progress_at=now,
    )


def _runtime_state(session_id: str) -> RuntimeStateRecord:
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    return RuntimeStateRecord(
        session_id=session_id,
        workspace_id="default",
        current_turn_id=None,
        session_status="running",
        turn_status=None,
        last_progress_at=now,
        watchdog_deadline_at=None,
        forced_stop_reason=None,
        last_error_detail=None,
        updated_at=now,
    )


def _interruptible_plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        summary="Implement and review.",
        tasks=(
            OrchestrationTaskSpec(
                task_id="implement",
                label="Implement",
                role="implementer",
                objective="Implement the requested change.",
            ),
            OrchestrationTaskSpec(
                task_id="review",
                label="Review",
                role="reviewer",
                objective="Review the implementation.",
                depends_on=("implement",),
                review_of="implement",
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
