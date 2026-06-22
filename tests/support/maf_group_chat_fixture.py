from __future__ import annotations

import asyncio
import contextlib
import json
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest

from core.inter_agent.adapters.maf import MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK
from core.inter_agent.models import BudgetPolicySpec, EdgeSpec, InterAgentRunSpec, ParticipantSpec


NOW = datetime(2026, 6, 21, 13, 15, tzinfo=UTC)
GROUP_CHAT_EVENT_TYPES = {
    "inter_agent.task.started",
    "inter_agent.message.sent",
    "inter_agent.task.completed",
    "inter_agent.summary.updated",
    "inter_agent.budget.exceeded",
    "inter_agent.run.completed",
    "inter_agent.run.failed",
    "inter_agent.run.cancelled",
}


def group_chat_run_spec(*, orchestrator_id: str, max_rounds: int = 3) -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id=f"thread-maf-group-chat-{orchestrator_id}",
        root_runtime_session_id="root-runtime-session",
        source_app_id="chat",
        mode="group_chat",
        created_by_user_id="user-1",
        participants=[
            ParticipantSpec(
                participant_id=orchestrator_id,
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label=orchestrator_id.title(),
            ),
            ParticipantSpec(
                participant_id="researcher",
                kind="agent",
                execution_mode="embedded_executor",
                label="Researcher",
            ),
            ParticipantSpec(
                participant_id="writer",
                kind="agent",
                execution_mode="embedded_executor",
                label="Writer",
            ),
        ],
        budget=BudgetPolicySpec(
            max_participants=3,
            max_concurrent_participants=3,
            max_handoffs=0,
            max_rounds=max_rounds,
            max_total_turns=4,
            max_turns_per_participant=2,
            max_tool_calls=0,
            max_estimated_cost=Decimal("0"),
        ),
        aggregator_participant_id="writer",
        edges=[
            EdgeSpec(source_id="writer", target_id=orchestrator_id, kind="produced", label="Final group chat output"),
        ],
        visibility_level="detail",
        idempotency_key=f"maf-group-chat-source-backed-{orchestrator_id}-{max_rounds}",
    )


def load_maf_symbols(test_case: unittest.TestCase) -> SimpleNamespace:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from agent_framework import (  # type: ignore[import-not-found]
                Agent,
                BaseChatClient,
                ChatMiddlewareLayer,
                ChatResponse,
                FunctionInvocationLayer,
                Message,
            )
            from agent_framework_orchestrations import GroupChatBuilder  # type: ignore[import-not-found]
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
        FunctionInvocationLayer=FunctionInvocationLayer,
        GroupChatBuilder=GroupChatBuilder,
        Message=Message,
    )


async def run_controlled_maf_group_chat_selector(
    maf: SimpleNamespace,
) -> tuple[list[object], list[dict[str, object]]]:
    researcher_client = _ControlledMafChatClient(maf, "researcher", ["research notes"])
    writer_client = _ControlledMafChatClient(maf, "writer", ["final answer"])
    decisions: list[dict[str, object]] = []

    def select_next(state: object) -> str:
        round_index = int(getattr(state, "current_round"))
        selected = "researcher" if round_index == 0 else "writer"
        decisions.append({"round_index": round_index, "selected_participant_id": selected})
        return selected

    workflow = maf.GroupChatBuilder(
        participants=[
            maf.Agent(
                researcher_client,
                name="researcher",
                description="find facts",
                require_per_service_call_history_persistence=True,
            ),
            maf.Agent(
                writer_client,
                name="writer",
                description="write answer",
                require_per_service_call_history_persistence=True,
            ),
        ],
        selection_func=select_next,
        orchestrator_name="selector",
        max_rounds=3,
        termination_condition=lambda conversation: bool(conversation)
        and "final answer" in conversation[-1].text,
        intermediate_output_from="all",
    ).build()
    result = await workflow.run("write a brief market note")
    _assert_idle_result(result)
    if len(researcher_client.calls) != 1 or len(writer_client.calls) != 1:
        raise AssertionError(
            f"Unexpected fake provider call counts: researcher={len(researcher_client.calls)}, "
            f"writer={len(writer_client.calls)}"
        )
    return list(result), decisions


