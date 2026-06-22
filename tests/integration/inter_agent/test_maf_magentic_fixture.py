from __future__ import annotations

import asyncio
import os
import unittest

from core.inter_agent.adapters.base import AdapterEventMappingContext
from core.inter_agent.adapters.maf import MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK, MafAdapter
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.maf_magentic_fixture import (
    MAGENTIC_EVENT_TYPES,
    NOW,
    assert_magentic_records_are_safe,
    assert_run_participants_do_not_inherit_runtime_or_provider,
    load_maf_symbols,
    maf_magentic_event_shape,
    magentic_run_spec,
    run_controlled_maf_magentic_manager,
    run_controlled_maf_magentic_max_rounds,
)
from tests.support.repo import make_temp_repo_root


class MafMagenticFixtureTest(unittest.IsolatedAsyncioTestCase):
    async def test_source_backed_magentic_manager_events_map_append_and_replay(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(magentic_run_spec(max_rounds=3), now=NOW)
        raw_events, call_counts = await run_controlled_maf_magentic_manager(maf)
        raw_shape = maf_magentic_event_shape(raw_events)

        self.assertEqual(call_counts, {"manager": 5, "researcher": 1, "writer": 0})
        self.assertTrue(
            any(
                event["type"] == "magentic_orchestrator"
                and event["orchestrator_event_type"] == "plan_created"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "magentic_orchestrator"
                and event["orchestrator_event_type"] == "progress_ledger_updated"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "group_chat"
                and event["data_type"] == "GroupChatRequestSentEvent"
                and event["participant_name"] == "researcher"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "intermediate"
                and event["executor_id"] == "researcher"
                and event["text"] == "research fact"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "output"
                and event["executor_id"] == "magentic_orchestrator"
                and event["text"] == "Final answer from manager."
                for event in raw_shape
            ),
            raw_shape,
        )

        context = AdapterEventMappingContext(
            run=run,
            visibility_plane="detail",
            event_id_prefix=f"iaevt-{run.run_id}",
            created_at=NOW,
        )
        adapter = MafAdapter()
        self.assertTrue(adapter.is_available())
        mapped = adapter.map_events(context, raw_events)
        mapped_retry = adapter.map_events(context, raw_events)

        self.assertEqual(
            [record.event_type for record in mapped],
            [
                "inter_agent.plan.summary_created",
                "inter_agent.summary.updated",
                "inter_agent.task.started",
                "inter_agent.message.sent",
                "inter_agent.task.completed",
                "inter_agent.summary.updated",
                "inter_agent.summary.updated",
                "inter_agent.run.completed",
            ],
        )
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped],
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped_retry],
        )
        self.assertEqual(mapped[0].participant_id, "manager")
        self.assertEqual(mapped[0].payload["observation_kind"], "plan_summary")
        self.assertIn("controlled plan", mapped[0].payload["summary"])
        self.assertEqual(mapped[1].payload["adapter_event_type"], "magentic_progress_updated")
        self.assertEqual(mapped[1].payload["progress_status"], "moving")
        self.assertEqual(mapped[1].payload["request_status"], "open")
        self.assertEqual(mapped[2].participant_id, "researcher")
        self.assertEqual(mapped[2].payload["observation_kind"], "participant_dispatch")
        self.assertEqual(mapped[3].payload["summary"], "research fact")
        self.assertEqual(mapped[5].payload["request_status"], "satisfied")
        self.assertEqual(mapped[-2].payload["summary"], "Final answer from manager.")
        self.assertEqual(mapped[-1].payload["terminal_status"], "completed")

        retention_policy = store.get_retention_policy(run.retention_policy_id, workspace_id=run.workspace_id)
        stored = [store.append_event(record, retention_policy=retention_policy) for record in mapped]
        stored_retry = [store.append_event(record, retention_policy=retention_policy) for record in mapped_retry]
        self.assertEqual([event.event_id for event in stored], [event.event_id for event in stored_retry])
        self.assertEqual([event.idempotency_key for event in stored], [event.idempotency_key for event in stored_retry])
        self.assertEqual([event.sequence for event in stored], [event.sequence for event in stored_retry])

        replay = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            event_types=MAGENTIC_EVENT_TYPES,
            limit=20,
        ).events
        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        assert_magentic_records_are_safe(self, replay)
        self.assertEqual(store.list_edges(run.run_id, workspace_id=run.workspace_id), [])
        assert_run_participants_do_not_inherit_runtime_or_provider(self, store, run.run_id)

    async def test_source_backed_magentic_stall_and_max_rounds_map_budget_failure(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(magentic_run_spec(max_rounds=1), now=NOW)
        raw_events, call_counts = await run_controlled_maf_magentic_max_rounds(maf)
        raw_shape = maf_magentic_event_shape(raw_events)

        self.assertEqual(call_counts, {"manager": 5, "researcher": 0})
        self.assertTrue(
            any(
                event["type"] == "magentic_orchestrator"
                and event["orchestrator_event_type"] == "replanned"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "output"
                and event["executor_id"] == "magentic_orchestrator"
                and event["text"] == "Workflow terminated due to reaching maximum round count."
                for event in raw_shape
            ),
            raw_shape,
        )

        mapped = MafAdapter().map_events(
            AdapterEventMappingContext(
                run=run,
                visibility_plane="detail",
                event_id_prefix=f"iaevt-{run.run_id}",
                created_at=NOW,
            ),
            raw_events,
        )
        mapped_retry = MafAdapter().map_events(
            AdapterEventMappingContext(
                run=run,
                visibility_plane="detail",
                event_id_prefix=f"iaevt-{run.run_id}",
                created_at=NOW,
            ),
            raw_events,
        )

        self.assertEqual(
            [record.event_type for record in mapped],
            [
                "inter_agent.plan.summary_created",
                "inter_agent.summary.updated",
                "inter_agent.plan.summary_created",
                "inter_agent.budget.exceeded",
                "inter_agent.run.failed",
            ],
        )
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped],
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped_retry],
        )
        self.assertEqual(mapped[1].payload["progress_status"], "stalled")
        self.assertEqual(mapped[1].payload["loop_status"], "loop_detected")
        self.assertEqual(mapped[1].payload["stall_detected"], "true")
        self.assertEqual(mapped[2].payload["observation_kind"], "replan_summary")
        self.assertEqual(mapped[3].payload["budget_limit"], "max_rounds")
        self.assertEqual(mapped[4].payload["terminal_status"], "failed")

        retention_policy = store.get_retention_policy(run.retention_policy_id, workspace_id=run.workspace_id)
        stored = [store.append_event(record, retention_policy=retention_policy) for record in mapped]
        stored_retry = [store.append_event(record, retention_policy=retention_policy) for record in mapped_retry]
        self.assertEqual([event.event_id for event in stored], [event.event_id for event in stored_retry])
        self.assertEqual([event.sequence for event in stored], [event.sequence for event in stored_retry])
        replay = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            event_types=MAGENTIC_EVENT_TYPES,
            limit=20,
        ).events
        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        assert_magentic_records_are_safe(self, replay)
        self.assertEqual(store.list_edges(run.run_id, workspace_id=run.workspace_id), [])
        assert_run_participants_do_not_inherit_runtime_or_provider(self, store, run.run_id)


if __name__ == "__main__":
    unittest.main()
