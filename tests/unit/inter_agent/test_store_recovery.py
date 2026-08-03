from __future__ import annotations

from datetime import UTC, datetime
import unittest

from core.inter_agent.events import EventRetentionPolicyRecord, InterAgentEventRecord
from core.inter_agent.store import build_inter_agent_document_store
from tests.support.repo import make_temp_repo_root


def _event(index: int, *, event_type: str, visibility_plane: str) -> InterAgentEventRecord:
    return InterAgentEventRecord(
        event_id=f"event-{index}",
        workspace_id="default",
        run_id="run-1",
        thread_id="thread-1",
        root_runtime_session_id="root-session",
        participant_id="orchestrator",
        runtime_session_id=None,
        runtime_turn_id=None,
        runtime_event_id=None,
        event_type=event_type,  # type: ignore[arg-type]
        visibility_plane=visibility_plane,  # type: ignore[arg-type]
        sequence=0,
        correlation_id=f"corr-{index}",
        idempotency_key=None,
        payload={"index": index},
        created_at=datetime(2026, 8, 3, 12, index, tzinfo=UTC),
    )


def _retention() -> EventRetentionPolicyRecord:
    return EventRetentionPolicyRecord(
        retention_policy_id="retention-1",
        workspace_id="default",
        summary_max_events=1,
        detail_max_events=1,
        debug_max_events=1,
        created_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
    )


class InterAgentStoreRecoveryTest(unittest.TestCase):
    def test_recovery_events_are_not_pruned_with_visibility_history(self) -> None:
        store = build_inter_agent_document_store(start_path=make_temp_repo_root(self))
        retention = _retention()
        event_specs = (
            (1, "inter_agent.plan.summary_created", "summary"),
            (2, "inter_agent.summary.updated", "summary"),
            (3, "inter_agent.summary.updated", "summary"),
            (4, "inter_agent.task.completed", "detail"),
            (5, "inter_agent.task.started", "detail"),
            (6, "inter_agent.task.started", "detail"),
        )
        for index, event_type, visibility_plane in event_specs:
            store.append_event(
                _event(index, event_type=event_type, visibility_plane=visibility_plane),
                retention_policy=retention,
            )

        page = store.list_event_page("run-1", workspace_id="default", visibility_plane="debug", limit=10)

        self.assertEqual(
            [(event.event_id, event.event_type) for event in page.events],
            [
                ("event-1", "inter_agent.plan.summary_created"),
                ("event-3", "inter_agent.summary.updated"),
                ("event-4", "inter_agent.task.completed"),
                ("event-6", "inter_agent.task.started"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