async def run_controlled_maf_group_chat_manager(
    maf: SimpleNamespace,
) -> tuple[list[object], list[dict[str, object]]]:
    manager_responses = [
        {"terminate": False, "reason": "need research", "next_speaker": "researcher"},
        {"terminate": False, "reason": "write final", "next_speaker": "writer"},
    ]
    manager_client = _ControlledMafChatClient(
        maf,
        "manager",
        [json.dumps(response, sort_keys=True) for response in manager_responses],
    )
    researcher_client = _ControlledMafChatClient(maf, "researcher", ["research notes"])
    writer_client = _ControlledMafChatClient(maf, "writer", ["final answer"])
    workflow = maf.GroupChatBuilder(
        participants=[
            maf.Agent(
                researcher_client,
                name="researcher",
                description="find facts",
                require_per_service_call_history_persistence=True,
            ),
            maf.Agent(
                writer_client,
                name="writer",
                description="write answer",
                require_per_service_call_history_persistence=True,
            ),
        ],
        orchestrator_agent=maf.Agent(
            manager_client,
            name="manager",
            require_per_service_call_history_persistence=True,
        ),
        max_rounds=3,
        termination_condition=lambda conversation: bool(conversation)
        and "final answer" in conversation[-1].text,
        intermediate_output_from="all",
    ).build()
    result = await workflow.run("write a brief market note")
    _assert_idle_result(result)
    if len(manager_client.calls) != 2 or len(researcher_client.calls) != 1 or len(writer_client.calls) != 1:
        raise AssertionError(
            f"Unexpected fake provider call counts: manager={len(manager_client.calls)}, "
            f"researcher={len(researcher_client.calls)}, writer={len(writer_client.calls)}"
        )
    return list(result), manager_responses


async def run_controlled_maf_group_chat_budget_exhaustion(maf: SimpleNamespace) -> list[object]:
    researcher_client = _ControlledMafChatClient(maf, "researcher", ["research notes"])
    writer_client = _ControlledMafChatClient(maf, "writer", ["unused writer response"])

    def select_next(_: object) -> str:
        return "researcher"

    workflow = maf.GroupChatBuilder(
        participants=[
            maf.Agent(
                researcher_client,
                name="researcher",
                description="find facts",
                require_per_service_call_history_persistence=True,
            ),
            maf.Agent(
                writer_client,
                name="writer",
                description="write answer",
                require_per_service_call_history_persistence=True,
            ),
        ],
        selection_func=select_next,
        orchestrator_name="selector",
        max_rounds=1,
        intermediate_output_from="all",
    ).build()
    result = await workflow.run("write a brief market note")
    _assert_idle_result(result)
    if len(researcher_client.calls) != 1 or writer_client.calls:
        raise AssertionError(
            f"Unexpected fake provider call counts: researcher={len(researcher_client.calls)}, "
            f"writer={len(writer_client.calls)}"
        )
    return list(result)


async def run_controlled_maf_group_chat_cancelled(maf: SimpleNamespace) -> list[object]:
    researcher_client = _BlockingMafChatClient(maf, "researcher")
    writer_client = _ControlledMafChatClient(maf, "writer", ["unused writer response"])

    def select_next(_: object) -> str:
        return "researcher"

    workflow = maf.GroupChatBuilder(
        participants=[
            maf.Agent(
                researcher_client,
                name="researcher",
                description="find facts",
                require_per_service_call_history_persistence=True,
            ),
            maf.Agent(
                writer_client,
                name="writer",
                description="write answer",
                require_per_service_call_history_persistence=True,
            ),
        ],
        selection_func=select_next,
        orchestrator_name="selector",
        max_rounds=3,
        intermediate_output_from="all",
    ).build()
    stream = workflow.run("write a brief market note", stream=True)
    raw_events: list[object] = []

    async def consume_stream() -> None:
        async for event in stream:
            raw_events.append(event)

    task = asyncio.create_task(consume_stream())
    await asyncio.wait_for(researcher_client.started.wait(), timeout=5)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await asyncio.wait_for(researcher_client.cancelled.wait(), timeout=5)

    if len(researcher_client.calls) != 1 or writer_client.calls:
        raise AssertionError(
            f"Unexpected fake provider call counts: researcher={len(researcher_client.calls)}, "
            f"writer={len(writer_client.calls)}"
        )
    if not any(
        getattr(event, "type", None) == "group_chat"
        and type(getattr(event, "data", None)).__name__ == "GroupChatRequestSentEvent"
        and getattr(getattr(event, "data", None), "participant_name", None) == "researcher"
        for event in raw_events
    ):
        raise AssertionError(f"MAF group_chat did not emit a request event before cancellation: {raw_events!r}")

    raw_events.append(
        SimpleNamespace(
            type="group_chat_cancelled",
            source_event_id="cancel-while-researcher-running",
            participant_id="researcher",
            summary="MAF group_chat run cancelled while participant was running.",
        )
    )
    return raw_events


