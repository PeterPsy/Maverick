from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest

from core.inter_agent.adapters.maf import MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK
from core.inter_agent.models import BudgetPolicySpec, InterAgentRunSpec, ParticipantSpec


NOW = datetime(2026, 6, 22, 9, 30, tzinfo=UTC)
MAGENTIC_EVENT_TYPES = {
    "inter_agent.plan.summary_created",
    "inter_agent.task.started",
    "inter_agent.message.sent",
    "inter_agent.task.completed",
    "inter_agent.summary.updated",
    "inter_agent.budget.exceeded",
    "inter_agent.run.completed",
    "inter_agent.run.failed",
    "inter_agent.run.cancelled",
}


def magentic_run_spec(*, max_rounds: int = 3) -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id=f"thread-maf-magentic-{max_rounds}",
        root_runtime_session_id="root-runtime-session",
        source_app_id="chat",
        mode="magentic_like",
        created_by_user_id="user-1",
        participants=[
            ParticipantSpec(
                participant_id="manager",
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label="Manager",
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
        visibility_level="detail",
        idempotency_key=f"maf-magentic-source-backed-{max_rounds}",
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
            from agent_framework_orchestrations import MagenticBuilder  # type: ignore[import-not-found]
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
        MagenticBuilder=MagenticBuilder,
        Message=Message,
    )


async def run_controlled_maf_magentic_manager(
    maf: SimpleNamespace,
) -> tuple[list[object], dict[str, int]]:
    manager_client = _ControlledMafChatClient(
        maf,
        "manager",
        [
            "controlled facts",
            "controlled plan",
            _progress_ledger_json(request_satisfied=False, in_loop=False, progress_made=True),
            _progress_ledger_json(request_satisfied=True, in_loop=False, progress_made=True),
            "Final answer from manager.",
        ],
    )
    researcher_client = _ControlledMafChatClient(maf, "researcher", ["research fact"])
    writer_client = _ControlledMafChatClient(maf, "writer", ["unused writer response"])
    workflow = maf.MagenticBuilder(
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
        manager_agent=maf.Agent(
            manager_client,
            name="manager",
            require_per_service_call_history_persistence=True,
        ),
        max_stall_count=1,
        max_round_count=3,
        intermediate_output_from="all",
    ).build()
    result = await workflow.run("answer with one sourced fact")
    _assert_idle_result(result)
    call_counts = {
        "manager": len(manager_client.calls),
        "researcher": len(researcher_client.calls),
        "writer": len(writer_client.calls),
    }
    if call_counts != {"manager": 5, "researcher": 1, "writer": 0}:
        raise AssertionError(f"Unexpected fake provider call counts: {call_counts!r}")
    return list(result), call_counts


async def run_controlled_maf_magentic_max_rounds(
    maf: SimpleNamespace,
) -> tuple[list[object], dict[str, int]]:
    manager_client = _ControlledMafChatClient(
        maf,
        "manager",
        [
            "controlled facts",
            "controlled plan",
            _progress_ledger_json(request_satisfied=False, in_loop=True, progress_made=False),
            "updated facts after stall",
            "replan after stall",
        ],
    )
    researcher_client = _ControlledMafChatClient(maf, "researcher", ["unused researcher response"])
    workflow = maf.MagenticBuilder(
        participants=[
            maf.Agent(
                researcher_client,
                name="researcher",
                description="find facts",
                require_per_service_call_history_persistence=True,
            )
        ],
        manager_agent=maf.Agent(
            manager_client,
            name="manager",
            require_per_service_call_history_persistence=True,
        ),
        max_stall_count=0,
        max_round_count=1,
        intermediate_output_from="all",
    ).build()
    result = await workflow.run("answer with one sourced fact")
    _assert_idle_result(result)
    call_counts = {
        "manager": len(manager_client.calls),
        "researcher": len(researcher_client.calls),
    }
    if call_counts != {"manager": 5, "researcher": 0}:
        raise AssertionError(f"Unexpected fake provider call counts: {call_counts!r}")
    return list(result), call_counts


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
                    raise AssertionError("The MAF Magentic fixture uses non-streaming fake provider responses.")
                await self._validate_options(options)
                self.calls.append((list(messages), dict(options), dict(kwargs)))
                if not self.responses:
                    raise AssertionError(f"No controlled fake response remains for {self.name}.")
                response_text = self.responses.pop(0)
                return maf.ChatResponse(
                    messages=[
                        maf.Message(
                            role="assistant",
                            contents=[response_text],
                            author_name=self.name,
                        )
                    ],
                    response_id=f"{self.name}-response-{len(self.calls)}",
                )

        return ControlledMafChatClient()


def _progress_ledger_json(
    *,
    request_satisfied: bool,
    in_loop: bool,
    progress_made: bool,
) -> str:
    return json.dumps(
        {
            "is_request_satisfied": {
                "reason": "controlled fixture reason",
                "answer": request_satisfied,
            },
            "is_in_loop": {
                "reason": "controlled fixture reason",
                "answer": in_loop,
            },
            "is_progress_being_made": {
                "reason": "controlled fixture reason",
                "answer": progress_made,
            },
            "next_speaker": {
                "reason": "controlled fixture reason",
                "answer": "researcher",
            },
            "instruction_or_question": {
                "reason": "controlled fixture reason",
                "answer": "Collect one fact.",
            },
        },
        sort_keys=True,
    )


def maf_magentic_event_shape(events: list[object]) -> list[dict[str, object]]:
    shape: list[dict[str, object]] = []
    for event in events:
        data = getattr(event, "data", None)
        content = getattr(data, "content", None)
        shape.append(
            {
                "type": getattr(event, "type", None),
                "executor_id": getattr(event, "executor_id", None),
                "data_type": type(data).__name__ if data is not None else None,
                "orchestrator_event_type": str(
                    getattr(getattr(data, "event_type", None), "value", getattr(data, "event_type", ""))
                )
                or None,
                "content_type": type(content).__name__ if content is not None else None,
                "participant_name": getattr(data, "participant_name", None),
                "round_index": getattr(data, "round_index", None),
                "text": getattr(data, "text", None),
            }
        )
    return shape


def assert_magentic_records_are_safe(
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
                "loop_status",
                "observation_kind",
                "participant_id",
                "progress_status",
                "request_status",
                "round_index",
                "selected_participant_id",
                "source_event_id",
                "stall_detected",
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
            "checkpoint",
            "task_write",
            "magentic_orchestrator",
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
