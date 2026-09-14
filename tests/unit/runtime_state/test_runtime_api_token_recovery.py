"""Runtime bearer authority follows the owning session recovery state."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.runtime.provider_step_admission import provider_step_admission_reason
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import transition_runtime_turn
from core.runtime.session_provider_state import initial_runtime_state
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.workspace_api_token import (
    issue_workspace_api_token,
    register_workspace_api_token,
    validate_workspace_api_token_lifecycle,
)
from tests.support.collections import FakeCollection


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


class RuntimeApiTokenRecoveryTest(unittest.TestCase):
    def test_turn_scoped_token_admits_only_its_pending_provider_step(self) -> None:
        journal = SimpleNamespace(commit_status="pending", turn_id="turn-owner")
        turn = SimpleNamespace(
            turn_id="turn-owner",
            session_id="session-token-owner",
            workspace_id="default",
            status="active",
        )
        session = SimpleNamespace(workspace_id="default")
        store = SimpleNamespace(
            list_provider_step_journals=lambda **_kwargs: [journal],
            get_turn=lambda turn_id: turn if turn_id == turn.turn_id else None,
            get_session=lambda _session_id: session,
        )

        self.assertIsNone(
            provider_step_admission_reason(
                store,
                session_id="session-token-owner",
                turn_id="turn-owner",
                allow_same_turn_pairing=True,
            )
        )
        self.assertEqual(
            provider_step_admission_reason(
                store,
                session_id="session-token-owner",
                turn_id="turn-other",
                allow_same_turn_pairing=True,
            ),
            "provider_pairing_ambiguous",
        )

    def test_turn_scoped_token_carries_same_turn_admission(self) -> None:
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
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-token-owner",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
        )
        store.insert_session(session)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="turn-owner",
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                status="active",
                input_text="Use the runtime CLI.",
                created_at=NOW,
                updated_at=NOW,
                started_at=NOW,
                completed_at=None,
                failure_reason=None,
            )
        )
        with patch.dict(
            "os.environ",
            {"MAVERICK_RUNTIME_API_SECRET": "runtime-token-test-secret"},
            clear=True,
        ):
            token = issue_workspace_api_token(
                workspace_id=session.workspace_id,
                runtime_session_id=session.session_id,
                effective_mode="full-access",
                runtime_turn_id="turn-owner",
                now=NOW,
            )
            register_workspace_api_token(store, token, now=NOW)
            claims, error = validate_workspace_api_token_lifecycle(
                store,
                token,
                now=NOW,
            )

        self.assertIsNone(error)
        self.assertEqual(claims["runtime_turn_id"], "turn-owner")
        self.assertEqual(
            store.get_api_token(str(claims["token_id"])).runtime_turn_id,
            "turn-owner",
        )

    def test_turn_scoped_token_rejects_a_terminal_turn_without_pending_pairing(self) -> None:
        store, session, turn = self._turn_store()
        store.save_turn(replace(turn, status="completed", completed_at=NOW))
        with patch.dict(
            "os.environ",
            {"MAVERICK_RUNTIME_API_SECRET": "runtime-token-test-secret"},
            clear=True,
        ):
            token = issue_workspace_api_token(
                workspace_id=session.workspace_id,
                runtime_session_id=session.session_id,
                effective_mode="full-access",
                runtime_turn_id=turn.turn_id,
                now=NOW,
            )
            record = register_workspace_api_token(store, token, now=NOW)
            claims, error = validate_workspace_api_token_lifecycle(
                store,
                token,
                now=NOW,
            )

        self.assertIsNone(claims)
        self.assertEqual(error, "provider_pairing_ambiguous")
        self.assertEqual(store.get_api_token(record.token_id).status, "revoked")

    def test_terminal_transition_revokes_turn_scoped_tokens(self) -> None:
        store, session, turn = self._turn_store()
        with patch.dict(
            "os.environ",
            {"MAVERICK_RUNTIME_API_SECRET": "runtime-token-test-secret"},
            clear=True,
        ):
            token = issue_workspace_api_token(
                workspace_id=session.workspace_id,
                runtime_session_id=session.session_id,
                effective_mode="full-access",
                runtime_turn_id=turn.turn_id,
                now=NOW,
            )
            record = register_workspace_api_token(store, token, now=NOW)

        transition_runtime_turn(
            store,
            turn_id=turn.turn_id,
            target_status="completed",
            now=NOW,
            update_thread=False,
        )

        self.assertEqual(store.get_api_token(record.token_id).status, "revoked")
        self.assertEqual(store.get_api_token(record.token_id).revoked_at, NOW)

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

    @staticmethod
    def _turn_store():
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
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root="/workspace",
            workdir="/workspace",
            runtime_root="/runtime/session-token-owner",
            started_at=NOW,
            updated_at=NOW,
            ended_at=None,
            last_progress_at=NOW,
        )
        turn = RuntimeTurnRecord(
            turn_id="turn-owner",
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            status="active",
            input_text="Use the runtime CLI.",
            created_at=NOW,
            updated_at=NOW,
            started_at=NOW,
            completed_at=None,
            failure_reason=None,
        )
        store.insert_session(session)
        store.save_state(
            initial_runtime_state(
                session_id=session.session_id,
                workspace_id=session.workspace_id,
                now=NOW,
            )
        )
        store.save_turn(turn)
        return store, session, turn


if __name__ == "__main__":
    unittest.main()
