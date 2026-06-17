from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
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
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionGrantRecord, RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
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

    def test_create_run_retry_repairs_missing_records_without_resetting_ledger(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        run = service.create_run(_run_spec(idempotency_key="repair-existing"))
        service.reserve_budget(
            run,
            reservation_id="spawn-researcher",
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

    def test_spawn_child_runtime_session_uses_explicit_materialized_authority_only(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        parent_grant = RuntimeSessionGrantRecord(operation="interrupt", grantee_kind="user", grantee_id="user-parent")
        runtime_store.save_session(
            self._runtime_session(
                "root-session",
                repo_root=repo_root,
                system_prompt="parent prompt",
                skill_ids=["parent-skill"],
                owner_user_id="user-parent",
                grants=[parent_grant],
            )
        )
        runtime_store.save_state(self._runtime_state("root-session"))
        snapshot = AgentParticipantSnapshot(
            agent_type_id="research-agent",
            label="Researcher",
            system_prompt="Use only provided files.",
            skill_ids=["storage"],
            skill_catalog_app_id="skills",
        )
        run = service.create_run(_run_spec(idempotency_key="spawn-child", researcher_snapshot=snapshot), now=now)

        participant, child, created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            now=now,
        )

        self.assertTrue(created)
        self.assertEqual(participant.runtime_session_id, child.session_id)
        self.assertEqual(child.session_kind, "inter_agent_participant")
        self.assertEqual(child.thread_visibility, "hidden")
        self.assertEqual(child.creator_runtime_session_id, "root-session")
        self.assertEqual(child.system_prompt, "Use only provided files.")
        self.assertEqual(child.skill_ids, ["storage"])
        self.assertEqual(child.skill_catalog_app_id, "skills")
        self.assertIsNone(child.owner_user_id)
        self.assertEqual(child.grants, [])
        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "running")

    def test_send_runtime_message_records_inter_agent_event(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(self._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(self._runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="send-message"), now=now)
        participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            now=now,
        )
        turn = RuntimeTurnRecord(
            turn_id="turn-1",
            session_id=child.session_id,
            workspace_id="default",
            status="completed",
            input_text="hello child",
            created_at=now,
            updated_at=now,
            started_at=now,
            completed_at=now,
            failure_reason=None,
        )
        event = RuntimeEventRecord(
            event_id="runtime-event-1",
            workspace_id="default",
            session_id=child.session_id,
            plane="turn",
            event_type="runtime.turn.completed",
            turn_id=turn.turn_id,
            process_id=None,
            payload={},
            created_at=now,
        )

        with patch("core.inter_agent.service.submit_runtime_turn", return_value=(turn, [event])):
            sent_participant, sent_turn, events = service.send_runtime_message(
                type("State", (), {"runtime_store": runtime_store, "provider_store": object(), "runtime_event_bus": None})(),
                workspace_id="default",
                run_id=run.run_id,
                participant_id=participant.participant_id,
                input_text="hello child",
                now=now,
            )

        page = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=20)
        self.assertEqual(sent_participant.participant_id, "researcher")
        self.assertEqual(sent_turn.turn_id, "turn-1")
        self.assertEqual(events, [event])
        self.assertIn("inter_agent.message.sent", [item.event_type for item in page.events])

    def test_close_run_cleans_child_sessions_without_deleting_root(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        runtime_store.save_session(self._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(self._runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="close-run"))
        _participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
        )
        cleaned: list[str] = []

        result = service.close_run(
            workspace_id="default",
            run_id=run.run_id,
            cleanup_runtime_session=lambda session_id, reason: cleaned.append(session_id) or {"session_id": session_id, "found": True},
        )

        self.assertEqual(cleaned, [child.session_id])
        self.assertEqual(result["run"].status, "cancelled")
        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "cancelled")
        self.assertEqual(runtime_store.get_session("root-session").session_id, "root-session")

    def test_interrupt_and_resume_run_cancel_active_child_turn(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(self._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(self._runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="interrupt-run"), now=now)
        participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            now=now,
        )
        runtime_store.save_turn(
            RuntimeTurnRecord(
                turn_id="active-turn",
                session_id=child.session_id,
                workspace_id="default",
                status="active",
                input_text="work",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )

        interrupted = service.interrupt_run(
            SimpleNamespace(runtime_store=runtime_store, provider_store=object(), runtime_event_bus=None),
            workspace_id="default",
            run_id=run.run_id,
            participant_id=participant.participant_id,
            reason="test-interrupt",
            now=now,
        )
        resumed = service.resume_run(
            workspace_id="default",
            run_id=run.run_id,
            reason="test-resume",
            now=now + timedelta(seconds=1),
        )

        self.assertEqual(interrupted["run"].status, "paused")
        self.assertEqual(interrupted["interrupted_sessions"][0]["cancelled_turns"], 1)
        self.assertEqual(runtime_store.get_turn("active-turn").status, "cancelled")
        self.assertEqual(
            store.get_participant(participant.participant_id, workspace_id="default", run_id=run.run_id).status,
            "cancelled",
        )
        self.assertEqual(resumed.status, "running")

    def test_startup_recovery_marks_missing_child_session_failed(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        runtime_store.save_session(self._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(self._runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="recover-run"))
        participant = store.get_participant("researcher", workspace_id="default", run_id=run.run_id)
        store.save_participant(
            participant.__class__(
                **{**participant.__dict__, "runtime_session_id": "missing-child-session", "status": "running"}
            )
        )
        store.save_run(run.__class__(**{**run.__dict__, "status": "running"}))

        result = service.recover_non_terminal_runs(runtime_store, workspace_id="default")

        recovered = store.get_participant("researcher", workspace_id="default", run_id=run.run_id)
        recovered_run = store.get_run(run.run_id, workspace_id="default")
        self.assertEqual(result["failed_participants"], 1)
        self.assertEqual(recovered.status, "failed")
        self.assertEqual(recovered_run.status, "failed")

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

    def _runtime_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def _runtime_session(
        self,
        session_id: str,
        *,
        repo_root: Path,
        system_prompt: str | None = None,
        skill_ids: list[str] | None = None,
        owner_user_id: str | None = None,
        grants: list[RuntimeSessionGrantRecord] | None = None,
    ) -> RuntimeSessionRecord:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        workspace_root = repo_root / "workspaces" / "default"
        runtime_root = workspace_root / "runtime" / "sessions" / session_id
        runtime_root.mkdir(parents=True, exist_ok=True)
        return RuntimeSessionRecord(
            session_id=session_id,
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode=None,
            effective_mode="sandbox",
            workspace_root=str(workspace_root),
            workdir=str(workspace_root),
            runtime_root=str(runtime_root),
            started_at=now,
            updated_at=now,
            ended_at=None,
            last_progress_at=now,
            system_prompt=system_prompt,
            skill_ids=skill_ids or [],
            owner_user_id=owner_user_id,
            grants=grants or [],
        )

    def _runtime_state(self, session_id: str) -> RuntimeStateRecord:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        return RuntimeStateRecord(
            session_id=session_id,
            workspace_id="default",
            current_turn_id=None,
            session_status="running",
            turn_status=None,
            last_progress_at=now,
            watchdog_deadline_at=None,
            forced_stop_reason=None,
            last_error_detail=None,
            updated_at=now,
        )


if __name__ == "__main__":
    unittest.main()
