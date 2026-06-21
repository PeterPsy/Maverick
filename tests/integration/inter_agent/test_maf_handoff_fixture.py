from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

from core.inter_agent.adapters.base import (
    AdapterEventMappingContext,
    InterAgentAdapterUnavailableError,
)
from core.inter_agent.adapters.maf import MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK, MafAdapter
from core.inter_agent.models import BudgetPolicySpec, InterAgentRunSpec, ParticipantSpec
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 6, 21, 12, 30, tzinfo=UTC)
HANDOFF_EVENT_TYPES = {
    "inter_agent.handoff.requested",
    "inter_agent.handoff.accepted",
    "inter_agent.handoff.completed",
}


class MafHandoffFixtureTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_source_backed_handoff_events_map_append_and_replay(self) -> None:
        asyncio.get_running_loop().slow_callback_duration = 5.0
        if os.environ.get(MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK) != "1":
            self.skipTest(f"Source-backed MAF fixture requires {MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1.")
        maf = _load_maf_symbols(self)
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(_handoff_run_spec(), now=NOW)
        raw_events = await _run_controlled_maf_handoff(maf)
        raw_shape = _maf_event_shape(raw_events)

        self.assertTrue(
            any(
                event["type"] == "handoff_sent"
                and event["data_type"] == "HandoffSentEvent"
                and event["source"] == "triage"
                and event["target"] == "specialist"
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "executor_invoked"
                and event["executor_id"] == "specialist"
                and event["should_respond"] is True
                for event in raw_shape
            ),
            raw_shape,
        )
        self.assertTrue(
            any(
                event["type"] == "output"
                and event["executor_id"] == "specialist"
                and event["text"] == "accepted and completed"
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
                "inter_agent.handoff.requested",
                "inter_agent.handoff.accepted",
                "inter_agent.handoff.completed",
            ],
        )
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped],
            [(record.event_id, record.idempotency_key, record.payload) for record in mapped_retry],
        )
        self.assertEqual(
            [record.payload["adapter_event_type"] for record in mapped],
            ["handoff_sent", "executor_invoked", "output"],
        )
        self.assertEqual(
            [record.participant_id for record in mapped],
            ["triage", "specialist", "specialist"],
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
            event_types=HANDOFF_EVENT_TYPES,
            limit=10,
        ).events
        after_requested = store.list_event_page(
            run.run_id,
            workspace_id=run.workspace_id,
            visibility_plane="debug",
            event_types=HANDOFF_EVENT_TYPES,
            after_event_id=replay[0].event_id,
            limit=10,
        ).events

        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        self.assertEqual(
            [event.event_type for event in after_requested],
            ["inter_agent.handoff.accepted", "inter_agent.handoff.completed"],
        )
        self.assertEqual(replay[-1].payload["summary"], "accepted and completed")

        for event in replay:
            self.assertIsNone(event.runtime_session_id)
            self.assertIsNone(event.runtime_turn_id)
            self.assertIsNone(event.runtime_event_id)
            _assert_payload_is_safe_maverick_projection(self, event.payload)

        participants = store.list_participants(run.run_id, workspace_id=run.workspace_id)
        self.assertEqual([participant.participant_id for participant in participants], ["triage", "specialist"])
        for participant in participants:
            self.assertIsNone(participant.provider_id)
            self.assertIsNone(participant.runtime_session_id)
            self.assertEqual(participant.authority_grant_ids, [])


def _handoff_run_spec() -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id="thread-maf-handoff",
        root_runtime_session_id="root-runtime-session",
        source_app_id="chat",
        mode="handoff",
        created_by_user_id="user-1",
        participants=[
            ParticipantSpec(
                participant_id="triage",
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label="Triage",
            ),
            ParticipantSpec(
                participant_id="specialist",
                kind="agent",
                execution_mode="embedded_executor",
                label="Specialist",
            ),
        ],
        budget=BudgetPolicySpec(
            max_participants=2,
            max_concurrent_participants=2,
            max_handoffs=1,
            max_rounds=1,
            max_total_turns=2,
            max_turns_per_participant=1,
            max_tool_calls=0,
            max_estimated_cost=Decimal("0"),
        ),
        visibility_level="detail",
        idempotency_key="maf-handoff-source-backed-fixture",
    )


