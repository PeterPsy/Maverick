"""Continuation forks never propagate legacy session data declarations."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.recovery.continuation_materialization import ensure_successor_session
from core.runtime.errors import RuntimeSessionNotFoundError


NOW = datetime(2026, 8, 26, tzinfo=UTC)


class ContinuationDataClassificationTest(unittest.TestCase):
    def test_successor_drops_legacy_predecessor_declaration(self) -> None:
        binding = object()
        predecessor = SimpleNamespace(
            session_id="session-predecessor",
            workspace_id="default",
            agent_id="chat",
            requested_mode="sandbox",
            system_prompt=None,
            skill_ids=[],
            skill_catalog_app_id=None,
            skill_activation_mode="implicit",
            source_app_id="chat",
            thread_title="Chat",
            agent_label="Chat",
            agent_type_id="chat",
            agent_role_id="",
            project_id=None,
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            creator_runtime_session_id=None,
            lineage_root_session_id=None,
            session_kind="chat_root",
            thread_visibility="user",
            runtime_mode="agentic",
            hosted_provider_id=None,
            hosted_model_id=None,
            declared_remote_data_class="legacy-do-not-propagate",
            grants=[],
        )
        handoff = SimpleNamespace(
            successor_session_id="session-successor",
            handoff_id="handoff-1",
            reason_code="profile_revision_changed",
            created_at=NOW,
            target_execution_binding=binding,
        )
        successor = SimpleNamespace(
            predecessor_session_id=predecessor.session_id,
            continuation_handoff_id=handoff.handoff_id,
            execution_binding=binding,
        )
        runtime_store = Mock()
        runtime_store.get_session.side_effect = RuntimeSessionNotFoundError("missing")
        state = SimpleNamespace(
            runtime_store=runtime_store,
            workspace_store=None,
            repository_root=None,
            observability_store=None,
        )

        with patch(
            "core.recovery.continuation_materialization.create_runtime_session",
            return_value=successor,
        ) as create_session:
            result = ensure_successor_session(state, predecessor, handoff)

        self.assertIs(result, successor)
        self.assertIsNone(
            create_session.call_args.kwargs["declared_remote_data_class"]
        )


if __name__ == "__main__":
    unittest.main()
