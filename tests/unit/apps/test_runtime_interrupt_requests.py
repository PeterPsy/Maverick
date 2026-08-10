"""Source-app runtime interrupt request regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Barrier, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.apps.runtime_requests as runtime_requests
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import (
    create_runtime_session,
    record_runtime_event,
    request_runtime_turn_cancellation,
    transition_runtime_turn,
)
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeInterruptRequestsTestCase(unittest.TestCase):
    def _runtime_store(self) -> RuntimeDocumentStore:
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

    def _active_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[RuntimeDocumentStore, RuntimeSessionRecord]:
        runtime_store = self._runtime_store()
        repo_root = make_temp_repo_root(self)
        session = create_runtime_session(
            runtime_store,
            session_id=session_id,
            workspace_id="default",
            agent_id="video-agent",
            source_app_id="video-studio",
            start_path=repo_root,
        )
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id=turn_id,
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="render",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        return runtime_store, session

    def test_app_runtime_interrupt_retries_provider_after_cancellation_handoff(self) -> None:
        runtime_store, _session = self._active_turn(
            session_id="app-owned-session",
            turn_id="app-owned-turn",
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            runtime_event_bus=None,
        )

        with (
            patch.object(runtime_requests, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_requests, "interrupt_runtime_provider_turn", side_effect=[False, True]) as interrupt,
            patch.object(runtime_requests, "release_idle_runtime_processes", return_value=0),
            patch.object(runtime_requests, "dispatch_source_app_runtime_event"),
        ):
            result = runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": "app-owned-turn"},
                workspace_id="default",
                app_id="video-studio",
            )

        self.assertEqual(interrupt.call_count, 2)
        self.assertNotIn("wait_for_termination", interrupt.call_args_list[0].kwargs)
        self.assertTrue(interrupt.call_args_list[1].kwargs["wait_for_termination"])
        self.assertTrue(result["provider_interrupted"])
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNotNone(runtime_store.get_turn("app-owned-turn").cancellation_requested_at)

    def test_app_retry_repairs_callback_after_terminal_event_was_already_persisted(self) -> None:
        runtime_store, session = self._active_turn(
            session_id="app-crashed-callback",
            turn_id="app-crashed-callback-turn",
        )
        cancelled = request_runtime_turn_cancellation(
            runtime_store,
            turn_id="app-crashed-callback-turn",
            reason="Interrupted by app request.",
        )
        cancelled = transition_runtime_turn(
            runtime_store,
            turn_id=cancelled.turn_id,
            target_status="cancelled",
            failure_reason="Interrupted by app request.",
        )
        existing_event = record_runtime_event(
            runtime_store,
            event_id="event-before-callback-crash",
            session_id=session.session_id,
            turn_id=cancelled.turn_id,
            plane="turn",
            event_type="runtime.turn.cancelled",
            payload={"reason": "Interrupted by app request."},
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            runtime_event_bus=None,
        )

        with (
            patch.object(runtime_requests, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_requests, "interrupt_runtime_provider_turn", return_value=False),
            patch.object(runtime_requests, "release_idle_runtime_processes"),
            patch.object(runtime_requests, "dispatch_source_app_runtime_event") as dispatch,
        ):
            result = runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": cancelled.turn_id},
                workspace_id="default",
                app_id="video-studio",
            )

        cancelled_events = [
            event
            for event in runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.turn.cancelled"
        ]
        self.assertEqual(len(cancelled_events), 1)
        self.assertEqual(cancelled_events[0].event_id, existing_event.event_id)
        self.assertTrue(result["interrupted"])
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["runtime_event_id"], existing_event.event_id)

    def test_app_runtime_interrupt_reports_completion_when_it_wins_before_cancel_intent(self) -> None:
        runtime_store, session = self._active_turn(
            session_id="app-completion-wins",
            turn_id="app-completion-wins-turn",
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            runtime_event_bus=None,
        )

        def completion_wins(store, *, turn_id: str, reason: str, now=None):
            transition_runtime_turn(store, turn_id=turn_id, target_status="completed")
            return request_runtime_turn_cancellation(store, turn_id=turn_id, reason=reason, now=now)

        with (
            patch.object(runtime_requests, "request_runtime_turn_cancellation", side_effect=completion_wins),
            patch.object(runtime_requests, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_requests, "interrupt_runtime_provider_turn") as interrupt_provider,
            patch.object(runtime_requests, "release_idle_runtime_processes"),
            patch.object(runtime_requests, "dispatch_source_app_runtime_event") as dispatch,
        ):
            result = runtime_requests._apply_one_runtime_interrupt_request(
                state,
                request={"turn_id": "app-completion-wins-turn"},
                workspace_id="default",
                app_id="video-studio",
            )

        self.assertFalse(result["interrupted"])
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("event_id", result)
        self.assertNotIn(
            "runtime.turn.cancelled",
            [event.event_type for event in runtime_store.list_events(session.session_id)],
        )
        interrupt_provider.assert_not_called()
        dispatch.assert_not_called()

    def test_concurrent_app_interrupts_publish_one_terminal_event_and_callback(self) -> None:
        runtime_store, session = self._active_turn(
            session_id="app-concurrent-interrupt",
            turn_id="app-concurrent-interrupt-turn",
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            provider_store=object(),
            runtime_event_bus=None,
        )
        barrier = Barrier(2)
        original_request = request_runtime_turn_cancellation
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def synchronized_request(*args, **kwargs):
            barrier.wait(timeout=2)
            return original_request(*args, **kwargs)

        def invoke() -> None:
            try:
                results.append(
                    runtime_requests._apply_one_runtime_interrupt_request(
                        state,
                        request={"turn_id": "app-concurrent-interrupt-turn"},
                        workspace_id="default",
                        app_id="video-studio",
                    )
                )
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        with (
            patch.object(runtime_requests, "request_runtime_turn_cancellation", side_effect=synchronized_request),
            patch.object(runtime_requests, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_requests, "interrupt_runtime_provider_turn", return_value=False),
            patch.object(runtime_requests, "release_idle_runtime_processes"),
            patch.object(runtime_requests, "dispatch_source_app_runtime_event") as dispatch,
        ):
            threads = [Thread(target=invoke) for _index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertEqual(errors, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(bool(result["interrupted"]) for result in results), [False, True])
        cancelled_events = [
            event
            for event in runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.turn.cancelled"
        ]
        self.assertEqual(len(cancelled_events), 1)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["runtime_event_id"], cancelled_events[0].event_id)


if __name__ == "__main__":
    unittest.main()
