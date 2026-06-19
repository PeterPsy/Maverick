from __future__ import annotations

from unittest.mock import patch
import unittest

from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.service import InterAgentService
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    participant_spec as _participant,
    run_spec as _run_spec,
    runtime_state_namespace as _state,
)


class InterAgentExecutorRuntimeFinalTest(unittest.TestCase):
    def _execute_runtime_child_with_events(
        self,
        *,
        run_id: str,
        delta_texts: list[str],
        final_payload: dict,
    ):
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                run_id=run_id,
                participants=[_participant("researcher", "Researcher", execution_mode="child_runtime_session")],
            ),
            now=NOW,
        )

        def fake_submit(state, *, session, input_text, client_message_id=None, async_requested=False):
            turn_id = f"turn-{session.session_id}"
            turn = RuntimeTurnRecord(
                turn_id=turn_id,
                session_id=session.session_id,
                workspace_id="default",
                status="completed",
                input_text=input_text,
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=NOW,
                failure_reason=None,
            )
            events = []
            for index, text in enumerate(delta_texts):
                events.append(
                    RuntimeEventRecord(
                        event_id=f"event-delta-{index}-{session.session_id}",
                        workspace_id="default",
                        session_id=session.session_id,
                        plane="turn",
                        event_type="runtime.output.delta",
                        turn_id=turn_id,
                        process_id=None,
                        payload={"text": text},
                        created_at=NOW,
                    )
                )
            events.append(
                RuntimeEventRecord(
                    event_id=f"event-final-{session.session_id}",
                    workspace_id="default",
                    session_id=session.session_id,
                    plane="turn",
                    event_type="runtime.output.final",
                    turn_id=turn_id,
                    process_id=None,
                    payload=dict(final_payload),
                    created_at=NOW,
                )
            )
            state.runtime_store.save_turn(turn)
            for event in events:
                state.runtime_store.save_event(event)
            return turn, events

        with patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit):
            return execute_inter_agent_run(
                service,
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                input_text="Review readiness.",
                project_summaries=False,
                now=NOW,
            )

    def test_runtime_participant_uses_complete_final_text_when_answer_streamed_in_delta(self) -> None:
        result = self._execute_runtime_child_with_events(
            run_id="runtime-complete-from-delta",
            delta_texts=["Answer streamed in deltas."],
            final_payload={"text": "", "complete_text": "Answer streamed in deltas."},
        )

        participant_result = result.participant_results[0]
        self.assertEqual(participant_result.output_text, "Answer streamed in deltas.")
        self.assertEqual(participant_result.partial_output, "Answer streamed in deltas.")
        self.assertEqual(participant_result.summary, "Answer streamed in deltas.")
        self.assertEqual(result.final_answer, "Answer streamed in deltas.")

    def test_runtime_participant_uses_complete_final_text_when_final_is_suffix(self) -> None:
        result = self._execute_runtime_child_with_events(
            run_id="runtime-complete-from-suffix",
            delta_texts=["Hello "],
            final_payload={"text": "world", "complete_text": "Hello world"},
        )

        participant_result = result.participant_results[0]
        self.assertEqual(participant_result.output_text, "Hello world")
        self.assertEqual(participant_result.partial_output, "Hello")
        self.assertEqual(result.final_answer, "Hello world")

    def test_runtime_participant_keeps_progress_delta_out_of_final_answer(self) -> None:
        result = self._execute_runtime_child_with_events(
            run_id="runtime-progress-delta-clean-final",
            delta_texts=["Mi oriento sul codice e preparo il piano."],
            final_payload={"text": "Final answer only.", "complete_text": "Final answer only."},
        )

        participant_result = result.participant_results[0]
        self.assertEqual(participant_result.output_text, "Final answer only.")
        self.assertEqual(participant_result.partial_output, "Mi oriento sul codice e preparo il piano.")
        self.assertEqual(result.final_answer, "Final answer only.")
        self.assertNotIn("Mi oriento", result.final_answer)


if __name__ == "__main__":
    unittest.main()
