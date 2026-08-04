from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from unittest.mock import patch
import unittest

from core.inter_agent.errors import InterAgentOperationError
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent import test_service_runtime as runtime_test_support
from tests.unit.inter_agent.test_dynamic_orchestration_service import orchestrated_spec


class OrchestrationRuntimePauseRaceTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
