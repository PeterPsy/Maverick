from __future__ import annotations

from unittest.mock import patch
import unittest

from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.service import InterAgentService
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import transition_runtime_turn
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    participant_spec,
    run_spec,
    runtime_state_namespace,
)


def _submit_active_child_turn(state, *, session, input_text, client_message_id=None):
    turn_id = f"turn-{session.session_id}"
    active = RuntimeTurnRecord(
        turn_id=turn_id,
        session_id=session.session_id,
        workspace_id="default",
        status="active",
        input_text=input_text,
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        completed_at=None,
        failure_reason=None,
    )
    started = RuntimeEventRecord(
        event_id=f"event-started-{session.session_id}",
        workspace_id="default",
        session_id=session.session_id,
        plane="turn",
        event_type="runtime.turn.started",
        turn_id=turn_id,
        process_id=None,
        payload={},
        created_at=NOW,
    )
    state.runtime_store.save_turn(active)
    state.runtime_store.save_event(started)
    return active, [started]


class InterAgentExecutorRuntimeCancelTest(unittest.TestCase):
    def test_async_runtime_cancel_does_not_rewrite_participant_after_run_cancel(self) -> None:
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        run = service.create_run(
            run_spec(
                mode="concurrent",
                run_id="async-cancel-race",
                participants=[participant_spec("researcher", "Researcher", execution_mode="child_runtime_session")],
                aggregator_participant_id="orchestrator",
                merge_policy="orchestrator_summarizes",
            ),
            now=NOW,
        )
        runtime_state = runtime_state_namespace(runtime_store)

        def cleanup_runtime_session(session_id: str, reason: str) -> dict[str, object]:
            cancelled_turns = 0
            for turn in runtime_store.list_turns(session_id):
                if turn.status not in {"queued", "active"}:
                    continue
                transition_runtime_turn(
                    runtime_store,
                    turn_id=turn.turn_id,
                    target_status="cancelled",
                    failure_reason=reason,
                    now=NOW,
                )
                cancelled_turns += 1
            return {"session_id": session_id, "found": True, "cancelled_turns": cancelled_turns}

        def fake_wait(state, turn_id):
            service.close_run(
                workspace_id="default",
                run_id=run.run_id,
                cleanup_runtime_session=cleanup_runtime_session,
                reason="root_runtime_turn_interrupted",
                terminal_status="cancelled",
                now=NOW,
            )
            return state.runtime_store.get_turn(turn_id)

        with (
            patch("core.inter_agent.service.submit_runtime_turn", side_effect=AssertionError("sync path called")),
            patch("core.inter_agent.service.submit_runtime_turn_async", side_effect=_submit_active_child_turn),
            patch("core.inter_agent.executor._wait_for_runtime_turn", side_effect=fake_wait),
        ):
            result = execute_inter_agent_run(
                service,
                runtime_state,
                workspace_id="default",
                run_id=run.run_id,
                input_text="Run the async child until the root turn is stopped.",
                project_summaries=False,
                async_runtime_turns=True,
                now=NOW,
            )

        participant = store.get_participant("researcher", workspace_id="default", run_id=run.run_id)
        child_session = next(session for session in runtime_store.list_sessions("default") if session.session_id != "root-session")
        child_turn = runtime_store.list_turns(child_session.session_id)[0]
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        event_types = [event.event_type for event in events]
        cancelled_index = event_types.index("inter_agent.run.cancelled")
        post_cancel_event_types = event_types[cancelled_index + 1 :]

        self.assertEqual(result.run.status, "cancelled")
        self.assertEqual(result.participant_results[0].status, "cancelled")
        self.assertEqual(participant.status, "cancelled")
        self.assertEqual(child_turn.status, "cancelled")
        self.assertNotIn("inter_agent.task.completed", post_cancel_event_types)
        self.assertNotIn("inter_agent.participant.status_changed", post_cancel_event_types)
        self.assertNotIn("inter_agent.summary.updated", post_cancel_event_types)

    def test_async_runtime_turn_cancel_finalizes_participant_and_budget(self) -> None:
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        run = service.create_run(
            run_spec(
                mode="concurrent",
                run_id="async-turn-cancel-only",
                participants=[participant_spec("researcher", "Researcher", execution_mode="child_runtime_session")],
                aggregator_participant_id="orchestrator",
                merge_policy="orchestrator_summarizes",
            ),
            now=NOW,
        )
        runtime_state = runtime_state_namespace(runtime_store)

        def fake_wait(state, turn_id):
            transition_runtime_turn(
                state.runtime_store,
                turn_id=turn_id,
                target_status="cancelled",
                failure_reason="Provider cancelled child turn.",
                now=NOW,
            )
            return state.runtime_store.get_turn(turn_id)

        with (
            patch("core.inter_agent.service.submit_runtime_turn", side_effect=AssertionError("sync path called")),
            patch("core.inter_agent.service.submit_runtime_turn_async", side_effect=_submit_active_child_turn),
            patch("core.inter_agent.executor._wait_for_runtime_turn", side_effect=fake_wait),
        ):
            result = execute_inter_agent_run(
                service,
                runtime_state,
                workspace_id="default",
                run_id=run.run_id,
                input_text="Run the async child until the runtime turn is cancelled.",
                project_summaries=False,
                async_runtime_turns=True,
                now=NOW,
            )

        participant = store.get_participant("researcher", workspace_id="default", run_id=run.run_id)
        ledger = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        child_session = next(session for session in runtime_store.list_sessions("default") if session.session_id != "root-session")
        child_turn = runtime_store.list_turns(child_session.session_id)[0]
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        event_types = [event.event_type for event in events]
        status_events = [event for event in events if event.event_type == "inter_agent.participant.status_changed"]

        self.assertEqual(result.run.status, "cancelled")
        self.assertEqual(result.participant_results[0].status, "cancelled")
        self.assertEqual(participant.status, "cancelled")
        self.assertEqual(child_turn.status, "cancelled")
        self.assertEqual(ledger.running_participants, 0)
        self.assertEqual([event.payload["status"] for event in status_events], ["cancelled"])
        self.assertNotIn("inter_agent.run.failed", event_types)


if __name__ == "__main__":
    unittest.main()
