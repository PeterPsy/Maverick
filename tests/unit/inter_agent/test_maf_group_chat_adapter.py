from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
import unittest

from core.inter_agent.adapters.base import AdapterEventMappingContext
from core.inter_agent.adapters.maf import map_maf_events_to_inter_agent_records
from core.inter_agent.events import EventRetentionPolicyRecord
from core.inter_agent.models import InterAgentRunRecord
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


def _group_chat_run() -> InterAgentRunRecord:
    return InterAgentRunRecord(
        run_id="run-maf-group-chat",
        workspace_id="default",
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="group_chat",
        status="running",
        created_by_user_id="user-1",
        orchestrator_participant_id="selector",
        budget_policy_id="budget-policy-1",
        budget_ledger_id="budget-ledger-1",
        visibility_level="detail",
        retention_policy_id="retention-1",
        created_at=NOW,
        updated_at=NOW,
        ended_at=None,
        recovery_generation=0,
    )


def _retention() -> EventRetentionPolicyRecord:
    return EventRetentionPolicyRecord(
        retention_policy_id="retention-1",
        workspace_id="default",
        summary_max_events=100,
        detail_max_events=100,
        debug_max_events=100,
        created_at=NOW,
    )


class MafGroupChatAdapterTest(unittest.TestCase):
    def test_group_chat_events_map_safe_selection_output_and_terminal_records(self) -> None:
        context = AdapterEventMappingContext(
            run=_group_chat_run(),
            visibility_plane="detail",
            sequence_start=100,
            event_id_prefix="iaevt-group",
            created_at=NOW,
        )
        events = [
            SimpleNamespace(
                type="group_chat",
                data=GroupChatRequestSentEvent(round_index=0, participant_name="researcher"),
                raw_state={"messages": ["must not persist"]},
            ),
            SimpleNamespace(
                type="intermediate",
                executor_id="researcher",
                data=SimpleNamespace(text="research notes", messages=["raw message must not persist"]),
            ),
            SimpleNamespace(
                type="group_chat",
                data=GroupChatResponseReceivedEvent(round_index=1, participant_name="researcher"),
            ),
            SimpleNamespace(
                type="group_chat_manager_decision",
                source_event_id="manager-decision-1",
                round_index=1,
                selected_participant_id="writer",
                decision_source="manager_agent",
                summary="manager selected writer for the final answer",
            ),
            SimpleNamespace(
                type="group_chat",
                data=GroupChatRequestSentEvent(round_index=1, participant_name="writer"),
            ),
            SimpleNamespace(
                type="intermediate",
                executor_id="writer",
                data=SimpleNamespace(text="final answer"),
            ),
            SimpleNamespace(
                type="group_chat",
                data=GroupChatResponseReceivedEvent(round_index=2, participant_name="writer"),
            ),
            SimpleNamespace(
                type="output",
                executor_id="group_chat_orchestrator",
                data=SimpleNamespace(text="The group chat has reached its termination condition."),
            ),
        ]

        records = map_maf_events_to_inter_agent_records(context, events)
        records_retry = map_maf_events_to_inter_agent_records(context, events)

        self.assertEqual(
            [record.event_type for record in records],
            [
                "inter_agent.task.started",
                "inter_agent.message.sent",
                "inter_agent.task.completed",
                "inter_agent.summary.updated",
                "inter_agent.task.started",
                "inter_agent.message.sent",
                "inter_agent.task.completed",
                "inter_agent.summary.updated",
                "inter_agent.run.completed",
            ],
        )
        self.assertEqual([record.sequence for record in records], list(range(101, 110)))
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in records],
            [(record.event_id, record.idempotency_key, record.payload) for record in records_retry],
        )
        self.assertEqual(records[0].participant_id, "researcher")
        self.assertEqual(records[0].payload["observation_kind"], "speaker_selection")
        self.assertEqual(records[0].payload["selected_participant_id"], "researcher")
        self.assertEqual(records[0].payload["decision_source"], "maf_group_chat")
        self.assertEqual(records[1].participant_id, "researcher")
        self.assertEqual(records[1].payload["summary"], "research notes")
        self.assertEqual(records[3].participant_id, "selector")
        self.assertEqual(records[3].payload["observation_kind"], "manager_decision")
        self.assertEqual(records[3].payload["decision_source"], "manager_agent")
        self.assertEqual(records[3].payload["selected_participant_id"], "writer")
        self.assertEqual(records[-1].event_type, "inter_agent.run.completed")
        self.assertEqual(records[-1].participant_id, "selector")
        self.assertEqual(records[-1].payload["terminal_status"], "completed")
        for record in records:
            self.assertIsNone(record.runtime_session_id)
            self.assertIsNone(record.runtime_turn_id)
            self.assertIsNone(record.runtime_event_id)
            _assert_group_chat_payload_is_safe(self, record.payload)

    def test_group_chat_max_rounds_output_maps_budget_exhaustion_and_failure(self) -> None:
        context = AdapterEventMappingContext(
            run=_group_chat_run(),
            visibility_plane="detail",
            event_id_prefix="iaevt-budget",
            created_at=NOW,
        )

        records = map_maf_events_to_inter_agent_records(
            context,
            [
                SimpleNamespace(
                    type="output",
                    executor_id="group_chat_orchestrator",
                    data=SimpleNamespace(text="The group chat has reached the maximum number of rounds."),
                )
            ],
        )

        self.assertEqual(
            [record.event_type for record in records],
            ["inter_agent.budget.exceeded", "inter_agent.run.failed"],
        )
        self.assertEqual(records[0].payload["budget_limit"], "max_rounds")
        self.assertEqual(records[0].payload["summary"], "The group chat has reached the maximum number of rounds.")
        self.assertEqual(records[1].payload["terminal_status"], "failed")
        self.assertEqual([record.participant_id for record in records], ["selector", "selector"])
        for record in records:
            _assert_group_chat_payload_is_safe(self, record.payload)

    def test_group_chat_explicit_speaker_selection_stays_speaker_observation(self) -> None:
        context = AdapterEventMappingContext(
            run=_group_chat_run(),
            visibility_plane="detail",
            event_id_prefix="iaevt-speaker",
            created_at=NOW,
        )

        records = map_maf_events_to_inter_agent_records(
            context,
            [
                SimpleNamespace(
                    type="group_chat_speaker_selection",
                    round_index=2,
                    selected_participant_id="writer",
                    summary="speaker selector picked writer",
                )
            ],
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].event_type, "inter_agent.summary.updated")
        self.assertEqual(records[0].participant_id, "selector")
        self.assertEqual(records[0].payload["observation_kind"], "speaker_selection")
        self.assertEqual(records[0].payload["decision_source"], "maf_group_chat")
        self.assertEqual(records[0].payload["selected_participant_id"], "writer")
        self.assertEqual(records[0].payload["summary"], "speaker selector picked writer")
        self.assertNotEqual(records[0].payload["decision_source"], "manager_agent")
        _assert_group_chat_payload_is_safe(self, records[0].payload)

    def test_group_chat_split_terminal_output_namespaces_explicit_idempotency_key(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        context = AdapterEventMappingContext(
            run=_group_chat_run(),
            visibility_plane="detail",
            event_id_prefix="iaevt-terminal-explicit",
            created_at=NOW,
        )

        records = map_maf_events_to_inter_agent_records(
            context,
            [
                SimpleNamespace(
                    type="output",
                    idempotency_key="maf-terminal-output-1",
                    executor_id="group_chat_orchestrator",
                    data=SimpleNamespace(text="The group chat has reached its termination condition."),
                )
            ],
        )

        self.assertEqual(
            [record.event_type for record in records],
            ["inter_agent.summary.updated", "inter_agent.run.completed"],
        )
        self.assertEqual(
            [record.idempotency_key for record in records],
            [
                "run-maf-group-chat:maf:output:inter_agent.summary.updated:maf-terminal-output-1",
                "run-maf-group-chat:maf:output:inter_agent.run.completed:maf-terminal-output-1",
            ],
        )
        self.assertEqual(len({record.idempotency_key for record in records}), 2)
        retention = _retention()
        stored = [store.append_event(record, retention_policy=retention) for record in records]
        stored_retry = [store.append_event(record, retention_policy=retention) for record in records]
        self.assertEqual([event.event_id for event in stored], [event.event_id for event in stored_retry])
        self.assertEqual([event.sequence for event in stored], [event.sequence for event in stored_retry])


class GroupChatRequestSentEvent:
    def __init__(self, *, round_index: int, participant_name: str) -> None:
        self.round_index = round_index
        self.participant_name = participant_name


class GroupChatResponseReceivedEvent:
    def __init__(self, *, round_index: int, participant_name: str) -> None:
        self.round_index = round_index
        self.participant_name = participant_name


def _assert_group_chat_payload_is_safe(
    test_case: unittest.TestCase,
    payload: dict[str, object],
) -> None:
    test_case.assertLessEqual(
        set(payload),
        {
            "adapter",
            "adapter_event_type",
            "budget_limit",
            "decision_source",
            "observation_kind",
            "participant_id",
            "round_index",
            "selected_participant_id",
            "source_event_id",
            "summary",
            "terminal_status",
        },
    )
    encoded = json.dumps(payload, sort_keys=True, default=str).lower()
    for forbidden in (
        "raw_payload",
        "raw_state",
        "raw_representation",
        "chain_of_thought",
        "reasoning_trace",
        "messages",
        "provider",
        "secret",
        "session",
        "edge",
        "route",
        "group_chat_orchestrator",
    ):
        test_case.assertNotIn(forbidden, encoded)
    for value in payload.values():
        test_case.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main()
