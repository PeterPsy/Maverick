from __future__ import annotations

import asyncio
import os
import unittest

from core.inter_agent.adapters.base import AdapterEventMappingContext
from core.inter_agent.adapters.maf import MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK, MafAdapter
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.maf_group_chat_fixture import (
    GROUP_CHAT_EVENT_TYPES,
    NOW,
    assert_group_chat_records_are_safe,
    assert_run_participants_do_not_inherit_runtime_or_provider,
    group_chat_run_spec,
    load_maf_symbols,
    maf_group_chat_event_shape,
    run_controlled_maf_group_chat_budget_exhaustion,
    run_controlled_maf_group_chat_cancelled,
    run_controlled_maf_group_chat_manager,
    run_controlled_maf_group_chat_selector,
    with_manager_decision_observations,
)
from tests.support.repo import make_temp_repo_root


class MafGroupChatFixtureTest(unittest.IsolatedAsyncioTestCase):
    async def test_source_backed_group_chat_selector_events_map_append_and_replay(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(group_chat_run_spec(orchestrator_id="selector"), now=NOW)
        raw_events, decisions = await run_controlled_maf_group_chat_selector(maf)
        raw_shape = maf_group_chat_event_shape(raw_events)

        self.assertEqual(
            [(decision["round_index"], decision["selected_participant_id"]) for decision in decisions],
            [(0, "researcher"), (1, "writer")],
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
                and event["executor_id"] == "writer"
                and event["text"] == "final answer"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "output"
                and event["text"] == "The group chat has reached its termination condition."
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
                "inter_agent.task.started",
                "inter_agent.message.sent",
                "inter_agent.task.completed",
                "inter_agent.task.started",
                "inter_agent.message.sent",
                "inter_agent.task.completed",
                "inter_agent.summary.updated",
                "inter_agent.run.completed",
            ],
        )
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped],
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped_retry],
        )
        self.assertEqual(
            [
                record.payload["selected_participant_id"]
                for record in mapped
                if record.payload["observation_kind"] == "speaker_selection"
            ],
            ["researcher", "writer"],
        )

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
            event_types=GROUP_CHAT_EVENT_TYPES,
            limit=20,
        ).events
        after_first = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            event_types=GROUP_CHAT_EVENT_TYPES,
            after_event_id=replay[0].event_id,
            limit=20,
        ).events

        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        self.assertEqual([event.event_type for event in after_first], [event.event_type for event in stored[1:]])
        self.assertEqual(replay[-1].event_type, "inter_agent.run.completed")
        self.assertEqual(replay[-1].payload["terminal_status"], "completed")
        assert_group_chat_records_are_safe(self, replay)
        self.assertEqual(store.list_edges(run.run_id, workspace_id=run.workspace_id), [])
        assert_run_participants_do_not_inherit_runtime_or_provider(self, store, run.run_id)

    async def test_source_backed_group_chat_manager_decisions_stay_observational(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(group_chat_run_spec(orchestrator_id="manager"), now=NOW)
        raw_events, manager_decisions = await run_controlled_maf_group_chat_manager(maf)
        event_stream = with_manager_decision_observations(raw_events, manager_decisions)

        context = AdapterEventMappingContext(
            run=run,
            visibility_plane="detail",
            event_id_prefix=f"iaevt-{run.run_id}",
            created_at=NOW,
        )
        mapped = MafAdapter().map_events(context, event_stream)

        decision_records = [
            record
            for record in mapped
            if record.payload.get("observation_kind") == "manager_decision"
        ]
        self.assertEqual([record.payload["selected_participant_id"] for record in decision_records], ["researcher", "writer"])
        self.assertEqual([record.payload["summary"] for record in decision_records], ["need research", "write final"])
        self.assertTrue(all(record.event_type == "inter_agent.summary.updated" for record in decision_records))
        self.assertTrue(
            any(
                record.event_type == "inter_agent.message.sent"
                and record.participant_id == "writer"
                and record.payload["summary"] == "final answer"
                for record in mapped
            )
        )
        self.assertEqual(mapped[-1].event_type, "inter_agent.run.completed")
        self.assertEqual(store.list_edges(run.run_id, workspace_id=run.workspace_id), [])
        assert_group_chat_records_are_safe(self, mapped)
        assert_run_participants_do_not_inherit_runtime_or_provider(self, store, run.run_id)

    async def test_source_backed_group_chat_max_rounds_maps_budget_exhaustion(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(group_chat_run_spec(orchestrator_id="selector", max_rounds=1), now=NOW)
        raw_events = await run_controlled_maf_group_chat_budget_exhaustion(maf)

        mapped = MafAdapter().map_events(
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
                "inter_agent.task.started",
                "inter_agent.message.sent",
                "inter_agent.task.completed",
                "inter_agent.budget.exceeded",
                "inter_agent.run.failed",
            ],
        )
        self.assertEqual(mapped[-2].payload["budget_limit"], "max_rounds")
        self.assertEqual(mapped[-1].payload["terminal_status"], "failed")
        retention_policy = store.get_retention_policy(run.retention_policy_id, workspace_id=run.workspace_id)
        stored = [store.append_event(record, retention_policy=retention_policy) for record in mapped]
        stored_retry = [store.append_event(record, retention_policy=retention_policy) for record in mapped]
        self.assertEqual([event.event_id for event in stored], [event.event_id for event in stored_retry])
        self.assertEqual([event.sequence for event in stored], [event.sequence for event in stored_retry])
        replay = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            event_types=GROUP_CHAT_EVENT_TYPES,
            limit=20,
        ).events
        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        assert_group_chat_records_are_safe(self, replay)
        self.assertEqual(store.list_edges(run.run_id, workspace_id=run.workspace_id), [])
        assert_run_participants_do_not_inherit_runtime_or_provider(self, store, run.run_id)

    async def test_source_backed_group_chat_cancel_while_participant_running_maps_terminal_cancelled(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(group_chat_run_spec(orchestrator_id="selector"), now=NOW)
        raw_events = await run_controlled_maf_group_chat_cancelled(maf)

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
            ["inter_agent.task.started", "inter_agent.run.cancelled"],
        )
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped],
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped_retry],
        )
        self.assertEqual(mapped[0].participant_id, "researcher")
        self.assertEqual(mapped[0].payload["observation_kind"], "speaker_selection")
        self.assertEqual(mapped[0].payload["selected_participant_id"], "researcher")
        self.assertEqual(mapped[1].participant_id, "researcher")
        self.assertEqual(mapped[1].payload["observation_kind"], "terminal_cancelled")
        self.assertEqual(mapped[1].payload["terminal_status"], "cancelled")

        retention_policy = store.get_retention_policy(run.retention_policy_id, workspace_id=run.workspace_id)
        stored = [store.append_event(record, retention_policy=retention_policy) for record in mapped]
        stored_retry = [store.append_event(record, retention_policy=retention_policy) for record in mapped]
        self.assertEqual([event.event_id for event in stored], [event.event_id for event in stored_retry])
        self.assertEqual([event.sequence for event in stored], [event.sequence for event in stored_retry])
        replay = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            event_types=GROUP_CHAT_EVENT_TYPES,
            limit=20,
        ).events
        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        assert_group_chat_records_are_safe(self, replay)
        self.assertEqual(store.list_edges(run.run_id, workspace_id=run.workspace_id), [])
        assert_run_participants_do_not_inherit_runtime_or_provider(self, store, run.run_id)


if __name__ == "__main__":
    unittest.main()
