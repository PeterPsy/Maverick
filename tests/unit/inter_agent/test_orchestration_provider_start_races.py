from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.plain_hosted_cancellation import plain_hosted_request_cancellation
from core.runtime.turn_submission import submit_runtime_turn, submit_runtime_turn_async
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent import test_service_runtime as runtime_test_support
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationProviderStartRaceTest(unittest.TestCase):
    def test_interrupt_waits_for_plain_hosted_provider_to_stop_after_late_acceptance(self) -> None:
        service, state, run, child = self._scenario()
        provider_called = Event()
        allow_provider_acceptance = Event()
        provider_accepted = Event()
        provider_stopped = Event()
        interrupt_returned = Event()
        provider_was_stopped_at_return: list[bool] = []
        errors: list[BaseException] = []

        def execute_provider(*_args, **kwargs):
            provider_called.set()
            if not allow_provider_acceptance.wait(timeout=2):
                raise AssertionError("Timed out waiting to accept the provider turn.")
            with plain_hosted_request_cancellation(
                session_id=kwargs["session"].session_id,
                turn_id=kwargs["turn_id"],
            ) as cancellation:
                accepted = kwargs.get("on_provider_accepted")
                if callable(accepted):
                    accepted({"provider_id": "hosted-test", "status_code": 200})
                provider_accepted.set()
                if not cancellation.wait_cancelled(timeout=2):
                    raise AssertionError("Provider request was not cancelled after acceptance.")
                provider_stopped.set()
                return SimpleNamespace(output_text="cancelled output", exit_code=0), SimpleNamespace(
                    selected_provider_id="hosted-test"
                )

        def interrupt() -> None:
            try:
                service.interrupt_run(
                    state,
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="pause_before_provider_ack",
                )
                provider_was_stopped_at_return.append(provider_stopped.is_set())
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)
            finally:
                interrupt_returned.set()

        with (
            patch(
                "core.runtime.turn_submission_service_runtime.execute_plain_hosted_text_turn",
                side_effect=execute_provider,
            ),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_runtime.dispatch_source_app_runtime_event"),
        ):
            turn, _events = submit_runtime_turn_async(state, session=child, input_text="race provider stop")
            self.assertTrue(provider_called.wait(timeout=1))
            interrupt_thread = Thread(target=interrupt)
            interrupt_thread.start()
            try:
                self.assertFalse(interrupt_returned.wait(timeout=0.1))
                self._wait_for_cancellation_intent(state, turn.turn_id)
            finally:
                allow_provider_acceptance.set()
            interrupt_thread.join(timeout=2)

        self.assertFalse(interrupt_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(provider_accepted.is_set())
        self.assertTrue(provider_stopped.is_set())
        self.assertEqual(provider_was_stopped_at_return, [True])
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")
        self.assertEqual(state.runtime_store.get_session(child.session_id).status, "stopped")

    def test_interrupt_cannot_complete_between_final_check_and_provider_acceptance(self) -> None:
        service, state, run, child = self._scenario()
        provider_called = Event()
        allow_provider_acceptance = Event()
        provider_accepted = Event()
        interrupt_returned = Event()
        errors: list[BaseException] = []

        def execute_provider(*_args, **kwargs):
            provider_called.set()
            if not allow_provider_acceptance.wait(timeout=2):
                raise AssertionError("Timed out waiting to accept the provider turn.")
            sent = kwargs.get("on_provider_turn_start_sent")
            if callable(sent):
                sent({"provider_id": "hosted-test", "source": "test"})
            accepted = kwargs.get("on_provider_accepted")
            if callable(accepted):
                accepted({"provider_id": "hosted-test", "status_code": 200})
            provider_accepted.set()
            return SimpleNamespace(output_text="cancelled output", exit_code=0), SimpleNamespace(
                selected_provider_id="hosted-test"
            )

        def interrupt() -> None:
            try:
                service.interrupt_run(
                    state,
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="pause_during_provider_start",
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)
            finally:
                interrupt_returned.set()

        with (
            patch(
                "core.runtime.turn_submission_service_runtime.execute_plain_hosted_text_turn",
                side_effect=execute_provider,
            ),
            patch("core.inter_agent.service.interrupt_runtime_provider_turn", return_value=False),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_runtime.dispatch_source_app_runtime_event"),
        ):
            turn, _events = submit_runtime_turn_async(state, session=child, input_text="race provider start")
            self.assertTrue(provider_called.wait(timeout=1))
            interrupt_thread = Thread(target=interrupt)
            interrupt_thread.start()
            try:
                self.assertFalse(interrupt_returned.wait(timeout=0.1))
                self._wait_for_cancellation_intent(state, turn.turn_id)
            finally:
                allow_provider_acceptance.set()
            interrupt_thread.join(timeout=2)

        self.assertFalse(interrupt_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(provider_accepted.is_set())
        self.assertTrue(interrupt_returned.is_set())
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")
        self.assertEqual(state.runtime_store.get_session(child.session_id).status, "stopped")

    def test_agentic_provider_start_is_covered_by_the_same_acceptance_handoff(self) -> None:
        service, state, run, child = self._scenario(runtime_mode="agentic")
        provider_called = Event()
        allow_provider_acceptance = Event()
        interrupt_returned = Event()
        errors: list[BaseException] = []

        def execute_provider(**kwargs):
            provider_called.set()
            if not allow_provider_acceptance.wait(timeout=2):
                raise AssertionError("Timed out waiting to accept the agentic provider turn.")
            thread_bound = kwargs.get("on_provider_thread_id")
            if callable(thread_bound):
                thread_bound("thread-1")
            sent = kwargs.get("on_provider_turn_start_sent")
            if callable(sent):
                sent({"provider_thread_id": "thread-1", "source": "test"})
            accepted = kwargs.get("on_provider_accepted")
            if callable(accepted):
                accepted({"provider_thread_id": "thread-1", "provider_turn_id": "turn-1"})
            return SimpleNamespace(output_text="cancelled output", exit_code=0)

        def interrupt() -> None:
            try:
                service.interrupt_run(
                    state,
                    workspace_id="default",
                    run_id=run.run_id,
                    reason="pause_during_agentic_provider_start",
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)
            finally:
                interrupt_returned.set()

        provider = SimpleNamespace(provider_id="codex")
        with (
            patch(
                "core.runtime.turn_submission_service_runtime.resolve_runtime_engine_for_session",
                return_value=(
                    provider,
                    None,
                    SimpleNamespace(local_process_lifecycle=object()),
                    object(),
                ),
            ),
            patch(
                "core.runtime.turn_submission_service_runtime._build_launch_spec_for_execution",
                return_value=(None, {}),
            ),
            patch(
                "core.runtime.turn_submission_service_runtime.runtime_provider_input_text",
                return_value="provider input",
            ),
            patch(
                "core.runtime.turn_submission_service_runtime.execute_runtime_turn",
                side_effect=execute_provider,
            ),
            patch("core.inter_agent.service.interrupt_runtime_provider_turn", return_value=False),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_runtime.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_runtime.dispatch_source_app_runtime_event"),
        ):
            turn, _events = submit_runtime_turn_async(state, session=child, input_text="race agentic start")
            self.assertTrue(provider_called.wait(timeout=1))
            interrupt_thread = Thread(target=interrupt)
            interrupt_thread.start()
            try:
                self.assertFalse(interrupt_returned.wait(timeout=0.1))
            finally:
                allow_provider_acceptance.set()
            interrupt_thread.join(timeout=2)

        self.assertFalse(interrupt_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(interrupt_returned.is_set())
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")
        persisted = state.runtime_store.get_session(child.session_id)
        self.assertEqual(persisted.provider_thread_id, "thread-1")
        self.assertEqual(persisted.status, "stopped")

    def test_provider_metadata_save_after_interrupt_preserves_stopped_session(self) -> None:
        service, state, run, child = self._scenario()
        provider_accepted = Event()
        allow_provider_return = Event()

        def execute_provider(*_args, **kwargs):
            sent = kwargs.get("on_provider_turn_start_sent")
            if callable(sent):
                sent({"provider_id": "hosted-test", "source": "test"})
            accepted = kwargs.get("on_provider_accepted")
            if callable(accepted):
                accepted({"provider_id": "hosted-test", "status_code": 200})
            provider_accepted.set()
            if not allow_provider_return.wait(timeout=2):
                raise AssertionError("Timed out waiting to return from the provider.")
            return SimpleNamespace(output_text="cancelled output", exit_code=0), SimpleNamespace(
                selected_provider_id="hosted-test"
            )

        with (
            patch(
                "core.runtime.turn_submission_service_runtime.execute_plain_hosted_text_turn",
                side_effect=execute_provider,
            ),
            patch("core.inter_agent.service.interrupt_runtime_provider_turn", return_value=False),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_runtime.dispatch_source_app_runtime_event"),
        ):
            turn, _events = submit_runtime_turn_async(state, session=child, input_text="race metadata save")
            self.assertTrue(provider_accepted.wait(timeout=1))
            service.interrupt_run(
                state,
                workspace_id="default",
                run_id=run.run_id,
                reason="pause_before_provider_return",
            )
            self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")
            self.assertEqual(state.runtime_store.get_session(child.session_id).status, "stopped")
            allow_provider_return.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if state.runtime_store.get_session(child.session_id).provider_id == "hosted-test":
                    break
                time.sleep(0.01)

        persisted = state.runtime_store.get_session(child.session_id)
        self.assertEqual(persisted.provider_id, "hosted-test")
        self.assertEqual(persisted.status, "stopped")
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")

    def test_sync_provider_return_after_interrupt_preserves_terminal_lifecycle(self) -> None:
        service, state, run, child = self._scenario()
        provider_accepted = Event()
        allow_provider_return = Event()
        results: dict[str, object] = {}
        errors: list[BaseException] = []

        def execute_provider(*_args, **kwargs):
            accepted = kwargs.get("on_provider_accepted")
            if callable(accepted):
                accepted({"provider_id": "hosted-test", "status_code": 200})
            provider_accepted.set()
            if not allow_provider_return.wait(timeout=2):
                raise AssertionError("Timed out waiting to return from the sync provider.")
            return SimpleNamespace(output_text="cancelled output", exit_code=0), SimpleNamespace(
                selected_provider_id="hosted-test"
            )

        def submit() -> None:
            try:
                results["turn"] = submit_runtime_turn(
                    state,
                    session=child,
                    input_text="race sync metadata save",
                )[0]
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        with (
            patch(
                "core.runtime.turn_submission_service_sync_hosted.execute_plain_hosted_text_turn",
                side_effect=execute_provider,
            ),
            patch("core.inter_agent.service.interrupt_runtime_provider_turn", return_value=False),
            patch("core.inter_agent.service.release_idle_runtime_processes", return_value=0),
            patch("core.runtime.turn_submission_service_submit.dispatch_source_app_runtime_event"),
        ):
            submit_thread = Thread(target=submit)
            submit_thread.start()
            self.assertTrue(provider_accepted.wait(timeout=1))
            service.interrupt_run(
                state,
                workspace_id="default",
                run_id=run.run_id,
                reason="pause_before_sync_provider_return",
            )
            allow_provider_return.set()
            submit_thread.join(timeout=2)

        self.assertFalse(submit_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results["turn"].status, "cancelled")
        self.assertEqual(state.runtime_store.get_session(child.session_id).status, "stopped")

    def _scenario(self, *, runtime_mode: str = "plain_hosted_chat"):
        repo_root = make_temp_repo_root(self)
        inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
        helpers = runtime_test_support.InterAgentRuntimeServiceTest()
        runtime_store = helpers._runtime_store()
        service = InterAgentService(inter_agent_store)
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
            replace(child, runtime_mode=runtime_mode, skill_ids=[], skill_catalog_app_id=None)
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            inter_agent_store=inter_agent_store,
            runtime_event_bus=None,
            runtime_thread_event_bus=None,
            repository_root=repo_root,
        )
        return service, state, run, child

    def _wait_for_cancellation_intent(self, state, turn_id: str) -> None:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if state.runtime_store.get_turn(turn_id).cancellation_requested_at is not None:
                return
            time.sleep(0.01)
        self.fail("Interrupt did not publish its cancellation intent before provider acceptance.")


if __name__ == "__main__":
    unittest.main()
