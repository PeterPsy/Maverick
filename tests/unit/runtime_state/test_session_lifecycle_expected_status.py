"""Reviewed lifecycle transitions validate expected state under the handoff."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from core.runtime.errors import RuntimeTransitionError
from core.runtime.lifecycle_service import transition_runtime_session
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 26, tzinfo=UTC)


class SessionLifecycleExpectedStatusTest(unittest.TestCase):
    def test_changed_status_fails_inside_lifecycle_handoff(self) -> None:
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )
        session = RuntimeSessionRecord(
            session_id="session-lifecycle-conflict",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-lifecycle-conflict",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
        )
        store.insert_session(session)
        store.save_state(
            RuntimeStateRecord(
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                current_turn_id=None,
                session_status=session.status,
                turn_status=None,
                last_progress_at=NOW,
                watchdog_deadline_at=None,
                forced_stop_reason=None,
                last_error_detail=None,
                updated_at=NOW,
            )
        )

        with self.assertRaisesRegex(
            RuntimeTransitionError,
            "runtime_session_expected_status_changed",
        ):
            transition_runtime_session(
                store,
                session_id=session.session_id,
                target_status="recovery_required",
                expected_status="created",
                now=NOW,
            )

        self.assertEqual(store.get_session(session.session_id).status, "running")
        self.assertEqual(store.get_state(session.session_id).session_status, "running")


if __name__ == "__main__":
    unittest.main()
