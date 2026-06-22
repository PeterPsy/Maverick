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


NOW = datetime(2026, 6, 22, 9, 0, tzinfo=UTC)


def _magentic_run() -> InterAgentRunRecord:
    return InterAgentRunRecord(
        run_id="run-maf-magentic",
        workspace_id="default",
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="magentic_like",
        status="running",
        created_by_user_id="user-1",
        orchestrator_participant_id="manager",
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


class MafMagenticAdapterTest(unittest.TestCase):
    def test_magentic_events_map_plan_progress_participant_and_terminal_output(self) -> None:
        context = AdapterEventMappingContext(
            run=_magentic_run(),
            visibility_plane="detail",
            sequence_start=200,
            event_id_prefix="iaevt-magentic",
            created_at=NOW,
        )
        events = [
            _magentic_orchestrator_event(
                "plan_created",
                MessageLike("Plan: ask the researcher, then synthesize."),
                raw_progress_ledger={"messages": ["must not persist"], "secret": "unused"},
            ),
            _magentic_orchestrator_event(
                "progress_ledger_updated",
                _progress_ledger(
                    request_satisfied=False,
                    in_loop=False,
                    progress_made=True,
                    next_speaker="researcher",
                    instruction="Collect one fact that is safe to summarize.",
                ),
            ),
            SimpleNamespace(
                type="group_chat",
                data=GroupChatRequestSentEvent(round_index=1, participant_name="researcher"),
            ),
            SimpleNamespace(
                type="intermediate",
                executor_id="researcher",
                data=SimpleNamespace(text="research fact", messages=["raw transcript must not persist"]),
            ),
            SimpleNamespace(
                type="group_chat",
                data=GroupChatResponseReceivedEvent(round_index=1, participant_name="researcher"),
            ),
            _magentic_orchestrator_event(
                "progress_ledger_updated",
                _progress_ledger(
                    request_satisfied=True,
                    in_loop=False,
                    progress_made=True,
                    next_speaker="researcher",
                    instruction="Finish.",
                ),
            ),
            SimpleNamespace(
                type="output",
                executor_id="magentic_orchestrator",
                data=SimpleNamespace(text="Final answer from manager."),
            ),
        ]

        records = map_maf_events_to_inter_agent_records(context, events)
        records_retry = map_maf_events_to_inter_agent_records(context, events)

        self.assertEqual(
            [record.event_type for record in records],
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
        self.assertEqual([record.sequence for record in records], list(range(201, 209)))
        self.assertEqual(
            [(record.event_id, record.idempotency_key, record.payload) for record in records],
            [(record.event_id, record.idempotency_key, record.payload) for record in records_retry],
        )
        self.assertEqual(records[0].participant_id, "manager")
        self.assertEqual(records[0].payload["observation_kind"], "plan_summary")
        self.assertEqual(records[0].payload["summary"], "Plan: ask the researcher, then synthesize.")
        self.assertEqual(records[1].participant_id, "manager")
        self.assertEqual(records[1].payload["adapter_event_type"], "magentic_progress_updated")
        self.assertEqual(records[1].payload["progress_status"], "moving")
        self.assertEqual(records[1].payload["request_status"], "open")
        self.assertEqual(records[1].payload["selected_participant_id"], "researcher")
        self.assertNotIn("Collect one fact", json.dumps(records[1].payload, sort_keys=True))
        self.assertEqual(records[2].participant_id, "researcher")
        self.assertEqual(records[2].payload["observation_kind"], "participant_dispatch")
        self.assertEqual(records[3].participant_id, "researcher")
        self.assertEqual(records[3].payload["summary"], "research fact")
        self.assertEqual(records[4].event_type, "inter_agent.task.completed")
        self.assertEqual(records[5].payload["request_status"], "satisfied")
        self.assertEqual(records[-2].payload["summary"], "Final answer from manager.")
        self.assertEqual(records[-1].participant_id, "manager")
        self.assertEqual(records[-1].payload["terminal_status"], "completed")
        for record in records:
            self.assertIsNone(record.runtime_session_id)
            self.assertIsNone(record.runtime_turn_id)
            self.assertIsNone(record.runtime_event_id)
            _assert_magentic_payload_is_safe(self, record.payload)

    def test_magentic_stall_and_max_rounds_map_to_safe_observations_and_failure(self) -> None:
        context = AdapterEventMappingContext(
            run=_magentic_run(),
            visibility_plane="detail",
            event_id_prefix="iaevt-magentic-stall",
            created_at=NOW,
        )

        records = map_maf_events_to_inter_agent_records(
            context,
            [
                _magentic_orchestrator_event("plan_created", MessageLike("Initial plan.")),
                _magentic_orchestrator_event(
                    "progress_ledger_updated",
                    _progress_ledger(
                        request_satisfied=False,
                        in_loop=True,
                        progress_made=False,
                        next_speaker="researcher",
                        instruction="Try again.",
                    ),
                ),
                _magentic_orchestrator_event("replanned", MessageLike("Replan after stall.")),
                SimpleNamespace(
                    type="output",
                    executor_id="magentic_orchestrator",
                    data=SimpleNamespace(text="Workflow terminated due to reaching maximum round count."),
                ),
            ],
        )

        self.assertEqual(
            [record.event_type for record in records],
            [
                "inter_agent.plan.summary_created",
                "inter_agent.summary.updated",
                "inter_agent.plan.summary_created",
                "inter_agent.budget.exceeded",
                "inter_agent.run.failed",
            ],
        )
        self.assertEqual(records[1].payload["progress_status"], "stalled")
        self.assertEqual(records[1].payload["loop_status"], "loop_detected")
        self.assertEqual(records[1].payload["stall_detected"], "true")
        self.assertEqual(records[2].payload["observation_kind"], "replan_summary")
        self.assertEqual(records[3].payload["budget_limit"], "max_rounds")
        self.assertEqual(records[4].payload["terminal_status"], "failed")
        self.assertEqual([record.participant_id for record in records], ["manager"] * 5)
        for record in records:
            _assert_magentic_payload_is_safe(self, record.payload)

    def test_magentic_split_terminal_output_replays_idempotently_without_raw_payload(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        context = AdapterEventMappingContext(
            run=_magentic_run(),
            visibility_plane="detail",
            event_id_prefix="iaevt-magentic-terminal",
            created_at=NOW,
        )

        records = map_maf_events_to_inter_agent_records(
            context,
            [
                SimpleNamespace(
                    type="output",
                    idempotency_key="maf-magentic-terminal-output-1",
                    executor_id="magentic_orchestrator",
                    data=SimpleNamespace(text="Final answer from manager."),
                    raw_payload={"progress_ledger": {"chain_of_thought": "must not persist"}},
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
                "run-maf-magentic:maf:output:inter_agent.summary.updated:maf-magentic-terminal-output-1",
                "run-maf-magentic:maf:output:inter_agent.run.completed:maf-magentic-terminal-output-1",
            ],
        )
        self.assertEqual(len({record.idempotency_key for record in records}), 2)
        retention = _retention()
        stored = [store.append_event(record, retention_policy=retention) for record in records]
        stored_retry = [store.append_event(record, retention_policy=retention) for record in records]
        self.assertEqual([event.event_id for event in stored], [event.event_id for event in stored_retry])
        self.assertEqual([event.sequence for event in stored], [event.sequence for event in stored_retry])
        replay = store.list_event_page(
            "run-maf-magentic",
            workspace_id="default",
            visibility_plane="debug",
            event_types={"inter_agent.summary.updated", "inter_agent.run.completed"},
            limit=10,
        ).events
        self.assertEqual([event.event_type for event in replay], [event.event_type for event in stored])
        for record in replay:
            _assert_magentic_payload_is_safe(self, record.payload)


class MessageLike:
    def __init__(self, text: str) -> None:
        self.text = text
        self.raw_representation = {"provider": "must not persist"}


class LedgerItem:
    def __init__(self, *, reason: str, answer: str | bool) -> None:
        self.reason = reason
        self.answer = answer


class ProgressLedger:
    def __init__(
        self,
        *,
        request_satisfied: bool,
        in_loop: bool,
        progress_made: bool,
        next_speaker: str,
        instruction: str,
    ) -> None:
        self.is_request_satisfied = LedgerItem(reason="raw satisfaction reason", answer=request_satisfied)
        self.is_in_loop = LedgerItem(reason="raw loop reason", answer=in_loop)
        self.is_progress_being_made = LedgerItem(reason="raw progress reason", answer=progress_made)
        self.next_speaker = LedgerItem(reason="raw speaker reason", answer=next_speaker)
        self.instruction_or_question = LedgerItem(reason="raw instruction reason", answer=instruction)


class GroupChatRequestSentEvent:
    def __init__(self, *, round_index: int, participant_name: str) -> None:
        self.round_index = round_index
        self.participant_name = participant_name


class GroupChatResponseReceivedEvent:
    def __init__(self, *, round_index: int, participant_name: str) -> None:
        self.round_index = round_index
        self.participant_name = participant_name


def _progress_ledger(
    *,
    request_satisfied: bool,
    in_loop: bool,
    progress_made: bool,
    next_speaker: str,
    instruction: str,
) -> ProgressLedger:
    return ProgressLedger(
        request_satisfied=request_satisfied,
        in_loop=in_loop,
        progress_made=progress_made,
        next_speaker=next_speaker,
        instruction=instruction,
    )


def _magentic_orchestrator_event(event_type: str, content: object, **extras: object) -> SimpleNamespace:
    return SimpleNamespace(
        type="magentic_orchestrator",
        executor_id="magentic_orchestrator",
        data=SimpleNamespace(event_type=event_type, content=content),
        **extras,
    )


def _assert_magentic_payload_is_safe(
    test_case: unittest.TestCase,
    payload: dict[str, object],
) -> None:
    test_case.assertLessEqual(
        set(payload),
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
        "checkpoint",
        "task_write",
        "magentic_orchestrator",
    ):
        test_case.assertNotIn(forbidden, encoded)
    for value in payload.values():
        test_case.assertIsInstance(value, str)


if __name__ == "__main__":
    unittest.main()
