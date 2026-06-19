from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import multiprocessing
from pathlib import Path
from unittest.mock import patch
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.inter_agent.errors import InterAgentIdempotencyConflictError
from core.inter_agent.models import (
    AgentParticipantSnapshot,
    ApprovalRequestRecord,
    BudgetPolicySpec,
    InterAgentRunSpec,
    ParticipantSpec,
)
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import _stable_fingerprint, build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


def _run_spec(
    *,
    idempotency_key: str | None = None,
    researcher_label: str = "Researcher",
    researcher_snapshot: AgentParticipantSnapshot | None = None,
) -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode="manager_tools",
        created_by_user_id="user-1",
        participants=[
            ParticipantSpec(
                participant_id="orchestrator",
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label="Orchestrator",
            ),
            ParticipantSpec(
                participant_id="researcher",
                kind="agent",
                execution_mode="child_runtime_session",
                label=researcher_label,
                agent_type_id="research-agent",
                agent_snapshot=researcher_snapshot,
            ),
        ],
        budget=BudgetPolicySpec(
            max_participants=3,
            max_concurrent_participants=2,
            max_total_turns=6,
            max_turns_per_participant=3,
            max_tool_calls=2,
            max_estimated_cost=Decimal("1.00"),
        ),
        idempotency_key=idempotency_key,
    )


def _create_run_worker(start_path: str, idempotency_key: str, queue) -> None:
    store = build_inter_agent_document_store(start_path=Path(start_path))
    service = InterAgentService(store)
    try:
        run = service.create_run(
            _run_spec(idempotency_key=idempotency_key),
            now=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        )
        queue.put(("ok", run.run_id))
    except Exception as exc:  # pragma: no cover - surfaced through the queue assertion.
        queue.put(("error", type(exc).__name__, str(exc)))


def _legacy_budget_reservation_document(reservation_id: str, *, turns: int, now: datetime) -> dict[str, object]:
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


