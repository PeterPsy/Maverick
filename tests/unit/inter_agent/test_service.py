from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
import unittest

from core.api.platform_state import bootstrap_platform_state
from core.inter_agent.models import (
    ApprovalRequestRecord,
    BudgetPolicySpec,
    InterAgentRunSpec,
    ParticipantSpec,
)
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


class InterAgentServiceTest(unittest.TestCase):
    def run_spec(self, *, idempotency_key: str | None = None) -> InterAgentRunSpec:
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

    def test_create_run_materializes_records_and_no_runtime_sessions(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)

        run = service.create_run(self.run_spec(idempotency_key="create-run-1"), now=now)
        same_run = service.create_run(self.run_spec(idempotency_key="create-run-1"), now=now + timedelta(minutes=1))
        participants = store.list_participants(run.run_id)
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
        stored = store.get_approval("approval-1")

        self.assertEqual([item.approval_id for item in expired], ["approval-1"])
        self.assertEqual(stored.status, "expired")
        self.assertEqual(stored.resolution_reason, "approval_timeout")

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
