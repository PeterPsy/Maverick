from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest

from core.inter_agent.errors import InterAgentValidationError
from core.inter_agent.events import InterAgentEventRecord, validate_event_record
from core.inter_agent.models import (
    AgentParticipantSnapshot,
    BudgetPolicySpec,
    EdgeSpec,
    InterAgentRunSpec,
    ParticipantSpec,
    validate_agent_snapshot,
    validate_run_spec,
)


class InterAgentModelValidationTest(unittest.TestCase):
    def valid_spec(self) -> InterAgentRunSpec:
        return InterAgentRunSpec(
            workspace_id="default",
            thread_id="thread-1",
            root_runtime_session_id="root-session",
            source_app_id="chat",
            mode="manager_tools",
            created_by_user_id="user-1",
            participants=[
                ParticipantSpec(
                    participant_id="orchestrator",
                    kind="orchestrator",
                    execution_mode="root_orchestrator",
                    label="Orchestrator",
                ),
                ParticipantSpec(
                    participant_id="researcher",
                    kind="agent",
                    execution_mode="child_runtime_session",
                    label="Researcher",
                    agent_type_id="research-agent",
                ),
            ],
            budget=BudgetPolicySpec(
                max_participants=3,
                max_concurrent_participants=2,
                max_total_turns=8,
                max_turns_per_participant=4,
                max_tool_calls=2,
                max_estimated_tokens=1000,
                max_estimated_cost=Decimal("1.50"),
            ),
        )

    def test_validates_manager_tools_run_without_runtime_sessions(self) -> None:
        spec = validate_run_spec(self.valid_spec())

        self.assertEqual(spec.participants[0].thread_visibility, "user")
        self.assertEqual(spec.participants[1].thread_visibility, "hidden")

    def test_orchestrated_run_starts_with_one_hidden_runtime_orchestrator(self) -> None:
        spec = InterAgentRunSpec(
            workspace_id="default",
            thread_id="thread-1",
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
                )
            ],
            budget=BudgetPolicySpec(max_participants=5, max_total_turns=8, max_turns_per_participant=4),
            source_runtime_turn_id="generalist-turn-1",
            orchestration_policy="multi",
        )

        validated = validate_run_spec(spec)

        self.assertEqual(validated.participants[0].thread_visibility, "hidden")

    def test_orchestrated_run_rejects_static_workers_and_edges(self) -> None:
        base = InterAgentRunSpec(
            workspace_id="default",
            thread_id="thread-1",
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
                ),
                ParticipantSpec(
                    participant_id="worker",
                    kind="agent",
                    execution_mode="child_runtime_session",
                    label="Worker",
                ),
            ],
            budget=BudgetPolicySpec(max_participants=5, max_total_turns=8, max_turns_per_participant=4),
            source_runtime_turn_id="generalist-turn-1",
        )

        with self.assertRaisesRegex(InterAgentValidationError, "start with only"):
            validate_run_spec(base)

    def test_concurrent_requires_aggregator_and_merge_policy(self) -> None:
        invalid = self.valid_spec()
        invalid = InterAgentRunSpec(
            **{
                **invalid.__dict__,
                "mode": "concurrent",
                "merge_policy": None,
                "aggregator_participant_id": "orchestrator",
            }
        )

        with self.assertRaisesRegex(InterAgentValidationError, "merge_policy"):
            validate_run_spec(invalid)

    def test_concurrent_aggregator_must_reference_existing_participant(self) -> None:
        invalid = self.valid_spec()
        invalid = InterAgentRunSpec(
            **{
                **invalid.__dict__,
                "mode": "concurrent",
                "merge_policy": "orchestrator_summarizes",
                "aggregator_participant_id": "missing",
            }
        )

        with self.assertRaisesRegex(InterAgentValidationError, "aggregator_participant_id"):
            validate_run_spec(invalid)

    def test_group_chat_requires_non_orchestrator_aggregator(self) -> None:
        spec = self.valid_spec()
        no_aggregator = InterAgentRunSpec(**{**spec.__dict__, "mode": "group_chat"})
        orchestrator_aggregator = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "mode": "group_chat",
                "aggregator_participant_id": "orchestrator",
            }
        )
        valid = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "mode": "group_chat",
                "aggregator_participant_id": "researcher",
            }
        )

        with self.assertRaisesRegex(InterAgentValidationError, "aggregator_participant_id"):
            validate_run_spec(no_aggregator)
        with self.assertRaisesRegex(InterAgentValidationError, "non-orchestrator"):
            validate_run_spec(orchestrator_aggregator)
        self.assertEqual(validate_run_spec(valid).aggregator_participant_id, "researcher")

    def test_handoff_edge_must_reference_existing_participants(self) -> None:
        spec = self.valid_spec()
        invalid = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "edges": [
                    EdgeSpec(
                        source_id="researcher",
                        target_id="missing-reviewer",
                        kind="handed_off",
                    )
                ],
            }
        )

        with self.assertRaisesRegex(InterAgentValidationError, "target participant"):
            validate_run_spec(invalid)

    def test_budget_max_participants_is_enforced_by_spec(self) -> None:
        spec = self.valid_spec()
        invalid = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "budget": BudgetPolicySpec(
                    max_participants=1,
                    max_concurrent_participants=1,
                    max_total_turns=2,
                    max_turns_per_participant=1,
                ),
            }
        )

        with self.assertRaisesRegex(InterAgentValidationError, "max_participants"):
            validate_run_spec(invalid)

    def test_child_runtime_session_rejects_user_thread_visibility(self) -> None:
        spec = self.valid_spec()
        participants = list(spec.participants)
        participants[1] = ParticipantSpec(
            participant_id="researcher",
            kind="agent",
            execution_mode="child_runtime_session",
            label="Researcher",
            thread_visibility="user",
        )
        invalid = InterAgentRunSpec(**{**spec.__dict__, "participants": participants})

        with self.assertRaisesRegex(InterAgentValidationError, "hidden thread visibility"):
            validate_run_spec(invalid)

    def test_agent_snapshot_digest_is_stable_and_order_independent_for_skills(self) -> None:
        first = AgentParticipantSnapshot(
            agent_type_id="reviewer",
            label="Reviewer",
            system_prompt="Review carefully.",
            skill_ids=["storage", "memory"],
            skill_catalog_app_id="skills",
            provider_id="codex",
            revision_id="r1",
        )
        second = AgentParticipantSnapshot(
            agent_type_id="reviewer",
            label="Reviewer",
            system_prompt="Review carefully.",
            skill_ids=["memory", "storage"],
            skill_catalog_app_id="skills",
            provider_id="codex",
            revision_id="r1",
        )

        self.assertEqual(first.digest(), second.digest())

    def test_agent_snapshot_allows_empty_system_prompt(self) -> None:
        snapshot = AgentParticipantSnapshot(
            agent_type_id="reviewer",
            label="Reviewer",
            system_prompt="",
            skill_ids=["storage"],
            skill_catalog_app_id="skills",
        )

        self.assertIs(validate_agent_snapshot(snapshot), snapshot)

    def test_user_visible_event_payload_rejects_raw_chain_of_thought(self) -> None:
        event = InterAgentEventRecord(
            event_id="event-1",
            workspace_id="default",
            run_id="run-1",
            thread_id="thread-1",
            root_runtime_session_id="root-session",
            participant_id="orchestrator",
            runtime_session_id=None,
            runtime_turn_id=None,
            runtime_event_id=None,
            event_type="inter_agent.summary.updated",
            visibility_plane="summary",
            sequence=1,
            correlation_id="corr-1",
            idempotency_key="idem-1",
            payload={"chain_of_thought": "hidden reasoning"},
            created_at=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(InterAgentValidationError, "raw reasoning"):
            validate_event_record(event)


if __name__ == "__main__":
    unittest.main()
