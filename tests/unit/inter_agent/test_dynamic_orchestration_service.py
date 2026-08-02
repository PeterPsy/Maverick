from __future__ import annotations

from datetime import UTC, datetime
import unittest

from core.inter_agent.errors import InterAgentOperationError, InterAgentValidationError
from core.inter_agent.models import (
    AgentParticipantSnapshot,
    BudgetPolicySpec,
    EdgeSpec,
    InterAgentRunSpec,
    ParticipantSpec,
)
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def snapshot() -> AgentParticipantSnapshot:
    return AgentParticipantSnapshot(
        agent_type_id="generalist",
        label="Generalist",
        system_prompt="Work carefully.",
        skill_ids=["storage"],
        skill_catalog_app_id="skills",
        provider_id="agents",
    )


def orchestrated_spec() -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id="root-session",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="orchestrated",
        created_by_user_id="user-1",
        participants=[
            ParticipantSpec(
                participant_id="orchestrator",
                kind="orchestrator",
                execution_mode="child_runtime_session",
                label="Orchestrator",
                agent_type_id="generalist",
                agent_snapshot=snapshot(),
            )
        ],
        budget=BudgetPolicySpec(
            max_participants=5,
            max_concurrent_participants=2,
            max_rounds=2,
            max_total_turns=8,
            max_turns_per_participant=4,
            max_tool_calls=8,
        ),
        visibility_level="detail",
        idempotency_key="orchestration-1",
        source_runtime_turn_id="generalist-turn-1",
        orchestration_policy="multi",
    )


class DynamicOrchestrationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        self.service = InterAgentService(self.store)
        self.run = self.service.create_run(orchestrated_spec(), now=NOW)

    def worker_spec(self, participant_id: str, label: str) -> ParticipantSpec:
        return ParticipantSpec(
            participant_id=participant_id,
            kind="agent",
            execution_mode="child_runtime_session",
            label=label,
            agent_type_id="generalist",
            agent_snapshot=snapshot(),
        )

    def test_adds_workers_and_edges_dynamically_and_idempotently(self) -> None:
        implementer = self.service.add_participant(
            workspace_id="default",
            run_id=self.run.run_id,
            spec=self.worker_spec("implementer", "Implementer"),
            now=NOW,
        )
        same_implementer = self.service.add_participant(
            workspace_id="default",
            run_id=self.run.run_id,
            spec=self.worker_spec("implementer", "Implementer"),
            now=NOW,
        )
        reviewer = self.service.add_participant(
            workspace_id="default",
            run_id=self.run.run_id,
            spec=self.worker_spec("reviewer", "Reviewer"),
            now=NOW,
        )
        edge = self.service.add_edge(
            workspace_id="default",
            run_id=self.run.run_id,
            spec=EdgeSpec(source_id=implementer.participant_id, target_id=reviewer.participant_id, kind="reviewed_by"),
            now=NOW,
        )
        same_edge = self.service.add_edge(
            workspace_id="default",
            run_id=self.run.run_id,
            spec=EdgeSpec(source_id=implementer.participant_id, target_id=reviewer.participant_id, kind="reviewed_by"),
            now=NOW,
        )

        self.assertEqual(implementer, same_implementer)
        self.assertEqual(edge, same_edge)
        self.assertEqual(
            [item.participant_id for item in self.store.list_participants(self.run.run_id, workspace_id="default")],
            ["orchestrator", "implementer", "reviewer"],
        )
        self.assertEqual(len(self.store.list_edges(self.run.run_id, workspace_id="default")), 1)

    def test_persists_and_delivers_generalist_directives_once(self) -> None:
        directive = self.service.record_directive(
            workspace_id="default",
            run_id=self.run.run_id,
            text="Prioritize the safer implementation.",
            source_kind="root_generalist",
            source_runtime_event_id="root-event-1",
            source_runtime_turn_id="generalist-turn-1",
            now=NOW,
        )

        self.assertEqual(self.service.pending_directives(self.run), [directive])

        self.service.mark_directives_delivered(self.run, [directive], now=NOW)

        self.assertEqual(self.service.pending_directives(self.run), [])
        later_link = self.service.link_generalist_directive(
            workspace_id="default",
            run_id=self.run.run_id,
            source_runtime_turn_id="other-turn",
            now=NOW,
        )
        self.assertEqual(self.service.pending_generalist_directive_links(self.run), [later_link])
        self.service.resolve_generalist_directive_link(self.run, later_link, status="ignored", now=NOW)
        self.assertEqual(self.service.pending_generalist_directive_links(self.run), [])
        with self.assertRaisesRegex(InterAgentValidationError, "linked runtime turn"):
            self.service.record_directive(
                workspace_id="default",
                run_id=self.run.run_id,
                text="Wrong turn.",
                source_kind="root_generalist",
            )

    def test_only_orchestrator_can_complete_after_quality_passes(self) -> None:
        self.service.add_participant(
            workspace_id="default",
            run_id=self.run.run_id,
            spec=self.worker_spec("reviewer", "Reviewer"),
            now=NOW,
        )

        with self.assertRaisesRegex(InterAgentOperationError, "Only the orchestrator"):
            self.service.decide_completion(
                workspace_id="default",
                run_id=self.run.run_id,
                participant_id="reviewer",
                complete=True,
                quality_passed=True,
                summary="Approved.",
                final_answer="Done.",
            )
        with self.assertRaisesRegex(InterAgentValidationError, "passing quality"):
            self.service.decide_completion(
                workspace_id="default",
                run_id=self.run.run_id,
                participant_id="orchestrator",
                complete=True,
                quality_passed=False,
                summary="Not approved.",
                final_answer="Done.",
            )

        completed = self.service.decide_completion(
            workspace_id="default",
            run_id=self.run.run_id,
            participant_id="orchestrator",
            complete=True,
            quality_passed=True,
            summary="Approved.",
            final_answer="Done.",
            now=NOW,
        )

        events = self.store.list_event_page(
            self.run.run_id,
            workspace_id="default",
            visibility_plane="detail",
            limit=100,
        ).events
        self.assertEqual(completed.status, "completed")
        self.assertIn("inter_agent.quality.assessed", [event.event_type for event in events])
        self.assertIn("inter_agent.completion.decided", [event.event_type for event in events])


if __name__ == "__main__":
    unittest.main()
