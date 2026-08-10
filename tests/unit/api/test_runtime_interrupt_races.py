"""Runtime interrupt surface race regressions."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from threading import Barrier, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.api.runtime_api as runtime_api
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.service import (
    create_runtime_session,
    request_runtime_turn_cancellation,
    transition_runtime_turn,
)
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeInterruptRaceTestCase(unittest.TestCase):
    def test_api_retry_repairs_cancelled_turn_without_terminal_event_or_callback(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_json_store(repo_root)
        session = create_runtime_session(
            runtime_store,
            session_id="api-crashed-terminalization",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="api-crashed-terminalization-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="cancel before crash",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        request_runtime_turn_cancellation(
            runtime_store,
            turn_id="api-crashed-terminalization-turn",
            reason="Interrupted by user.",
            now=now,
        )
        transition_runtime_turn(
            runtime_store,
            turn_id="api-crashed-terminalization-turn",
            target_status="cancelled",
            failure_reason="Interrupted by user.",
            now=now,
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            runtime_event_bus=None,
            workspace_store=object(),
        )

        with (
            patch.object(runtime_api, "require_runtime_session_operation"),
            patch.object(runtime_api, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_api, "interrupt_runtime_provider_turn", return_value=False),
            patch.object(runtime_api, "release_idle_runtime_processes"),
            patch.object(runtime_api, "dispatch_source_app_runtime_event") as dispatch,
        ):
            response = runtime_api._handle_turn_interrupt(
                state,
                SimpleNamespace(workspace_id="default", user=SimpleNamespace()),
                "api-crashed-terminalization-turn",
                lambda _status, _headers: None,
                start_path=repo_root,
            )

        payload = json.loads(b"".join(response).decode("utf-8"))
        cancelled_events = [
            event
            for event in runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.turn.cancelled"
        ]
        self.assertTrue(payload["interrupted"])
        self.assertEqual(len(cancelled_events), 1)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["runtime_event_id"], cancelled_events[0].event_id)

    def test_api_reports_not_interrupted_when_completion_wins_before_cancel_intent(self) -> None:
        runtime_store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        repo_root = make_temp_repo_root(self)
        session = create_runtime_session(
            runtime_store,
            session_id="api-completion-wins",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="api-completion-wins-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="finish now",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            runtime_event_bus=None,
            workspace_store=object(),
        )
        response_status: list[str] = []

        def completion_wins(store, *, turn_id: str, reason: str, now=None):
            transition_runtime_turn(store, turn_id=turn_id, target_status="completed")
            return request_runtime_turn_cancellation(store, turn_id=turn_id, reason=reason, now=now)

        def start_response(status: str, _headers: list[tuple[str, str]]) -> None:
            response_status.append(status)

        with (
            patch.object(runtime_api, "require_runtime_session_operation"),
            patch.object(runtime_api, "request_runtime_turn_cancellation", side_effect=completion_wins),
            patch.object(runtime_api, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_api, "interrupt_runtime_provider_turn") as interrupt_provider,
            patch.object(runtime_api, "release_idle_runtime_processes"),
            patch.object(runtime_api, "dispatch_source_app_runtime_event") as dispatch,
        ):
            response = runtime_api._handle_turn_interrupt(
                state,
                SimpleNamespace(workspace_id="default", user=SimpleNamespace()),
                "api-completion-wins-turn",
                start_response,
                start_path=repo_root,
            )

        payload = json.loads(b"".join(response).decode("utf-8"))
        self.assertEqual(response_status, ["200 OK"])
        self.assertFalse(payload["interrupted"])
        self.assertEqual(payload["turn"]["status"], "completed")
        self.assertNotIn("event", payload)
        self.assertNotIn(
            "runtime.turn.cancelled",
            [event.event_type for event in runtime_store.list_events(session.session_id)],
        )
        interrupt_provider.assert_not_called()
        dispatch.assert_not_called()

    def test_concurrent_api_interrupts_publish_one_terminal_event_and_callback(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_json_store(repo_root)
        session = create_runtime_session(
            runtime_store,
            session_id="api-concurrent-interrupt",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="api-concurrent-interrupt-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="stop once",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            runtime_event_bus=None,
            workspace_store=object(),
        )
        barrier = Barrier(2)
        original_request = request_runtime_turn_cancellation
        payloads: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def synchronized_request(*args, **kwargs):
            barrier.wait(timeout=2)
            return original_request(*args, **kwargs)

        def invoke() -> None:
            try:
                response = runtime_api._handle_turn_interrupt(
                    state,
                    SimpleNamespace(workspace_id="default", user=SimpleNamespace()),
                    "api-concurrent-interrupt-turn",
                    lambda _status, _headers: None,
                    start_path=repo_root,
                )
                payloads.append(json.loads(b"".join(response).decode("utf-8")))
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        with (
            patch.object(runtime_api, "require_runtime_session_operation"),
            patch.object(runtime_api, "request_runtime_turn_cancellation", side_effect=synchronized_request),
            patch.object(runtime_api, "_resolved_provider_id", return_value="codex"),
            patch.object(runtime_api, "interrupt_runtime_provider_turn", return_value=False),
            patch.object(runtime_api, "release_idle_runtime_processes"),
            patch.object(runtime_api, "dispatch_source_app_runtime_event") as dispatch,
        ):
            threads = [Thread(target=invoke) for _index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertEqual(errors, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(bool(payload["interrupted"]) for payload in payloads), [False, True])
        cancelled_events = [
            event
            for event in runtime_store.list_events(session.session_id)
            if event.event_type == "runtime.turn.cancelled"
        ]
        self.assertEqual(len(cancelled_events), 1)
        self.assertEqual(
            [event.event_id for event in runtime_store.list_event_page(session.session_id).events],
            [cancelled_events[0].event_id],
        )
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["runtime_event_id"], cancelled_events[0].event_id)


def _runtime_json_store(repo_root) -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=RuntimeSessionJsonCollection(start_path=repo_root, filename="session.json"),
            turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
            events=RuntimeEventJsonCollection(start_path=repo_root),
            processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
            states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
            threads=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="threads.json"),
        )
    )


if __name__ == "__main__":
    unittest.main()
