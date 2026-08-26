"""Runtime bearer authority follows the owning session recovery state."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.workspace_api_token import (
    issue_workspace_api_token,
    register_workspace_api_token,
    validate_workspace_api_token_lifecycle,
)
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


class RuntimeApiTokenRecoveryTest(unittest.TestCase):
    def test_recovery_required_session_has_no_runtime_bearer_authority(self) -> None:
        store = RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
                api_tokens=FakeCollection(),
            )
        )
        session = RuntimeSessionRecord(
            session_id="session-token-owner",
            workspace_id="default",
            agent_id="chat",
            status="running",
            requested_mode="sandbox",
            effective_mode="sandbox",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-token-owner",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
        )
        store.insert_session(session)
        with patch.dict(
            "os.environ",
            {"MAVERICK_RUNTIME_API_SECRET": "runtime-token-test-secret"},
            clear=True,
        ):
            token = issue_workspace_api_token(
                workspace_id=session.workspace_id,
                runtime_session_id=session.session_id,
                now=NOW,
            )
            self.assertIsNotNone(register_workspace_api_token(store, token, now=NOW))
            claims, error = validate_workspace_api_token_lifecycle(
                store,
                token,
                now=NOW,
            )
            self.assertIsNotNone(claims)
            self.assertIsNone(error)

            store.save_session(
                replace(
                    session,
                    status="recovery_required",
                    recovery_reason_code="runtime_state_ambiguous",
                )
            )
            claims, error = validate_workspace_api_token_lifecycle(
                store,
                token,
                now=NOW,
            )

        self.assertIsNone(claims)
        self.assertEqual(error, "runtime_session_recovery_required")


if __name__ == "__main__":
    unittest.main()
