"""Structured runtime failure propagation regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

from core.runtime.event_collection import RuntimeEventJsonCollection
from core.runtime.failure_messages import runtime_failure_details, runtime_failure_public_message
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from core.runtime.session_collection import RuntimeSessionJsonCollection
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.turn_submission_service_events import _complete_turn_from_exit_code
from core.runtime.workspace_collection import WorkspaceRuntimeJsonCollection
from tests.support.repo import make_temp_repo_root


PUBLIC_TOOL_ERROR = (
    "The model requested a tool that is not available. "
    "The unavailable tool was not executed."
)


class StructuredRuntimeFailureTest(unittest.TestCase):
    def test_provider_overload_has_actionable_public_message(self) -> None:
        public_message = runtime_failure_public_message("provider_overloaded")

        self.assertIn("temporarily overloaded", public_message)
        self.assertIn("completed actions are preserved", public_message)

    def test_provider_cybersecurity_policy_block_has_actionable_public_message(self) -> None:
        public_message = runtime_failure_public_message(
            "provider_cybersecurity_policy_blocked"
        )

        self.assertIn("cybersecurity policy", public_message)
        self.assertIn("Rephrase", public_message)

    def test_profile_upgrade_failures_have_actionable_public_messages(self) -> None:
        self.assertIn(
            "older runtime profile",
            runtime_failure_public_message("adapter_artifact_mismatch"),
        )
        self.assertIn(
            "compatible runtime-profile upgrade",
            runtime_failure_public_message("runtime_profile_upgrade_required"),
        )

    def test_raw_exception_text_cannot_become_a_public_reason_code(self) -> None:
        reason_code, public_message = runtime_failure_details(
            RuntimeError("private_token_value")
        )

        self.assertEqual(reason_code, "runtime_execution_failed")
        self.assertEqual(public_message, "The runtime could not complete this request.")
        self.assertNotIn("private_token_value", public_message)

    def test_failed_exit_persists_public_error_instead_of_numeric_only(self) -> None:
        repo_root = make_temp_repo_root(self)
        store = _runtime_json_store(repo_root)
        session = create_runtime_session(
            store,
            session_id="structured-failure",
            workspace_id="default",
            agent_id="chat",
            start_path=repo_root,
        )
        now = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
        store.save_turn(
            RuntimeTurnRecord(
                turn_id="structured-failure-turn",
                session_id=session.session_id,
                workspace_id="default",
                status="active",
                input_text="trigger a fixture failure",
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                failure_reason=None,
            )
        )

        failed, event = _complete_turn_from_exit_code(
            SimpleNamespace(
                runtime_store=store,
                runtime_event_bus=None,
                repository_root=repo_root,
            ),
            session_id=session.session_id,
            turn_id="structured-failure-turn",
            provider_id="maverick-tool-loop",
            exit_code=1,
            failure_reason_code="tool_not_found",
            public_error_message=PUBLIC_TOOL_ERROR,
            diagnostic_reference="turn:structured-failure-turn",
        )

        self.assertEqual(failed.failure_reason, PUBLIC_TOOL_ERROR)
        self.assertEqual(event.payload["failure_reason_code"], "tool_not_found")
        self.assertEqual(
            event.payload["diagnostic_reference"],
            "turn:structured-failure-turn",
        )
        self.assertEqual(event.payload["error"], failed.failure_reason)


def _runtime_json_store(repo_root) -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=RuntimeSessionJsonCollection(
                start_path=repo_root,
                filename="sessions.json",
            ),
            turns=RuntimeSessionJsonCollection(
                start_path=repo_root,
                filename="turns.json",
            ),
            events=RuntimeEventJsonCollection(start_path=repo_root),
            processes=RuntimeSessionJsonCollection(
                start_path=repo_root,
                filename="processes.json",
            ),
            states=RuntimeSessionJsonCollection(
                start_path=repo_root,
                filename="state.json",
            ),
            threads=WorkspaceRuntimeJsonCollection(
                start_path=repo_root,
                filename="threads.json",
            ),
        )
    )


if __name__ == "__main__":
    unittest.main()