def _load_maf_symbols(test_case: unittest.TestCase) -> SimpleNamespace:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from agent_framework import (  # type: ignore[import-not-found]
                Agent,
                BaseChatClient,
                ChatMiddlewareLayer,
                ChatResponse,
                Content,
                FunctionInvocationLayer,
                Message,
            )
            from agent_framework_orchestrations import HandoffBuilder  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError) as exc:
        test_case.fail(
            f"MAF optional dependency is unavailable while "
            f"{MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK}=1: {exc}"
        )
    return SimpleNamespace(
        Agent=Agent,
        BaseChatClient=BaseChatClient,
        ChatMiddlewareLayer=ChatMiddlewareLayer,
        ChatResponse=ChatResponse,
        Content=Content,
        FunctionInvocationLayer=FunctionInvocationLayer,
        HandoffBuilder=HandoffBuilder,
        Message=Message,
    )


async def _run_controlled_maf_handoff(maf: SimpleNamespace) -> list[object]:
    class ControlledMafChatClient(
        maf.FunctionInvocationLayer,
        maf.ChatMiddlewareLayer,
        maf.BaseChatClient,
    ):
        def __init__(self, responses: list[object]) -> None:
            self.responses = list(responses)
            self.calls: list[object] = []
            super().__init__()

        async def _inner_get_response(self, *, messages, stream, options, **kwargs):
            if stream:
                raise AssertionError("The MAF handoff fixture uses non-streaming fake provider responses.")
            await self._validate_options(options)
            self.calls.append((list(messages), dict(options), dict(kwargs)))
            if self.responses:
                return self.responses.pop(0)
            return maf.ChatResponse(
                messages=[maf.Message(role="assistant", contents=["done"])],
                response_id="controlled-default",
            )

    triage_client = ControlledMafChatClient([
        maf.ChatResponse(
            messages=[
                maf.Message(
                    role="assistant",
                    contents=[
                        maf.Content.from_function_call(
                            "call-triage-specialist",
                            "handoff_to_specialist",
                            arguments={},
                        )
                    ],
                )
            ],
            response_id="triage-response-1",
            finish_reason="tool_calls",
        )
    ])
    specialist_client = ControlledMafChatClient([
        maf.ChatResponse(
            messages=[maf.Message(role="assistant", contents=["accepted and completed"])],
            response_id="specialist-response-1",
        )
    ])
    triage = maf.Agent(
        triage_client,
        name="triage",
        require_per_service_call_history_persistence=True,
    )
    specialist = maf.Agent(
        specialist_client,
        name="specialist",
        require_per_service_call_history_persistence=True,
    )
    workflow = (
        maf.HandoffBuilder(participants=[triage, specialist])
        .add_handoff(triage, [specialist], description="route billing question to specialist")
        .add_handoff(specialist, [triage], description="return to triage if more triage is needed")
        .with_start_agent(triage)
        .with_termination_condition(
            lambda conversation: bool(conversation) and "accepted" in conversation[-1].text
        )
        .build()
    )
    result = await workflow.run("billing question")
    if result.get_final_state().value != "IDLE":
        raise AssertionError(f"Unexpected MAF workflow final state: {result.get_final_state()}")
    if len(triage_client.calls) != 1 or len(specialist_client.calls) != 1:
        raise AssertionError(
            f"Unexpected fake provider call counts: triage={len(triage_client.calls)}, "
            f"specialist={len(specialist_client.calls)}"
        )
    return list(result)


def _maf_event_shape(events: list[object]) -> list[dict[str, object]]:
    shape: list[dict[str, object]] = []
    for event in events:
        data = getattr(event, "data", None)
        shape.append(
            {
                "type": getattr(event, "type", None),
                "executor_id": getattr(event, "executor_id", None),
                "data_type": type(data).__name__ if data is not None else None,
                "source": getattr(data, "source", None),
                "target": getattr(data, "target", None),
                "should_respond": getattr(data, "should_respond", None),
                "text": getattr(data, "text", None),
            }
        )
    return shape


def _assert_payload_is_safe_maverick_projection(
    test_case: unittest.TestCase,
    payload: dict[str, object],
) -> None:
    test_case.assertLessEqual(
        set(payload),
        {
            "adapter",
            "adapter_event_type",
            "source_event_id",
            "source_participant_id",
            "target_participant_id",
            "summary",
            "task_id",
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
    ):
        test_case.assertNotIn(forbidden, encoded)
    for value in payload.values():
        test_case.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main()
