from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from core.inter_agent.errors import InterAgentBudgetExceededError
from core.inter_agent.models import BudgetPolicySpec, InterAgentRunSpec
from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_service_runtime import _run_spec, _state


class InterAgentRuntimeBudgetTest(unittest.TestCase):
    def test_send_runtime_message_enforces_turn_budget_per_participant(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        spec = _run_spec(idempotency_key="turn-budget-per-participant")
        spec = InterAgentRunSpec(
            **{
                **spec.__dict__,
                "budget": BudgetPolicySpec(
                    max_participants=3,
                    max_concurrent_participants=2,
                    max_total_turns=2,
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
            turn_id="turn-budget-per-participant-1",
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


def _runtime_store() -> RuntimeDocumentStore:
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


def _runtime_session(session_id: str, *, repo_root: Path) -> RuntimeSessionRecord:
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
    )


def _runtime_state(session_id: str) -> RuntimeStateRecord:
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
