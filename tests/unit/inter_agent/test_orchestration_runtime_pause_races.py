from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from core.inter_agent import service as service_module
from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.turn_submission import submit_runtime_turn_async
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent import test_service_runtime as runtime_test_support
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationRuntimePauseRaceTest(unittest.TestCase):
    def test_cancelled_turn_snapshot_cannot_reactivate_stopped_session(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        helpers = runtime_test_support.InterAgentRuntimeServiceTest()
        runtime_store = helpers._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(helpers._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(helpers._runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        _participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="orchestrator",
            now=now,
        )
        child = runtime_store.save_session(
            replace(child, runtime_mode="plain_hosted_chat", skill_ids=[], skill_catalog_app_id=None)
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            inter_agent_store=store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
            repository_root=repo_root,
        )
        provider_started = False

        class ImmediateThread:
            def __init__(self, *, target, name, daemon) -> None:
                self.target = target

            def start(self) -> None:
                self.target()

        def interrupt_after_worker_snapshot(_turn, _events) -> None:
            interrupted = service.interrupt_run(
                state,
                workspace_id="default",
                run_id=run.run_id,
                reason="pause_after_worker_snapshot",
                now=now,
            )
            self.assertEqual(interrupted["run"].status, "paused")

        def execute_provider(*_args, **_kwargs):
            nonlocal provider_started
            provider_started = True
            return SimpleNamespace(output_text="should not run", exit_code=0), SimpleNamespace(
                selected_provider_id="hosted-test"
            )

        with (
            patch("core.runtime.turn_submission_service_runtime.Thread", ImmediateThread),
            patch(
                "core.runtime.turn_submission_service_runtime.execute_plain_hosted_text_turn",
                side_effect=execute_provider,
            ),
            patch("core.inter_agent.service.interrupt_runtime_provider_turn", return_value=False),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_runtime.dispatch_source_app_runtime_event"),
        ):
            turn, _events = submit_runtime_turn_async(
                state,
                session=child,
                input_text="must remain cancelled",
                on_queued=interrupt_after_worker_snapshot,
            )

        self.assertFalse(provider_started)
        self.assertEqual(runtime_store.get_turn(turn.turn_id).status, "cancelled")
        self.assertEqual(runtime_store.get_session(child.session_id).status, "stopped")

    def test_interrupt_cancellation_rejects_a_new_generation_session_claim(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        run = service.create_run(orchestrated_spec(), now=now)
        participant = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        captured = store.save_participant(
            replace(participant, runtime_session_id="old-session", status="running", updated_at=now)
        )
        store.save_run(replace(run, status="running", recovery_generation=1, updated_at=now))
        store.save_participant(replace(captured, runtime_session_id="replacement-session", updated_at=now))

        previous, updated, cancelled = store.cancel_participant_for_interrupt(
            workspace_id="default",
            run_id=run.run_id,
            participant_id=participant.participant_id,
            expected_recovery_generation=run.recovery_generation,
            expected_runtime_session_id=captured.runtime_session_id,
            expected_current_task_id=captured.current_task_id,
            now=now,
        )

        self.assertFalse(cancelled)
        self.assertEqual(previous.runtime_session_id, "replacement-session")
        self.assertEqual(updated.status, "running")
        self.assertEqual(updated.runtime_session_id, "replacement-session")

    def test_orchestrated_runtime_turn_cannot_queue_after_pause(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        helpers = runtime_test_support.InterAgentRuntimeServiceTest()
        runtime_store = helpers._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(helpers._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(helpers._runtime_state("root-session"))
        run = service.create_run(orchestrated_spec(), now=now)
        participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="orchestrator",
            now=now,
        )

        def submit_after_pause(state, **kwargs):
            service.interrupt_run(
                state,
                workspace_id="default",
                run_id=run.run_id,
                reason="pause_before_runtime_queue",
                now=now,
            )
            queue_fence = kwargs.get("queue_fence")
            queue_turn = nullcontext() if queue_fence is None else queue_fence()
            with queue_turn:
                turn = RuntimeTurnRecord(
                    turn_id="late-turn",
                    session_id=child.session_id,
                    workspace_id="default",
                    status="queued",
                    input_text="must not queue",
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                )
                runtime_store.save_turn(turn)
            return turn, []

        with (
            patch("core.inter_agent.service.submit_runtime_turn", side_effect=submit_after_pause),
            self.assertRaises(InterAgentOperationError),
        ):
            service.send_runtime_message(
                runtime_test_support._state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                participant_id=participant.participant_id,
                input_text="must not queue",
                client_message_id="late-message",
                expected_recovery_generation=run.recovery_generation,
                now=now,
            )

        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "paused")
        self.assertEqual(runtime_store.get_session(child.session_id).status, "stopped")
        self.assertEqual(runtime_store.list_turns(child.session_id), [])

    def test_resume_waits_for_the_interrupt_cleanup_handoff(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        helpers = runtime_test_support.InterAgentRuntimeServiceTest()
        runtime_store = helpers._runtime_store()
        interrupt_service = InterAgentService(store)
        resume_service = InterAgentService(store)
        state = runtime_test_support._state(runtime_store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(helpers._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(helpers._runtime_state("root-session"))
        run = interrupt_service.create_run(orchestrated_spec(), now=now)
        _participant, child, _created = interrupt_service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="orchestrator",
            now=now,
        )
        cleanup_entered = Event()
        allow_cleanup = Event()
        resume_returned = Event()
        results: dict[str, object] = {}
        errors: list[BaseException] = []

        original_interrupt_session = service_module._interrupt_runtime_session

        def blocked_interrupt_session(*args, **kwargs):
            cleanup_entered.set()
            if not allow_cleanup.wait(timeout=2):
                raise AssertionError("Timed out waiting to release interrupt cleanup.")
            return original_interrupt_session(*args, **kwargs)

        def interrupt() -> None:
            try:
                results["interrupt"] = interrupt_service.interrupt_run(
                    state,
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="concurrent_pause",
                    now=now,
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        def resume() -> None:
            try:
                results["resume"] = resume_service.resume_run(
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="concurrent_resume",
                    now=now,
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)
            finally:
                resume_returned.set()

        with (
            patch("core.inter_agent.service._interrupt_runtime_session", side_effect=blocked_interrupt_session),
            patch("core.inter_agent.service.interrupt_runtime_provider_turn", return_value=False),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
        ):
            interrupt_thread = Thread(target=interrupt)
            interrupt_thread.start()
            self.assertTrue(cleanup_entered.wait(timeout=1))
            resume_thread = Thread(target=resume)
            resume_thread.start()
            try:
                self.assertFalse(resume_returned.wait(timeout=0.1))
            finally:
                allow_cleanup.set()
            interrupt_thread.join(timeout=2)
            resume_thread.join(timeout=2)

        self.assertFalse(interrupt_thread.is_alive())
        self.assertFalse(resume_thread.is_alive())
        self.assertEqual(errors, [])
        resumed = results["resume"]
        self.assertEqual(resumed.status, "running")
        self.assertEqual(resumed.recovery_generation, 1)
        persisted_run = store.get_run(run.run_id, workspace_id="default")
        orchestrator = store.get_participant("orchestrator", workspace_id="default", run_id=run.run_id)
        self.assertEqual(persisted_run.status, "running")
        self.assertEqual(persisted_run.recovery_generation, 1)
        self.assertEqual(orchestrator.status, "idle")
        self.assertIsNone(orchestrator.runtime_session_id)
        self.assertEqual(runtime_store.get_session(child.session_id).status, "stopped")


if __name__ == "__main__":
    unittest.main()
