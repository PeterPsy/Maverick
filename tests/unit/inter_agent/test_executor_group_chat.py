from __future__ import annotations

import unittest

from core.inter_agent.executor import execute_inter_agent_run
from core.inter_agent.models import EdgeSpec
from core.inter_agent.service import InterAgentService
from tests.unit.inter_agent.executor_test_support import (
    NOW,
    build_executor_stores,
    participant_spec as _participant,
    run_spec as _run_spec,
    runtime_state_namespace as _state,
)


class InterAgentGroupChatExecutorTest(unittest.TestCase):
    def test_group_chat_controlled_run_uses_shared_context_and_aggregator(self) -> None:
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="group_chat",
                run_id="group-chat-controlled",
                participants=[
                    _participant("analyst", "Analyst"),
                    _participant("reviewer", "Reviewer"),
                    _participant("synthesizer", "Synthesizer"),
                ],
                aggregator_participant_id="synthesizer",
                edges=[
                    EdgeSpec(
                        source_id="synthesizer",
                        target_id="orchestrator",
                        kind="produced",
                        label="Final synthesis",
                    ),
                ],
            ),
            now=NOW,
        )

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Compare the rollout options.",
            participant_inputs={
                "analyst": "Analyze the options.",
                "reviewer": "Review for risks.",
                "synthesizer": "Produce the final answer.",
            },
            controlled_participants={
                "analyst": {"output_text": "Option A is faster.", "summary": "Analyst favors speed."},
                "reviewer": {"output_text": "Option B has lower risk.", "summary": "Reviewer flags risk."},
                "synthesizer": {"output_text": "Choose option B with a staged rollout.", "summary": "Synthesis is ready."},
            },
            allow_synthetic_participants=True,
            now=NOW,
        )

        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        message_events = [event for event in events if event.event_type == "inter_agent.message.sent"]
        plan_event = next(event for event in events if event.event_type == "inter_agent.plan.summary_created")

        self.assertEqual(result.run.status, "completed")
        self.assertEqual(result.final_answer, "Choose option B with a staged rollout.")
        self.assertEqual(plan_event.payload["summary"], "Orchestrator started a group chat run with 3 worker nodes.")
        self.assertEqual([event.participant_id for event in message_events], ["analyst", "reviewer", "synthesizer"])
        self.assertIn("You are one participant in a Maverick group chat run.", message_events[0].payload["input_text"])
        self.assertIn("Prior participant outputs in this group chat round", message_events[2].payload["input_text"])
        self.assertIn("Analyst: Option A is faster.", message_events[2].payload["input_text"])
        self.assertIn("Reviewer: Option B has lower risk.", message_events[2].payload["input_text"])

    def test_group_chat_runs_aggregator_after_contributors_regardless_of_payload_order(self) -> None:
        _repo_root, store, runtime_store = build_executor_stores(self)
        service = InterAgentService(store)
        run = service.create_run(
            _run_spec(
                mode="group_chat",
                run_id="group-chat-aggregator-order",
                participants=[
                    _participant("synthesizer", "Synthesizer"),
                    _participant("analyst", "Analyst"),
                    _participant("reviewer", "Reviewer"),
                ],
                aggregator_participant_id="synthesizer",
                edges=[
                    EdgeSpec(
                        source_id="synthesizer",
                        target_id="orchestrator",
                        kind="produced",
                        label="Final synthesis",
                    ),
                ],
            ),
            now=NOW,
        )

        result = execute_inter_agent_run(
            service,
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            input_text="Compare the rollout options.",
            participant_inputs={
                "analyst": "Analyze the options.",
                "reviewer": "Review for risks.",
                "synthesizer": "Produce the final answer.",
            },
            controlled_participants={
                "analyst": {"output_text": "Option A is faster.", "summary": "Analyst favors speed."},
                "reviewer": {"output_text": "Option B has lower risk.", "summary": "Reviewer flags risk."},
                "synthesizer": {"output_text": "Choose option B with a staged rollout.", "summary": "Synthesis is ready."},
            },
            allow_synthetic_participants=True,
            now=NOW,
        )

        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=100).events
        message_events = [event for event in events if event.event_type == "inter_agent.message.sent"]

        self.assertEqual(result.run.status, "completed")
        self.assertEqual(result.final_answer, "Choose option B with a staged rollout.")
        self.assertEqual([event.participant_id for event in message_events], ["analyst", "reviewer", "synthesizer"])
        self.assertIn("Analyst: Option A is faster.", message_events[2].payload["input_text"])
        self.assertIn("Reviewer: Option B has lower risk.", message_events[2].payload["input_text"])
