from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import unittest

from core.inter_agent.service import InterAgentService
from core.inter_agent.store import build_inter_agent_document_store
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.runtime_threads import create_runtime_thread
from core.runtime.service import queue_runtime_turn, record_runtime_event
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root
from tests.unit.inter_agent.test_service_runtime import _run_spec


class InterAgentRuntimeRecoveryTest(unittest.TestCase):
    def test_startup_recovery_closes_async_root_turn_for_planning_run_without_children(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = build_inter_agent_document_store(start_path=repo_root)
        runtime_store = _runtime_store()
        service = InterAgentService(store)
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        runtime_store.save_session(_runtime_session("root-session", repo_root=repo_root))
        runtime_store.save_state(_runtime_state("root-session"))
        run = service.create_run(_run_spec(idempotency_key="recover-async-run"), now=now)
        service.mark_run_planning(workspace_id="default", run_id=run.run_id, now=now)
        turn = queue_runtime_turn(
            runtime_store,
            turn_id="root-turn-recover-async",
            session_id="root-session",
            input_text="Run async work.",
            now=now,
        )
        record_runtime_event(
            runtime_store,
            event_id="event-root-turn-recover-async",
            session_id="root-session",
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"inter_agent_run_id": run.run_id},
            now=now,
        )
        create_runtime_thread(
            runtime_store,
            workspace_id="default",
            thread_id="root-session",
            runtime_session_id="root-session",
            title="Async run",
            agent_label="chat",
            source_app_id="chat",
            now=now,
        )

        result = service.recover_non_terminal_runs(runtime_store, workspace_id="default", now=now + timedelta(seconds=1))

        recovered_run = store.get_run(run.run_id, workspace_id="default")
        recovered_turn = runtime_store.get_turn(turn.turn_id)
        root_thread = runtime_store.get_thread("root-session")
        root_event_types = [event.event_type for event in runtime_store.list_events("root-session")]
        self.assertEqual(result["failed_runs"], 1)
        self.assertEqual(result["closed_root_turns"], 1)
        self.assertEqual(recovered_run.status, "failed")
        self.assertEqual(recovered_turn.status, "cancelled")
        self.assertEqual(root_thread.availability, "free")
        self.assertIn("runtime.turn.cancelled", root_event_types)


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
