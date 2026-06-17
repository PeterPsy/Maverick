from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import multiprocessing
import unittest
from pathlib import Path

from core.inter_agent.errors import (
    InterAgentBudgetExceededError,
    InterAgentEventNotFoundError,
    InterAgentIdempotencyConflictError,
)
from core.inter_agent.events import EventRetentionPolicyRecord, InterAgentEventRecord
from core.inter_agent.models import BudgetPolicySpec, budget_policy_from_spec, empty_budget_ledger
from core.inter_agent.store import _stable_fingerprint, build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


def _event(
    index: int,
    *,
    workspace_id: str = "default",
    run_id: str = "run-1",
    visibility_plane: str = "summary",
    idempotency_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> InterAgentEventRecord:
    return InterAgentEventRecord(
        event_id=f"event-{index}",
        workspace_id=workspace_id,
        run_id=run_id,
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        participant_id="orchestrator",
        runtime_session_id=None,
        runtime_turn_id=None,
        runtime_event_id=None,
        event_type="inter_agent.summary.updated",
        visibility_plane=visibility_plane,  # type: ignore[arg-type]
        sequence=0,
        correlation_id=f"corr-{index}",
        idempotency_key=idempotency_key,
        payload=dict(payload or {"index": index}),
        created_at=datetime(2026, 6, 16, 12, index % 60, tzinfo=UTC),
    )


def _retention(
    *,
    workspace_id: str = "default",
    summary_max_events: int = 100,
    detail_max_events: int = 100,
    debug_max_events: int = 100,
) -> EventRetentionPolicyRecord:
    return EventRetentionPolicyRecord(
        retention_policy_id="retention-1",
        workspace_id=workspace_id,
        summary_max_events=summary_max_events,
        detail_max_events=detail_max_events,
        debug_max_events=debug_max_events,
        created_at=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
    )


def _append_event_worker(start_path: str, start_index: int, count: int) -> None:
    store = build_inter_agent_document_store(start_path=Path(start_path))
    retention = _retention()
    for index in range(start_index, start_index + count):
        store.append_event(_event(index, idempotency_key=f"worker-{index}"), retention_policy=retention)


def _reserve_budget_worker(start_path: str, reservation_index: int, queue) -> None:
    store = build_inter_agent_document_store(start_path=Path(start_path))
    try:
        store.reserve_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            budget_policy_id="policy-1",
            reservation_id=f"reservation-{reservation_index}",
            participant_slots=1,
            running_participants=1,
            now=datetime(2026, 6, 16, 12, reservation_index % 60, tzinfo=UTC),
        )
        queue.put("reserved")
    except InterAgentBudgetExceededError:
        queue.put("exceeded")


def _legacy_turn_reservation_document(reservation_id: str, *, turns: int, now: datetime) -> dict[str, object]:
    document: dict[str, object] = {
        "reservation_id": reservation_id,
        "participant_slots": 0,
        "running_participants": 0,
        "turns": turns,
        "tool_calls": 0,
        "handoffs": 0,
        "estimated_tokens": 0,
        "estimated_cost": Decimal("0"),
        "status": "reserved",
        "created_at": now,
        "released_at": None,
    }
    fingerprint_document = dict(document)
    for key in ("status", "created_at", "released_at", "fingerprint"):
        fingerprint_document.pop(key, None)
    document["fingerprint"] = _stable_fingerprint(fingerprint_document)
    return document


