from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from core.inter_agent.adapters.base import AdapterEventMappingContext, InterAgentAdapterUnavailableError
from core.inter_agent.adapters.maf import (
    MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK,
    MafAdapter,
    map_maf_events_to_inter_agent_records,
)
from core.inter_agent.events import EventRetentionPolicyRecord
from core.inter_agent.models import InterAgentRunRecord
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


def _run() -> InterAgentRunRecord:
    return InterAgentRunRecord(
        run_id="run-maf-handoff",
        workspace_id="default",
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="handoff",
        status="running",
        created_by_user_id="user-1",
        orchestrator_participant_id="triage",
        budget_policy_id="budget-policy-1",
        budget_ledger_id="budget-ledger-1",
        visibility_level="detail",
        retention_policy_id="retention-1",
        created_at=NOW,
        updated_at=NOW,
        ended_at=None,
        recovery_generation=0,
    )


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


class MafAdapterTest(unittest.TestCase):
    def test_adapter_is_unavailable_when_feature_flag_is_off(self) -> None:
        with patch.dict(os.environ, {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK: "0"}):
            adapter = MafAdapter()

            self.assertFalse(adapter.is_enabled())
            self.assertFalse(adapter.is_available())
            with self.assertRaisesRegex(
                InterAgentAdapterUnavailableError,
                MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK,
            ):
                adapter.require_available()
            with self.assertRaisesRegex(
                InterAgentAdapterUnavailableError,
                MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK,
            ):
                adapter.map_events(AdapterEventMappingContext(run=_run(), created_at=NOW), [])

    def test_adapter_lazily_imports_maf_modules_when_flag_is_on(self) -> None:
        imported: list[str] = []

        def fake_import(name: str) -> ModuleType:
            imported.append(name)
            return ModuleType(name)

        with patch.dict(os.environ, {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK: "1"}):
            with patch("core.inter_agent.adapters.maf.importlib.import_module", side_effect=fake_import):
                MafAdapter().require_available()

        self.assertEqual(imported, ["agent_framework_orchestrations", "agent_framework"])

    def test_handoff_events_map_to_safe_inter_agent_records(self) -> None:
        context = AdapterEventMappingContext(
            run=_run(),
            visibility_plane="detail",
            sequence_start=40,
            event_id_prefix="iaevt-test",
            created_at=NOW,
        )
        raw_payload = {"chain_of_thought": "must not be persisted", "raw_state": {"secret": "unused"}}
        events = [
            {
                "event_type": "handoff_sent",
                "event_id": "maf-event-1",
                "source_participant_id": "triage",
                "target_participant_id": "specialist",
                "message": "Route billing question to specialist.",
                "correlation_id": "maf-correlation-1",
                "raw_payload": raw_payload,
            },
            SimpleNamespace(
                event_type="handoff_accepted",
                event_id="maf-event-2",
                source_participant_id="triage",
                target_participant_id="specialist",
                summary="Specialist accepted the transfer.",
            ),
            {
                "event_type": "handoff_completed",
                "event_id": "maf-event-3",
                "source_participant_id": "triage",
                "target_participant_id": "specialist",
                "summary": "Specialist completed the billing answer.",
            },
        ]

        records = map_maf_events_to_inter_agent_records(context, events)

        self.assertEqual(
            [record.event_type for record in records],
            [
                "inter_agent.handoff.requested",
                "inter_agent.handoff.accepted",
                "inter_agent.handoff.completed",
            ],
        )
        self.assertEqual([record.sequence for record in records], [41, 42, 43])
        self.assertEqual(len({record.event_id for record in records}), 3)
        self.assertTrue(records[0].event_id.startswith("iaevt-test-handoff_sent-"))
        self.assertTrue(records[1].event_id.startswith("iaevt-test-handoff_accepted-"))
        self.assertTrue(records[2].event_id.startswith("iaevt-test-handoff_completed-"))
        self.assertEqual(records[0].participant_id, "triage")
        self.assertEqual(records[1].participant_id, "specialist")
        self.assertEqual(records[2].participant_id, "specialist")
        self.assertEqual(records[0].correlation_id, "maf-correlation-1")
        self.assertEqual(records[0].idempotency_key, "run-maf-handoff:maf:handoff_sent:maf-event-1")
        self.assertEqual(records[0].payload["adapter"], "maf")
        self.assertEqual(records[0].payload["source_participant_id"], "triage")
        self.assertEqual(records[0].payload["target_participant_id"], "specialist")
        self.assertEqual(records[0].payload["summary"], "Route billing question to specialist.")
        self.assertNotIn("raw_payload", records[0].payload)
        self.assertNotIn("chain_of_thought", records[0].payload)

    def test_maf_workflow_event_shape_derives_handoff_lifecycle(self) -> None:
        context = AdapterEventMappingContext(
            run=_run(),
            visibility_plane="detail",
            sequence_start=50,
            event_id_prefix="iaevt-workflow",
            created_at=NOW,
        )
        events = [
            SimpleNamespace(
                type="handoff_sent",
                data=SimpleNamespace(source="triage", target="specialist"),
            ),
            SimpleNamespace(
                type="executor_invoked",
                executor_id="specialist",
                data=SimpleNamespace(should_respond=True),
            ),
            SimpleNamespace(
                type="output",
                executor_id="specialist",
                data=SimpleNamespace(text="accepted and completed"),
            ),
        ]

        records = map_maf_events_to_inter_agent_records(context, events)

        self.assertEqual(
            [record.event_type for record in records],
            [
                "inter_agent.handoff.requested",
                "inter_agent.handoff.accepted",
                "inter_agent.handoff.completed",
            ],
        )
        self.assertEqual([record.sequence for record in records], [51, 52, 53])
        self.assertEqual([record.participant_id for record in records], ["triage", "specialist", "specialist"])
        self.assertEqual(
            [record.payload["adapter_event_type"] for record in records],
            ["handoff_sent", "executor_invoked", "output"],
        )
        self.assertEqual(records[-1].payload["summary"], "accepted and completed")
        self.assertTrue(records[1].idempotency_key.startswith("run-maf-handoff:maf:executor_invoked:"))
        self.assertTrue(records[2].idempotency_key.startswith("run-maf-handoff:maf:output:"))

    def test_unknown_maf_events_are_not_projected(self) -> None:
        context = AdapterEventMappingContext(run=_run(), created_at=NOW)

        records = map_maf_events_to_inter_agent_records(
            context,
            [{"event_type": "group_chat_message", "message": "Future fixture."}],
        )

        self.assertEqual(records, [])

    def test_default_event_ids_do_not_collide_across_mapping_batches(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        context = AdapterEventMappingContext(run=_run(), created_at=NOW)
        retention = _retention()

        first = map_maf_events_to_inter_agent_records(
            context,
            [{"event_type": "handoff_sent", "event_id": "maf-event-1", "message": "First handoff."}],
        )[0]
        second = map_maf_events_to_inter_agent_records(
            context,
            [{"event_type": "handoff_sent", "event_id": "maf-event-2", "message": "Second handoff."}],
        )[0]

        stored_first = store.append_event(first, retention_policy=retention)
        stored_second = store.append_event(second, retention_policy=retention)

        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual(first.idempotency_key, "run-maf-handoff:maf:handoff_sent:maf-event-1")
        self.assertEqual(second.idempotency_key, "run-maf-handoff:maf:handoff_sent:maf-event-2")
        self.assertEqual([stored_first.sequence, stored_second.sequence], [1, 2])

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
