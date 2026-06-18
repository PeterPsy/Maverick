from __future__ import annotations

from unittest.mock import patch
import unittest

from core.inter_agent.errors import InterAgentOperationError
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


class InterAgentExecutorTest(unittest.TestCase):
    def _stores(self):
        return build_executor_stores(self)

    def test_manager_tools_controlled_run_projects_root_summary_and_graph_events(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                run_id="manager-controlled",
                participants=[
                    _participant("researcher", "Researcher"),
                    _participant("reviewer", "Reviewer"),
                ],
            ),
            now=NOW,
        )

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Summarize the migration risks.",
            controlled_participants={
                "researcher": {
                    "output_text": "Found two migration risks.",
                    "summary": "Research found two migration risks.",
                    "artifact_refs": [{"app_id": "storage", "entity_type": "file", "entity_id": "file-risk"}],
                },
                "reviewer": {"output_text": "Risks are valid.", "summary": "Reviewer confirmed the risks."},
            },
            allow_synthetic_participants=True,
            now=NOW,
        )

        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        root_events = runtime_store.list_events("root-session")
        summary_events = [event for event in events if event.event_type == "inter_agent.summary.updated"]
        run_completed = next(event for event in events if event.event_type == "inter_agent.run.completed")

        self.assertEqual(result.run.status, "completed")
        self.assertEqual(
            [store.get_participant(pid, workspace_id="default", run_id=run.run_id).status for pid in ("researcher", "reviewer")],
            ["completed", "completed"],
        )
        self.assertIn("inter_agent.plan.summary_created", [event.event_type for event in events])
        self.assertIn("inter_agent.artifact.created", [event.event_type for event in events])
        self.assertIn("inter_agent.run.completed", [event.event_type for event in events])
        self.assertEqual([event.event_type for event in root_events], ["runtime.step.updated", "runtime.step.updated"])
        self.assertIn("manager-tools mode", root_events[0].payload["label"])
        self.assertIn("Multi-agent run completed", root_events[-1].payload["label"])
        self.assertTrue(result.participant_results[0].synthetic)
        self.assertEqual(result.participant_results[0].synthetic_source, "controlled_payload")
        self.assertTrue(all(event.payload.get("synthetic") is True for event in summary_events))
        self.assertEqual({event.payload.get("synthetic_source") for event in summary_events}, {"controlled_payload"})
        self.assertTrue(run_completed.payload.get("synthetic"))
        self.assertEqual(run_completed.payload.get("synthetic_source"), "controlled_payload")
        self.assertEqual([event.payload.get("synthetic") for event in root_events], [True, True])
        self.assertEqual([event.payload.get("synthetic_source") for event in root_events], ["controlled_payload", "controlled_payload"])

    def test_controlled_participants_require_synthetic_execution_allowance(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(_run_spec(run_id="controlled-disallowed"), now=NOW)

        with self.assertRaisesRegex(InterAgentOperationError, "Controlled inter-agent participant output"):
            execute_inter_agent_run(
                service,
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                controlled_participants={"researcher": {"output_text": "synthetic"}},
                project_summaries=False,
                now=NOW,
            )

        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "created")

    def test_manager_tools_delegates_worker_prompt_instead_of_forwarding_raw_request(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(_run_spec(run_id="manager-delegated-prompt"), now=NOW)
        original_prompt = "The orchestrator must assign this work to the operational agent."

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text=original_prompt,
            controlled_participants={"researcher": {"output_text": "Worker result.", "summary": "Worker completed."}},
            allow_synthetic_participants=True,
            project_summaries=False,
            now=NOW,
        )
        message_event = next(
            event
            for event in store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
            if event.event_type == "inter_agent.message.sent"
        )
        delegated_prompt = message_event.payload["input_text"]

        self.assertEqual(result.final_answer, "Worker result.")
        self.assertNotEqual(delegated_prompt, original_prompt)
        self.assertIn("delegated worker", delegated_prompt)
        self.assertIn("Do not act as the orchestrator", delegated_prompt)
        self.assertIn(f"User request:\n{original_prompt}", delegated_prompt)

    def test_sequential_controlled_run_passes_previous_output_to_next_participant(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="sequential",
                run_id="sequential-controlled",
                participants=[
                    _participant("researcher", "Researcher"),
                    _participant("synthesizer", "Synthesizer"),
                ],
            ),
            now=NOW,
        )

        execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Research then synthesize.",
            controlled_participants={
                "researcher": {"output_text": "Primary evidence A.", "summary": "Evidence A found."},
                "synthesizer": {"output_text": "Synthesis used evidence A.", "summary": "Synthesis completed."},
            },
            allow_synthetic_participants=True,
            project_summaries=False,
            now=NOW,
        )

        message_events = [
            event
            for event in store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
            if event.event_type == "inter_agent.message.sent"
        ]

        self.assertEqual(len(message_events), 2)
        self.assertIn("Primary evidence A.", message_events[1].payload["input_text"])

    def test_concurrent_runtime_participants_spawn_hidden_sessions_and_complete(self) -> None:
        repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="concurrent",
                run_id="concurrent-runtime",
                participants=[
                    _participant("researcher", "Researcher", execution_mode="child_runtime_session"),
                    _participant("reviewer", "Reviewer", execution_mode="child_runtime_session"),
                ],
                aggregator_participant_id="orchestrator",
                merge_policy="orchestrator_summarizes",
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
            final = RuntimeEventRecord(
                event_id=f"event-final-{session.session_id}",
                workspace_id="default",
                session_id=session.session_id,
                plane="turn",
                event_type="runtime.output.final",
                turn_id=turn_id,
                process_id=None,
                payload={"text": f"{session.agent_id} completed"},
                created_at=NOW,
            )
            completed = RuntimeEventRecord(
                event_id=f"event-completed-{session.session_id}",
                workspace_id="default",
                session_id=session.session_id,
                plane="turn",
                event_type="runtime.turn.completed",
                turn_id=turn_id,
                process_id=None,
                payload={},
                created_at=NOW,
            )
            state.runtime_store.save_turn(turn)
            state.runtime_store.save_event(final)
            state.runtime_store.save_event(completed)
            return turn, [final, completed]

        with patch("core.inter_agent.service.submit_runtime_turn", side_effect=fake_submit):
            result = execute_inter_agent_run(
                service,
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                input_text="Run both checks.",
                project_summaries=False,
                now=NOW,
            )

        child_sessions = [session for session in runtime_store.list_sessions("default") if session.session_id != "root-session"]
        ledger = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")

        self.assertEqual(result.run.status, "completed")
        self.assertEqual(sorted(session.thread_visibility for session in child_sessions), ["hidden", "hidden"])
        self.assertEqual(sorted(session.session_kind for session in child_sessions), ["inter_agent_participant", "inter_agent_participant"])
        self.assertEqual(ledger.running_participants, 0)
        self.assertEqual(ledger.turns_used, 2)
        self.assertEqual(
            sorted(result.runtime_session_id for result in result.participant_results),
            sorted(session.session_id for session in child_sessions),
        )

    def test_async_runtime_participant_waits_for_queued_turn_completion(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="concurrent",
                run_id="async-runtime",
                participants=[_participant("researcher", "Researcher", execution_mode="child_runtime_session")],
                aggregator_participant_id="orchestrator",
                merge_policy="orchestrator_summarizes",
            ),
            now=NOW,
        )

        def fake_submit_async(state, *, session, input_text, client_message_id=None):
            turn_id = f"turn-{session.session_id}"
            queued = RuntimeTurnRecord(
                turn_id=turn_id,
                session_id=session.session_id,
                workspace_id="default",
                status="queued",
                input_text=input_text,
                created_at=NOW,
                updated_at=NOW,
                started_at=None,
                completed_at=None,
                failure_reason=None,
            )
            completed = RuntimeTurnRecord(
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
            queued_event = RuntimeEventRecord(
                event_id=f"event-queued-{session.session_id}",
                workspace_id="default",
                session_id=session.session_id,
                plane="turn",
                event_type="runtime.turn.queued",
                turn_id=turn_id,
                process_id=None,
                payload={},
                created_at=NOW,
            )
            final = RuntimeEventRecord(
                event_id=f"event-final-{session.session_id}",
                workspace_id="default",
                session_id=session.session_id,
                plane="turn",
                event_type="runtime.output.final",
                turn_id=turn_id,
                process_id=None,
                payload={"text": "Async child completed."},
                created_at=NOW,
            )
            state.runtime_store.save_turn(queued)
            state.runtime_store.save_event(queued_event)
            state.runtime_store.save_turn(completed)
            state.runtime_store.save_event(final)
            return queued, [queued_event]

        with (
            patch("core.inter_agent.service.submit_runtime_turn", side_effect=AssertionError("sync path called")),
            patch("core.inter_agent.service.submit_runtime_turn_async", side_effect=fake_submit_async) as submit_async,
        ):
            result = execute_inter_agent_run(
                service,
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                input_text="Run the async child.",
                project_summaries=False,
                async_runtime_turns=True,
                now=NOW,
            )

        self.assertTrue(submit_async.called)
        self.assertEqual(result.run.status, "completed")
        self.assertEqual(len(result.participant_results), 1)
        self.assertEqual(result.participant_results[0].output_text, "Async child completed.")
        self.assertEqual(result.participant_results[0].status, "completed")

    def test_failed_controlled_participant_records_artifact_partial_before_failure(self) -> None:
        _repo_root, store, runtime_store = self._stores()
        service = InterAgentService(store)
        run = service.create_run(_run_spec(run_id="failure-artifact"), now=NOW)

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Produce a draft.",
            controlled_participants={
                "researcher": {
                    "status": "failed",
                    "partial_output": "Partial draft before failure.",
                    "artifact_refs": [{"app_id": "storage", "entity_type": "file", "entity_id": "partial-file"}],
                    "error": "controlled failure",
                }
            },
            allow_synthetic_participants=True,
            now=NOW,
        )
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        event_types = [event.event_type for event in events]
        artifact_index = event_types.index("inter_agent.artifact.created")
        failed_index = max(index for index, event in enumerate(events) if event.event_type == "inter_agent.run.failed")
        artifact_event = events[artifact_index]

        self.assertEqual(result.run.status, "failed")
        self.assertLess(artifact_index, failed_index)
        self.assertEqual(artifact_event.payload["partial_output"], "Partial draft before failure.")
        self.assertEqual(artifact_event.payload["artifact_refs"][0]["entity_id"], "partial-file")

if __name__ == "__main__":
    unittest.main()
