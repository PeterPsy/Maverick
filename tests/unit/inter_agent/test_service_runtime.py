from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from core.inter_agent.errors import InterAgentBudgetExceededError, InterAgentOperationError
from core.inter_agent.models import AgentParticipantSnapshot, BudgetPolicySpec, InterAgentRunSpec, ParticipantSpec
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
                label="Researcher",
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


def _state(runtime_store: RuntimeDocumentStore) -> SimpleNamespace:
    return SimpleNamespace(runtime_store=runtime_store, provider_store=object(), runtime_event_bus=None)


class InterAgentRuntimeServiceTest(unittest.TestCase):
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
        run = service.create_run(
            _run_spec(
                idempotency_key="send-message",
                researcher_snapshot=AgentParticipantSnapshot(
                    agent_type_id="research-agent",
                    label="Researcher",
                    system_prompt="Use Storage when needed.",
                    skill_ids=["storage-ops"],
                    skill_catalog_app_id="skills",
                    skill_activation_mode="explicit",
                ),
            ),
            now=now,
        )
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

        with patch("core.inter_agent.service.submit_runtime_turn", return_value=(turn, [event])) as submit:
            sent_participant, sent_turn, events = service.send_runtime_message(
                _state(runtime_store),
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
        self.assertEqual(submit.call_args.kwargs["invoked_skill_ids"], ["storage-ops"])

    def test_send_runtime_message_enforces_total_turn_budget(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(self._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(self._runtime_state("root-session"))
        spec = _run_spec(idempotency_key="turn-budget")
        spec = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "budget": BudgetPolicySpec(
                    max_participants=3,
                    max_concurrent_participants=2,
                    max_total_turns=1,
                    max_turns_per_participant=1,
                    max_tool_calls=2,
                    max_estimated_cost=Decimal("1.00"),
                ),
            }
        )
        run = service.create_run(spec, now=now)
        participant, child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            now=now,
        )
        turn = RuntimeTurnRecord(
            turn_id="turn-budget-1",
            session_id=child.session_id,
            workspace_id="default",
            status="completed",
            input_text="first",
            created_at=now,
            updated_at=now,
            started_at=now,
            completed_at=now,
            failure_reason=None,
        )

        with patch("core.inter_agent.service.submit_runtime_turn", return_value=(turn, [])) as submit_mock:
            service.send_runtime_message(
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                participant_id=participant.participant_id,
                input_text="first",
                client_message_id="first-message",
                now=now,
            )
            with self.assertRaises(InterAgentBudgetExceededError):
                service.send_runtime_message(
                    _state(runtime_store),
                    workspace_id="default",
                    run_id=run.run_id,
                    participant_id=participant.participant_id,
                    input_text="second",
                    client_message_id="second-message",
                    now=now,
                )

        ledger = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        self.assertEqual(submit_mock.call_count, 1)
        self.assertEqual(ledger.turns_used, 1)
        self.assertEqual(ledger.running_participants, 1)

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
        ledger_before = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        cleaned: list[str] = []

        result = service.close_run(
            workspace_id="default",
            run_id=run.run_id,
            cleanup_runtime_session=(
                lambda session_id, reason: cleaned.append(session_id) or {"session_id": session_id, "found": True}
            ),
        )

        self.assertEqual(cleaned, [child.session_id])
        self.assertEqual(result["run"].status, "cancelled")
        self.assertEqual(store.get_run(run.run_id, workspace_id="default").status, "cancelled")
        self.assertEqual(runtime_store.get_session("root-session").session_id, "root-session")
        ledger_after = store.get_budget_ledger(run.budget_ledger_id, workspace_id="default")
        events = store.list_event_page(run.run_id, workspace_id="default", visibility_plane="debug", limit=50).events
        event_types = [event.event_type for event in events]
        cancelled_status_events = [
            event
            for event in events
            if event.event_type == "inter_agent.participant.status_changed"
            and event.participant_id == "researcher"
            and event.payload.get("status") == "cancelled"
        ]
        self.assertEqual(ledger_before.running_participants, 1)
        self.assertEqual(ledger_before.turns_used, 0)
        self.assertEqual(ledger_after.reserved_participants, 0)
        self.assertEqual(ledger_after.running_participants, 0)
        self.assertEqual(ledger_after.turns_used, 0)
        self.assertEqual(len(cancelled_status_events), 1)
        self.assertLess(
            event_types.index("inter_agent.participant.status_changed"),
            event_types.index("inter_agent.run.cancelled"),
        )

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
            _state(runtime_store),
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

    def test_send_runtime_message_rejects_paused_run_and_cancelled_participant(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = self._runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(self._runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(self._runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="blocked-after-interrupt"), now=now)
        participant, _child, _created = service.spawn_participant_runtime_session(
            runtime_store,
            workspace_id="default",
            run_id=run.run_id,
            participant_id="researcher",
            now=now,
        )
        service.interrupt_run(
            _state(runtime_store),
            workspace_id="default",
            run_id=run.run_id,
            participant_id=participant.participant_id,
            reason="test-interrupt",
            now=now,
        )

        with self.assertRaisesRegex(InterAgentOperationError, "run is not accepting"):
            service.send_runtime_message(
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                participant_id=participant.participant_id,
                input_text="blocked while paused",
                now=now,
            )

        service.resume_run(
            workspace_id="default",
            run_id=run.run_id,
            reason="test-resume",
            now=now + timedelta(seconds=1),
        )
        with self.assertRaisesRegex(InterAgentOperationError, "Participant is not accepting"):
            service.send_runtime_message(
                _state(runtime_store),
                workspace_id="default",
                run_id=run.run_id,
                participant_id=participant.participant_id,
                input_text="blocked after resume",
                now=now,
            )

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
