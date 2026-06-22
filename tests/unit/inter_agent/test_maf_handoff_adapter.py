from __future__ import annotations

from datetime import UTC, datetime
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


def _retention() -> EventRetentionPolicyRecord:
    return EventRetentionPolicyRecord(
        retention_policy_id="retention-1",
        workspace_id="default",
        summary_max_events=100,
        detail_max_events=100,
        debug_max_events=100,
        created_at=NOW,
    )


class MafHandoffAdapterTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