class InterAgentServiceTest(unittest.TestCase):
    def run_spec(self, *, idempotency_key: str | None = None) -> InterAgentRunSpec:
        return _run_spec(idempotency_key=idempotency_key)

    def test_create_run_materializes_records_and_no_runtime_sessions(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

        run = service.create_run(self.run_spec(idempotency_key="create-run-1"), now=now)
        same_run = service.create_run(self.run_spec(idempotency_key="create-run-1"), now=now + timedelta(minutes=1))
        participants = store.list_participants(run.run_id, workspace_id="default")
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=20).events
        sessions_root = repo_root / "workspaces" / "default" / "runtime" / "sessions"

        self.assertEqual(same_run.run_id, run.run_id)
        self.assertEqual(run.orchestrator_participant_id, "orchestrator")
        self.assertEqual([participant.participant_id for participant in participants], ["orchestrator", "researcher"])
        self.assertTrue(all(participant.runtime_session_id is None for participant in participants))
        self.assertEqual(participants[0].thread_visibility, "user")
        self.assertEqual(participants[1].thread_visibility, "hidden")
        self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
        self.assertEqual(len([event for event in events if event.event_type == "inter_agent.run.started"]), 1)
        self.assertFalse(sessions_root.exists())

    def test_participant_ids_are_scoped_to_run(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)

        first = service.create_run(self.run_spec(idempotency_key="run-a"))
        second = service.create_run(self.run_spec(idempotency_key="run-b"))

        self.assertEqual(
            [participant.participant_id for participant in store.list_participants(first.run_id, workspace_id="default")],
            ["orchestrator", "researcher"],
        )
        self.assertEqual(
            [participant.participant_id for participant in store.list_participants(second.run_id, workspace_id="default")],
            ["orchestrator", "researcher"],
        )

    def test_create_run_rejects_idempotency_key_with_different_spec(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)

        service.create_run(_run_spec(idempotency_key="same-key"))

        with self.assertRaises(InterAgentIdempotencyConflictError):
            service.create_run(_run_spec(idempotency_key="same-key", researcher_label="Different Researcher"))

    def test_concurrent_create_run_idempotency_materializes_once(self) -> None:
        repo_root = make_temp_repo_root(self)
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [
            context.Process(target=_create_run_worker, args=(str(repo_root), "concurrent-run", queue))
            for _ in range(8)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
        results = [queue.get(timeout=1) for _ in processes]
        store = build_inter_agent_document_store(start_path=repo_root)
        runs = store.list_runs("default")

        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertTrue(all(result[0] == "ok" for result in results), results)
        self.assertEqual(len({result[1] for result in results}), 1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(store.list_participants(runs[0].run_id, workspace_id="default")), 2)

    def test_create_run_retry_repairs_partial_bundle_without_visible_run(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        original_save_run = store.save_run

        def fail_save_run(record):
            raise RuntimeError("injected save_run failure")

        store.save_run = fail_save_run  # type: ignore[method-assign]
        try:
            with self.assertRaisesRegex(RuntimeError, "injected save_run failure"):
                service.create_run(_run_spec(idempotency_key="partial-create"))
        finally:
            store.save_run = original_save_run  # type: ignore[method-assign]

        self.assertEqual(store.list_runs("default"), [])

        run = service.create_run(_run_spec(idempotency_key="partial-create"))
        events_root = repo_root / "workspaces" / "default" / "runtime" / "inter_agent" / "runs"
        run_dirs = sorted(path.name for path in events_root.iterdir() if path.is_dir())
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=20).events

        self.assertEqual(run_dirs, [run.run_id])
        self.assertEqual(
            [participant.participant_id for participant in store.list_participants(run.run_id, workspace_id="default")],
            ["orchestrator", "researcher"],
        )
        self.assertEqual([event.sequence for event in events], [1, 2, 3, 4])

    def test_create_run_persists_participant_sequence_from_spec_order(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        spec = replace(
            _run_spec(idempotency_key="sequence-order"),
            participants=[
                ParticipantSpec(
                    participant_id="orchestrator",
                    kind="orchestrator",
                    execution_mode="root_orchestrator",
                    label="Orchestrator",
                ),
                ParticipantSpec(
                    participant_id="z_first",
                    kind="agent",
                    execution_mode="child_runtime_session",
                    label="First",
                    agent_type_id="first-agent",
                ),
                ParticipantSpec(
                    participant_id="a_second",
                    kind="agent",
                    execution_mode="child_runtime_session",
                    label="Second",
                    agent_type_id="second-agent",
                ),
            ],
        )

        run = service.create_run(spec, now=datetime(2026, 6, 16, 12, 0, tzinfo=UTC))
        participants = store.list_participants(run.run_id, workspace_id="default")

        self.assertEqual([participant.participant_id for participant in participants], ["orchestrator", "z_first", "a_second"])
        self.assertEqual([participant.sequence_index for participant in participants], [0, 1, 2])

    def test_create_run_retry_repairs_missing_records_without_resetting_ledger(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(_run_spec(idempotency_key="repair-existing"))
        service.reserve_budget(
            run,
            reservation_id="spawn-researcher",
            participant_id="researcher",
            participant_slots=1,
            running_participants=1,
            turns=1,
            estimated_cost=Decimal("0.25"),
        )
        store.collections.participants.delete_one(
            {"workspace_id": "default", "run_id": run.run_id, "participant_id": "researcher"}
        )

        same_run = service.create_run(_run_spec(idempotency_key="repair-existing"))
        ledger = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        participants = store.list_participants(run.run_id, workspace_id="default")

        self.assertEqual(same_run.run_id, run.run_id)
        self.assertEqual([participant.participant_id for participant in participants], ["orchestrator", "researcher"])
        self.assertEqual(ledger.reserved_participants, 1)
        self.assertEqual(ledger.turns_used, 1)
        self.assertEqual(ledger.estimated_cost_used, Decimal("0.25"))

    def test_agent_snapshot_is_copied_into_participant_record(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        snapshot = AgentParticipantSnapshot(
            agent_type_id="research-agent",
            label="Researcher",
            system_prompt="Research from the supplied sources only.",
            skill_ids=["storage", "memory"],
            skill_catalog_app_id="skills",
            provider_id="codex",
            revision_id="r1",
        )

        run = service.create_run(_run_spec(idempotency_key="snapshot-run", researcher_snapshot=snapshot))
        researcher = store.get_participant("researcher", workspace_id="default", run_id=run.run_id)

        self.assertEqual(researcher.agent_snapshot_digest, snapshot.digest())
        self.assertIsNotNone(researcher.agent_snapshot)
        self.assertEqual(researcher.agent_snapshot["system_prompt"], "Research from the supplied sources only.")
        self.assertEqual(researcher.agent_snapshot["digest"], snapshot.digest())

    def test_budget_service_records_idempotent_budget_events(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        run = service.create_run(self.run_spec(), now=now)

        first = service.reserve_budget(
            run,
            reservation_id="spawn-researcher",
            participant_slots=1,
            running_participants=1,
            estimated_cost=Decimal("0.25"),
            now=now,
        )
        second = service.reserve_budget(
            run,
            reservation_id="spawn-researcher",
            participant_slots=1,
            running_participants=1,
            estimated_cost=Decimal("0.25"),
            now=now,
        )
        released = service.release_budget(run, reservation_id="spawn-researcher", now=now)
        released_again = service.release_budget(run, reservation_id="spawn-researcher", now=now)
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=20).events

        self.assertEqual(first.reserved_participants, 1)
        self.assertEqual(second.reserved_participants, 1)
        self.assertEqual(released.reserved_participants, 0)
        self.assertEqual(released_again.reserved_participants, 0)
        self.assertEqual(len([event for event in events if event.event_type == "inter_agent.budget.reserved"]), 1)
        self.assertEqual(len([event for event in events if event.event_type == "inter_agent.budget.released"]), 1)

    def test_budget_service_legacy_reserved_event_retry_allows_participant_id(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        run = service.create_run(self.run_spec(), now=now)
        ledger = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        store.save_budget_ledger(
            replace(
                ledger,
                turns_used=1,
                operation_reservations={
                    "turn-legacy": _legacy_budget_reservation_document(
                        "turn-legacy",
                        turns=1,
                        now=now,
                    ),
                },
            )
        )
        service.record_event(
            run,
            event_type="inter_agent.budget.reserved",
            visibility_plane="detail",
            idempotency_key=f"{run.run_id}:budget.reserved:turn-legacy",
            correlation_id="turn-legacy",
            payload={
                "reservation_id": "turn-legacy",
                "participant_slots": 0,
                "running_participants": 0,
                "turns": 1,
                "tool_calls": 0,
                "handoffs": 0,
                "estimated_tokens": 0,
                "estimated_cost": "0",
            },
            now=now,
        )

        retry = service.reserve_budget(
            run,
            reservation_id="turn-legacy",
            participant_id="researcher",
            turns=1,
            now=now,
        )
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=20).events

        self.assertEqual(retry.turns_used, 1)
        self.assertEqual(len([event for event in events if event.event_type == "inter_agent.budget.reserved"]), 1)

    def test_pending_approval_timeout_fails_closed(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        run = service.create_run(self.run_spec(), now=now)
        approval = ApprovalRequestRecord(
            approval_id="approval-1",
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            requested_by_participant_id="orchestrator",
            operation_kind="file.write",
            resource_refs=[{"app_id": "storage", "entity_type": "file", "entity_id": "file-1"}],
            summary="Write a generated file.",
            risk_level="medium",
            status="pending",
            eligible_approver_user_ids=["user-1"],
            eligible_approver_roles=[],
            expires_at=now - timedelta(seconds=1),
        )
        store.save_approval(approval)

        expired = service.expire_pending_approvals(run, now=now)
        stored = store.get_approval("approval-1", workspace_id="default")

        self.assertEqual([item.approval_id for item in expired], ["approval-1"])
        self.assertEqual(stored.status, "expired")
        self.assertEqual(stored.resolution_reason, "approval_timeout")

    def test_resolve_pending_approval_records_summary_event(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        run = service.create_run(self.run_spec(), now=now)
        store.save_approval(
            ApprovalRequestRecord(
                approval_id="approval-resolve-1",
                workspace_id="default",
                run_id=run.run_id,
                participant_id="researcher",
                requested_by_participant_id="orchestrator",
                operation_kind="storage.write",
                resource_refs=[],
                summary="Write generated output.",
                risk_level="medium",
                status="pending",
                eligible_approver_user_ids=["user-1"],
                eligible_approver_roles=[],
                expires_at=now + timedelta(minutes=5),
            )
        )

        resolved = service.resolve_approval(
            workspace_id="default",
            approval_id="approval-resolve-1",
            approved=False,
            resolved_by_user_id="user-1",
            resolution_reason="needs-review",
            now=now,
        )
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="summary").events

        self.assertEqual(resolved.status, "rejected")
        self.assertEqual(resolved.resolution_reason, "needs-review")
        self.assertEqual(resolved.resolved_by_user_id, "user-1")
        self.assertIn("inter_agent.approval.resolved", [event.event_type for event in events])

    def test_platform_state_exposes_inter_agent_store_separate_from_runtime_store(self) -> None:
        repo_root = make_temp_repo_root(self)
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(
                start_path=repo_root,
                install_builtin_apps=False,
                register_builtin_provider_definitions=False,
            )
        service = InterAgentService(state.inter_agent_store)
        run = service.create_run(self.run_spec(idempotency_key="platform-state-run"))
        events_path = (
            repo_root
            / "workspaces"
            / "default"
            / "runtime"
            / "inter_agent"
            / "runs"
            / run.run_id
            / "events.json"
        )

        self.assertIsNot(state.inter_agent_store, state.runtime_store)
        self.assertTrue(events_path.is_file())


if __name__ == "__main__":
    unittest.main()