class _ControlledMafChatClient:
    def __new__(cls, maf: SimpleNamespace, name: str, responses: list[str]) -> object:
        class ControlledMafChatClient(
            maf.FunctionInvocationLayer,
            maf.ChatMiddlewareLayer,
            maf.BaseChatClient,
        ):
            def __init__(self) -> None:
                self.name = name
                self.responses = list(responses)
                self.calls: list[object] = []
                super().__init__()

            async def _inner_get_response(self, *, messages, stream, options, **kwargs):
                if stream:
                    raise AssertionError("The MAF group_chat fixture uses non-streaming fake provider responses.")
                await self._validate_options(options)
                self.calls.append((list(messages), dict(options), dict(kwargs)))
                if not self.responses:
                    raise AssertionError(f"No controlled fake response remains for {self.name}.")
                response_text = self.responses.pop(0)
                return maf.ChatResponse(
                    messages=[maf.Message(role="assistant", contents=[response_text], author_name=self.name)],
                    response_id=f"{self.name}-response-{len(self.calls)}",
                )

        return ControlledMafChatClient()


class _BlockingMafChatClient:
    def __new__(cls, maf: SimpleNamespace, name: str) -> object:
        class BlockingMafChatClient(
            maf.FunctionInvocationLayer,
            maf.ChatMiddlewareLayer,
            maf.BaseChatClient,
        ):
            def __init__(self) -> None:
                self.name = name
                self.started = asyncio.Event()
                self.cancelled = asyncio.Event()
                self.calls: list[object] = []
                super().__init__()

            async def _inner_get_response(self, *, messages, stream, options, **kwargs):
                await self._validate_options(options)
                self.calls.append((list(messages), dict(options), dict(kwargs)))
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise

        return BlockingMafChatClient()


def with_manager_decision_observations(
    raw_events: list[object],
    manager_decisions: list[dict[str, object]],
) -> list[object]:
    merged: list[object] = []
    decision_index = 0
    for event in raw_events:
        data = getattr(event, "data", None)
        if (
            getattr(event, "type", None) == "group_chat"
            and type(data).__name__ == "GroupChatRequestSentEvent"
            and decision_index < len(manager_decisions)
        ):
            decision = manager_decisions[decision_index]
            merged.append(
                SimpleNamespace(
                    type="group_chat_manager_decision",
                    source_event_id=f"manager-decision-{decision_index + 1}",
                    round_index=decision_index,
                    selected_participant_id=str(decision["next_speaker"]),
                    decision_source="manager_agent",
                    summary=str(decision["reason"]),
                )
            )
            decision_index += 1
        merged.append(event)
    return merged


def maf_group_chat_event_shape(events: list[object]) -> list[dict[str, object]]:
    shape: list[dict[str, object]] = []
    for event in events:
        data = getattr(event, "data", None)
        text = getattr(data, "text", None) if data is not None else None
        shape.append(
            {
                "type": getattr(event, "type", None),
                "executor_id": getattr(event, "executor_id", None),
                "data_type": type(data).__name__ if data is not None else None,
                "participant_name": getattr(data, "participant_name", None),
                "round_index": getattr(data, "round_index", None),
                "text": text,
            }
        )
    return shape


def assert_group_chat_records_are_safe(
    test_case: unittest.TestCase,
    records: list[object],
) -> None:
    for record in records:
        test_case.assertIsNone(record.runtime_session_id)
        test_case.assertIsNone(record.runtime_turn_id)
        test_case.assertIsNone(record.runtime_event_id)
        test_case.assertLessEqual(
            set(record.payload),
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
        encoded = json.dumps(record.payload, sort_keys=True, default=str).lower()
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
        for value in record.payload.values():
            test_case.assertIsInstance(value, str)


def assert_run_participants_do_not_inherit_runtime_or_provider(
    test_case: unittest.TestCase,
    store: object,
    run_id: str,
) -> None:
    participants = store.list_participants(run_id, workspace_id="default")
    for participant in participants:
        test_case.assertIsNone(participant.provider_id)
        test_case.assertIsNone(participant.runtime_session_id)
        test_case.assertEqual(participant.authority_grant_ids, [])


def _assert_idle_result(result: object) -> None:
    final_state = result.get_final_state()
    if getattr(final_state, "value", None) != "IDLE":
        raise AssertionError(f"Unexpected MAF workflow final state: {final_state}")
