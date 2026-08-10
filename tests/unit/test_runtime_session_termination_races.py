"""Runtime session termination race regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import core.runtime.session_termination as session_termination
from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session, request_runtime_turn_cancellation, transition_runtime_turn
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission_service_events import _complete_turn_from_exit_code
from core.runtime.turn_terminalization import terminalize_runtime_turn_cancellation
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class RuntimeSessionTerminationRaceTest(unittest.TestCase):
    def test_worker_completion_drains_cancellation_outbox_claimed_after_status_check(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_json_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="worker-cancel-outbox-race",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="worker-cancel-outbox-race-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="finish while interrupt claims the outbox",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        request_runtime_turn_cancellation(
            store,
            turn_id="worker-cancel-outbox-race-turn",
            reason="interrupt won",
            now=now,
        )
        cancelled = transition_runtime_turn(
            store,
            turn_id="worker-cancel-outbox-race-turn",
            target_status="cancelled",
            failure_reason="interrupt won",
            now=now,
        )
        claimed, applied = store.claim_turn_terminalization(
            turn_id=cancelled.turn_id,
            event_id="outbox-event",
            event_type="runtime.turn.cancelled",
            payload={"reason": "interrupt won"},
            now=now,
        )
        self.assertTrue(applied)

        completed, event = _complete_turn_from_exit_code(
            SimpleNamespace(runtime_store=store, runtime_event_bus=None, repository_root=repo_root),
            session_id=session.session_id,
            turn_id=claimed.turn_id,
            provider_id="codex",
            exit_code=0,
            output_text="provider output",
        )
        retried = terminalize_runtime_turn_cancellation(
            store,
            turn_id=claimed.turn_id,
            reason="interrupt won",
            event_payload={"reason": "interrupt won"},
            now=now,
        )

        self.assertEqual(completed.status, "cancelled")
        self.assertEqual(event.event_id, "outbox-event")
        self.assertEqual(retried.event.event_id, "outbox-event")
        self.assertEqual(
            [item.event_id for item in store.list_events(session.session_id) if item.event_type == "runtime.turn.cancelled"],
            ["outbox-event"],
        )

    def test_terminalization_retry_delivers_callback_with_stable_event_id(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_json_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="terminalization-callback-retry",
            workspace_id="default",
            agent_id="chat",
            source_app_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="terminalization-callback-retry-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="retry callback",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )
        callback_event_ids: list[str] = []

        def fail_callback(_session, _turn, event) -> None:
            callback_event_ids.append(event.event_id)
            raise RuntimeError("simulated callback crash")

        first = terminalize_runtime_turn_cancellation(
            store,
            turn_id="terminalization-callback-retry-turn",
            reason="cancel",
            event_payload={"reason": "cancel"},
            callback=fail_callback,
            now=now,
        )
        self.assertTrue(first.claimed)
        self.assertTrue(first.callback_pending)
        self.assertIsNone(store.get_turn(first.turn.turn_id).terminalization_callback_delivered_at)

        second = terminalize_runtime_turn_cancellation(
            store,
            turn_id=first.turn.turn_id,
            reason="cancel",
            event_payload={"reason": "cancel"},
            callback=lambda _session, _turn, event: callback_event_ids.append(event.event_id),
            now=now,
        )

        self.assertFalse(second.claimed)
        self.assertFalse(second.callback_pending)
        self.assertEqual(callback_event_ids, [first.event.event_id, first.event.event_id])
        self.assertEqual(second.event.event_id, first.event.event_id)
        self.assertIsNotNone(store.get_turn(first.turn.turn_id).terminalization_callback_delivered_at)

    def test_terminalization_retry_repairs_history_only_event_write(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_json_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="terminalization-partial-event",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="terminalization-partial-event-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="crash between history and tail",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )

        with patch.object(store, "_insert_one_if_absent", side_effect=RuntimeError("simulated tail crash")):
            with self.assertRaisesRegex(RuntimeError, "simulated tail crash"):
                terminalize_runtime_turn_cancellation(
                    store,
                    turn_id="terminalization-partial-event-turn",
                    reason="cancel",
                    event_payload={"reason": "cancel"},
                    now=now,
                )

        claimed = store.get_turn("terminalization-partial-event-turn")
        self.assertIsNotNone(claimed.terminalization_event_id)
        self.assertIsNone(claimed.terminalization_event_persisted_at)
        self.assertEqual(store.list_events(session.session_id), [])

        repaired = terminalize_runtime_turn_cancellation(
            store,
            turn_id=claimed.turn_id,
            reason="cancel",
            event_payload={"reason": "cancel"},
            now=now,
        )

        self.assertEqual(repaired.event.event_id, claimed.terminalization_event_id)
        self.assertEqual([event.event_id for event in store.list_events(session.session_id)], [repaired.event.event_id])
        self.assertEqual(
            [event.event_id for event in store.list_event_page(session.session_id).events],
            [repaired.event.event_id],
        )

    def test_completion_winner_never_publishes_cancelled_cleanup_event(self) -> None:
        store = RuntimeDocumentStore(
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
            store,
            session_id="cleanup-completion-wins",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="cleanup-completion-wins-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="finish during cleanup",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )

        def completion_wins(runtime_store, *, turn_id: str, reason: str, now=None):
            transition_runtime_turn(
                runtime_store,
                turn_id=turn_id,
                target_status="completed",
                now=now,
            )
            return request_runtime_turn_cancellation(
                runtime_store,
                turn_id=turn_id,
                reason=reason,
                now=now,
            )

        with patch(
            "core.runtime.turn_terminalization.request_runtime_turn_cancellation",
            side_effect=completion_wins,
        ):
            result = session_termination.terminate_runtime_session(
                store,
                session_id=session.session_id,
                reason="cleanup",
            )

        persisted = store.get_turn("cleanup-completion-wins-turn")
        terminal_events = [
            event.event_type
            for event in store.list_events(session.session_id)
            if event.event_type.startswith("runtime.turn.")
        ]
        self.assertEqual(persisted.status, "completed")
        self.assertEqual(result["cancelled_turns"], 0)
        self.assertNotIn("runtime.turn.cancelled", terminal_events)


def _runtime_json_store(repo_root) -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=RuntimeSessionJsonCollection(start_path=repo_root, filename="sessions.json"),
            turns=RuntimeSessionJsonCollection(start_path=repo_root, filename="turns.json"),
            events=RuntimeEventJsonCollection(start_path=repo_root),
            processes=RuntimeSessionJsonCollection(start_path=repo_root, filename="processes.json"),
            states=RuntimeSessionJsonCollection(start_path=repo_root, filename="state.json"),
            threads=WorkspaceRuntimeJsonCollection(start_path=repo_root, filename="threads.json"),
        )
    )


if __name__ == "__main__":
    unittest.main()
