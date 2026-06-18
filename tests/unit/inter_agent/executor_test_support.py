from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.inter_agent.models import BudgetPolicySpec, EdgeSpec, InterAgentRunSpec, ParticipantSpec
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


def participant_spec(
    participant_id: str,
    label: str,
    *,
    execution_mode: str = "embedded_executor",
) -> ParticipantSpec:
    return ParticipantSpec(
        participant_id=participant_id,
        kind="agent",
        execution_mode=execution_mode,  # type: ignore[arg-type]
        label=label,
        agent_type_id=f"{participant_id}-agent",
    )


def run_spec(
    *,
    mode: str = "manager_tools",
    run_id: str = "run-f3",
    participants: list[ParticipantSpec] | None = None,
    aggregator_participant_id: str | None = None,
    merge_policy: str | None = None,
    edges: list[EdgeSpec] | None = None,
) -> InterAgentRunSpec:
    return InterAgentRunSpec(
        workspace_id="default",
        thread_id="root-session",
        root_runtime_session_id="root-session",
        source_app_id="chat",
        mode=mode,  # type: ignore[arg-type]
        created_by_user_id="user-1",
        participants=[
            ParticipantSpec(
                participant_id="orchestrator",
                kind="orchestrator",
                execution_mode="root_orchestrator",
                label="Orchestrator",
            ),
            *(participants or [participant_spec("researcher", "Researcher")]),
        ],
        budget=BudgetPolicySpec(
            max_participants=5,
            max_concurrent_participants=3,
            max_handoffs=1,
            max_total_turns=8,
            max_turns_per_participant=4,
            max_tool_calls=2,
            max_estimated_cost=Decimal("2.00"),
        ),
        aggregator_participant_id=aggregator_participant_id,
        merge_policy=merge_policy,
        edges=edges or [],
        run_id=run_id,
        idempotency_key=run_id,
    )


def runtime_store() -> RuntimeDocumentStore:
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


def runtime_state_namespace(store: RuntimeDocumentStore) -> SimpleNamespace:
    return SimpleNamespace(runtime_store=store, provider_store=object(), runtime_event_bus=None)


def root_session(repo_root: Path) -> RuntimeSessionRecord:
    workspace_root = repo_root / "workspaces" / "default"
    runtime_root = workspace_root / "runtime" / "sessions" / "root-session"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return RuntimeSessionRecord(
        session_id="root-session",
        workspace_id="default",
        agent_id="chat",
        status="running",
        requested_mode=None,
        effective_mode="sandbox",
        workspace_root=str(workspace_root),
        workdir=str(workspace_root),
        runtime_root=str(runtime_root),
        started_at=NOW,
        updated_at=NOW,
        ended_at=None,
        last_progress_at=NOW,
        source_app_id="chat",
        owner_user_id="user-1",
    )


def runtime_state() -> RuntimeStateRecord:
    return RuntimeStateRecord(
        session_id="root-session",
        workspace_id="default",
        current_turn_id=None,
        session_status="running",
        turn_status=None,
        last_progress_at=NOW,
        watchdog_deadline_at=None,
        forced_stop_reason=None,
        last_error_detail=None,
        updated_at=NOW,
    )


def build_executor_stores(test_case: Any) -> tuple[Path, Any, RuntimeDocumentStore]:
    repo_root = make_temp_repo_root(test_case)
    inter_agent_store = build_inter_agent_document_store(start_path=repo_root)
    store = runtime_store()
    store.save_session(root_session(repo_root))
    store.save_state(runtime_state())
    return repo_root, inter_agent_store, store