class InterAgentStoreTest(unittest.TestCase):
    def test_event_append_assigns_ordered_sequence_and_is_idempotent(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        retention = _retention()

        first = store.append_event(_event(1, idempotency_key="same"), retention_policy=retention)
        second = store.append_event(_event(1, idempotency_key="same"), retention_policy=retention)
        third = store.append_event(_event(3), retention_policy=retention)
        page = store.list_event_page("run-1", workspace_id="default", visibility_plane="debug")

        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(first.sequence, 1)
        self.assertEqual(third.sequence, 2)
        self.assertEqual([event.event_id for event in page.events], ["event-1", "event-3"])

    def test_event_idempotency_rejects_same_key_with_different_payload(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        retention = _retention()

        store.append_event(_event(1, idempotency_key="same"), retention_policy=retention)

        with self.assertRaises(InterAgentIdempotencyConflictError):
            store.append_event(
                _event(2, idempotency_key="same", payload={"index": 999}),
                retention_policy=retention,
            )

    def test_event_paging_uses_visibility_hierarchy_and_cursors(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        retention = _retention()
        store.append_event(_event(1, visibility_plane="summary"), retention_policy=retention)
        store.append_event(_event(2, visibility_plane="detail"), retention_policy=retention)
        store.append_event(_event(3, visibility_plane="debug"), retention_policy=retention)
        store.append_event(_event(4, visibility_plane="summary"), retention_policy=retention)

        summary_page = store.list_event_page("run-1", workspace_id="default", visibility_plane="summary", limit=10)
        detail_page = store.list_event_page("run-1", workspace_id="default", visibility_plane="detail", limit=10)
        debug_page = store.list_event_page("run-1", workspace_id="default", visibility_plane="debug", limit=10)
        after_page = store.list_event_page(
            "run-1",
            workspace_id="default",
            visibility_plane="debug",
            after_event_id="event-2",
            limit=10,
        )
        before_page = store.list_event_page(
            "run-1",
            workspace_id="default",
            visibility_plane="debug",
            before_event_id="event-4",
            limit=2,
        )

        self.assertEqual([event.event_id for event in summary_page.events], ["event-1", "event-4"])
        self.assertEqual([event.event_id for event in detail_page.events], ["event-1", "event-2", "event-4"])
        self.assertEqual([event.event_id for event in debug_page.events], ["event-1", "event-2", "event-3", "event-4"])
        self.assertEqual([event.event_id for event in after_page.events], ["event-3", "event-4"])
        self.assertEqual([event.event_id for event in before_page.events], ["event-2", "event-3"])
        self.assertTrue(before_page.has_more_before)

    def test_event_paging_requires_workspace_and_rejects_missing_cursor(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        store.append_event(_event(1, workspace_id="default"), retention_policy=_retention(workspace_id="default"))
        store.append_event(_event(2, workspace_id="beta"), retention_policy=_retention(workspace_id="beta"))

        default_page = store.list_event_page("run-1", workspace_id="default", visibility_plane="debug")
        beta_page = store.list_event_page("run-1", workspace_id="beta", visibility_plane="debug")

        self.assertEqual([event.event_id for event in default_page.events], ["event-1"])
        self.assertEqual([event.event_id for event in beta_page.events], ["event-2"])
        with self.assertRaises(InterAgentEventNotFoundError):
            store.list_event_page(
                "run-1",
                workspace_id="default",
                visibility_plane="debug",
                after_event_id="missing",
            )

    def test_retention_is_applied_per_visibility_plane(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        retention = _retention(summary_max_events=2, detail_max_events=2, debug_max_events=1)
        store.append_event(_event(1, visibility_plane="summary"), retention_policy=retention)
        store.append_event(_event(2, visibility_plane="summary"), retention_policy=retention)
        store.append_event(_event(3, visibility_plane="summary"), retention_policy=retention)
        store.append_event(_event(4, visibility_plane="debug"), retention_policy=retention)
        store.append_event(_event(5, visibility_plane="debug"), retention_policy=retention)
        page = store.list_event_page("run-1", workspace_id="default", visibility_plane="debug", limit=10)

        self.assertEqual([event.event_id for event in page.events], ["event-2", "event-3", "event-5"])

    def test_concurrent_event_append_keeps_unique_sequences(self) -> None:
        repo_root = make_temp_repo_root(self)
        processes = [
            multiprocessing.Process(target=_append_event_worker, args=(str(repo_root), offset, 10))
            for offset in (0, 10, 20, 30)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
        store = build_inter_agent_document_store(start_path=repo_root)
        page = store.list_event_page("run-1", workspace_id="default", visibility_plane="debug", limit=100)

        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual(len(page.events), 40)
        self.assertEqual(sorted(event.sequence for event in page.events), list(range(1, 41)))

    def test_budget_reservation_and_release_are_idempotent(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        policy = budget_policy_from_spec(
            BudgetPolicySpec(
                max_participants=2,
                max_concurrent_participants=2,
                max_total_turns=4,
                max_turns_per_participant=2,
                max_tool_calls=2,
                max_estimated_cost=Decimal("2.00"),
            ),
            budget_policy_id="policy-1",
            workspace_id="default",
            created_at=now,
        )
        store.save_budget_policy(policy)
        store.save_budget_ledger(
            empty_budget_ledger(
                budget_ledger_id="ledger-1",
                workspace_id="default",
                run_id="run-1",
                updated_at=now,
            )
        )

        first = store.reserve_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            budget_policy_id="policy-1",
            reservation_id="reservation-1",
            participant_id="researcher",
            participant_slots=1,
            running_participants=1,
            turns=1,
            tool_calls=1,
            estimated_cost=Decimal("0.50"),
            now=now,
        )
        second = store.reserve_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            budget_policy_id="policy-1",
            reservation_id="reservation-1",
            participant_id="researcher",
            participant_slots=1,
            running_participants=1,
            turns=1,
            tool_calls=1,
            estimated_cost=Decimal("0.50"),
            now=now,
        )
        with self.assertRaises(InterAgentIdempotencyConflictError):
            store.reserve_budget(
                workspace_id="default",
                budget_ledger_id="ledger-1",
                budget_policy_id="policy-1",
                reservation_id="reservation-1",
                participant_id="researcher",
                participant_slots=1,
                running_participants=1,
                turns=2,
                tool_calls=1,
                estimated_cost=Decimal("0.50"),
                now=now,
            )
        released = store.release_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            reservation_id="reservation-1",
            now=now,
        )
        released_again = store.release_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            reservation_id="reservation-1",
            now=now,
        )

        self.assertEqual(first.reserved_participants, 1)
        self.assertEqual(second.reserved_participants, 1)
        self.assertEqual(second.turns_used, 1)
        self.assertEqual(released.reserved_participants, 0)
        self.assertEqual(released.running_participants, 0)
        self.assertEqual(released.turns_used, 0)
        self.assertEqual(released.tool_calls_used, 0)
        self.assertEqual(released.estimated_cost_used, Decimal("0"))
        self.assertEqual(released_again.reserved_participants, 0)

    def test_budget_reservation_enforces_max_turns_per_participant(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        store.save_budget_policy(
            budget_policy_from_spec(
                BudgetPolicySpec(
                    max_participants=3,
                    max_concurrent_participants=2,
                    max_total_turns=4,
                    max_turns_per_participant=1,
                ),
                budget_policy_id="policy-1",
                workspace_id="default",
                created_at=now,
            )
        )
        store.save_budget_ledger(
            empty_budget_ledger(
                budget_ledger_id="ledger-1",
                workspace_id="default",
                run_id="run-1",
                updated_at=now,
            )
        )

        store.reserve_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            budget_policy_id="policy-1",
            reservation_id="turn-1",
            participant_id="researcher",
            turns=1,
            now=now,
        )
        with self.assertRaisesRegex(InterAgentBudgetExceededError, "max_turns_per_participant"):
            store.reserve_budget(
                workspace_id="default",
                budget_ledger_id="ledger-1",
                budget_policy_id="policy-1",
                reservation_id="turn-2",
                participant_id="researcher",
                turns=1,
                now=now,
            )
        reviewer = store.reserve_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            budget_policy_id="policy-1",
            reservation_id="turn-3",
            participant_id="reviewer",
            turns=1,
            now=now,
        )

        self.assertEqual(reviewer.turns_used, 2)

    def test_legacy_turn_reservation_retry_allows_participant_id_and_counts_limit(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        store.save_budget_policy(
            budget_policy_from_spec(
                BudgetPolicySpec(
                    max_participants=3,
                    max_concurrent_participants=2,
                    max_total_turns=4,
                    max_turns_per_participant=1,
                ),
                budget_policy_id="policy-1",
                workspace_id="default",
                created_at=now,
            )
        )
        ledger = empty_budget_ledger(
            budget_ledger_id="ledger-1",
            workspace_id="default",
            run_id="run-1",
            updated_at=now,
        )
        store.save_budget_ledger(
            replace(
                ledger,
                turns_used=1,
                operation_reservations={
                    "turn-legacy": _legacy_turn_reservation_document(
                        "turn-legacy",
                        turns=1,
                        now=now,
                    ),
                },
            )
        )

        retry = store.reserve_budget(
            workspace_id="default",
            budget_ledger_id="ledger-1",
            budget_policy_id="policy-1",
            reservation_id="turn-legacy",
            participant_id="researcher",
            turns=1,
            now=now,
        )
        with self.assertRaisesRegex(InterAgentBudgetExceededError, "max_turns_per_participant"):
            store.reserve_budget(
                workspace_id="default",
                budget_ledger_id="ledger-1",
                budget_policy_id="policy-1",
                reservation_id="turn-new",
                participant_id="researcher",
                turns=1,
                now=now,
            )
        with self.assertRaises(InterAgentIdempotencyConflictError):
            store.reserve_budget(
                workspace_id="default",
                budget_ledger_id="ledger-1",
                budget_policy_id="policy-1",
                reservation_id="turn-legacy",
                participant_id="researcher",
                turns=2,
                now=now,
            )

        self.assertEqual(retry.turns_used, 1)

    def test_concurrent_budget_reservations_are_atomically_limited(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        store.save_budget_policy(
            budget_policy_from_spec(
                BudgetPolicySpec(
                    max_participants=4,
                    max_concurrent_participants=4,
                    max_total_turns=10,
                    max_turns_per_participant=2,
                ),
                budget_policy_id="policy-1",
                workspace_id="default",
                created_at=now,
            )
        )
        store.save_budget_ledger(
            empty_budget_ledger(
                budget_ledger_id="ledger-1",
                workspace_id="default",
                run_id="run-1",
                updated_at=now,
            )
        )
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [
            context.Process(target=_reserve_budget_worker, args=(str(repo_root), index, queue))
            for index in range(8)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
        results = [queue.get(timeout=1) for _ in processes]
        ledger = store.get_budget_ledger("ledger-1", workspace_id="default")

        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual(results.count("reserved"), 4)
        self.assertEqual(results.count("exceeded"), 4)
        self.assertEqual(ledger.reserved_participants, 4)
        self.assertEqual(ledger.running_participants, 4)


if __name__ == "__main__":
    unittest.main()
