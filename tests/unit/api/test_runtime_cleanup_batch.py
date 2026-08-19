from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.runtime_cleanup_batch import cleanup_runtime_sessions_batch
from core.inter_agent.service import RUNTIME_CHILD_EXECUTION_MODE
from tests.support.repo import make_temp_repo_root


class RuntimeCleanupBatchTest(unittest.TestCase):
    def test_batch_expands_children_and_invokes_app_hooks_once(self) -> None:
        repo_root = make_temp_repo_root(self)
        run = SimpleNamespace(run_id="run-1", root_runtime_session_id="root", status="running")
        participant = SimpleNamespace(
            execution_mode=RUNTIME_CHILD_EXECUTION_MODE,
            runtime_session_id="child",
        )
        sessions = {
            session_id: SimpleNamespace(session_id=session_id, workspace_id="default")
            for session_id in ("root", "child")
        }
        state = SimpleNamespace(
            repository_root=repo_root,
            runtime_store=SimpleNamespace(
                get_session=lambda session_id: sessions[session_id],
                delete_session_records_batch=lambda session_ids: {
                    session_id: {} for session_id in session_ids
                },
            ),
            inter_agent_store=SimpleNamespace(
                list_runs=lambda _workspace_id: [run],
                list_participants=lambda _run_id, workspace_id: [participant],
            ),
        )
        cleanup_calls: list[tuple[str, bool]] = []

        class FakeInterAgentService:
            def __init__(self, _store) -> None:
                pass

            def close_run(self, **kwargs):
                kwargs["cleanup_runtime_session"]("child", kwargs["reason"])
                return {"participant_cleanups": [], "deleted": {"runs": 1}}

        def cleanup_session(_state, *, session_id: str, allow_hidden_inter_agent_cleanup: bool, **_kwargs):
            cleanup_calls.append((session_id, allow_hidden_inter_agent_cleanup))
            return {"session_id": session_id, "found": True}

        with patch(
            "core.api.runtime_cleanup_batch.InterAgentService",
            FakeInterAgentService,
        ), patch(
            "core.api.runtime_cleanup_batch.cleanup_runtime_session",
            side_effect=cleanup_session,
        ), patch(
            "core.api.runtime_cleanup_batch.cleanup_app_runtime_session_metadata",
            return_value=[{"app_id": "design-studio"}],
        ) as app_cleanup:
            result = cleanup_runtime_sessions_batch(
                state,
                session_ids=["root"],
                workspace_id="default",
                reason="test",
                start_path=repo_root,
                delete_threads=False,
            )

        app_cleanup.assert_called_once_with(
            state,
            workspace_id="default",
            session_ids=["root", "child"],
            start_path=repo_root,
        )
        self.assertEqual(cleanup_calls, [("child", True), ("root", False)])
        self.assertEqual(result["expanded_session_ids"], ["root", "child"])
        self.assertEqual([item["session_id"] for item in result["session_results"]], ["root", "child"])

    def test_batch_does_not_clean_a_session_from_another_workspace(self) -> None:
        repo_root = make_temp_repo_root(self)
        foreign_session = SimpleNamespace(session_id="foreign", workspace_id="another-workspace")
        state = SimpleNamespace(
            repository_root=repo_root,
            runtime_store=SimpleNamespace(
                get_session=lambda _session_id: foreign_session,
                delete_session_records_batch=lambda _session_ids: {},
            ),
            inter_agent_store=SimpleNamespace(list_runs=lambda _workspace_id: []),
        )

        with patch(
            "core.api.runtime_cleanup_batch.cleanup_runtime_session",
            side_effect=AssertionError("foreign session cleaned"),
        ), patch(
            "core.api.runtime_cleanup_batch.cleanup_app_runtime_session_metadata",
            return_value=[],
        ):
            result = cleanup_runtime_sessions_batch(
                state,
                session_ids=["foreign"],
                workspace_id="default",
                reason="test",
                start_path=repo_root,
                delete_threads=False,
            )

        self.assertEqual(result["session_results"][0]["session_id"], "foreign")
        self.assertFalse(result["session_results"][0]["found"])


if __name__ == "__main__":
    unittest.main()
