from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.api.runtime_api import _list_session_payloads
from core.api.provider_api import workspace_runtime_status


class RuntimeSessionCollectionProjectionTestCase(unittest.TestCase):
    def test_runtime_status_reuses_one_context_for_provider_and_sessions(self) -> None:
        sessions = [SimpleNamespace(session_id="session-1")]
        state = SimpleNamespace(
            runtime_store=SimpleNamespace(list_sessions=Mock(return_value=sessions)),
        )
        projection_context = object()

        with patch(
            "core.api.provider_api.provider_projection_context",
            return_value=projection_context,
        ) as build_context, patch(
            "core.api.provider_api.workspace_provider_status",
            return_value={"workspace_id": "default"},
        ) as provider_status, patch(
            "core.api.provider_api.runtime_session_payload",
            return_value={"session_id": "session-1"},
        ) as session_payload:
            payload = workspace_runtime_status(state, workspace_id="default")

        self.assertEqual(
            payload,
            {"workspace_id": "default", "sessions": [{"session_id": "session-1"}]},
        )
        build_context.assert_called_once_with(state)
        provider_status.assert_called_once_with(
            state,
            workspace_id="default",
            actor_roles=None,
            projection_context=projection_context,
        )
        session_payload.assert_called_once_with(
            sessions[0],
            state=state,
            projection_context=projection_context,
        )

    def test_collection_reuses_one_governance_projection_context(self) -> None:
        sessions = [
            SimpleNamespace(session_id="session-1", execution_binding=object()),
            SimpleNamespace(session_id="session-2", execution_binding=object()),
        ]
        state = SimpleNamespace(
            runtime_store=SimpleNamespace(list_sessions=Mock(return_value=sessions)),
        )
        projection_context = object()

        with (
            patch(
                "core.api.runtime_api._visibility_reconciled_session",
                side_effect=lambda _state, session: session,
            ),
            patch(
                "core.api.runtime_api._reconciled_session",
                side_effect=lambda _state, session, **_kwargs: session,
            ),
            patch(
                "core.api.runtime_api.runtime_session_allows_user_thread",
                return_value=True,
            ),
            patch(
                "core.api.runtime_api.provider_projection_context",
                return_value=projection_context,
            ) as build_context,
            patch(
                "core.api.runtime_api._resolved_provider_id",
                return_value="codex",
            ),
            patch(
                "core.api.runtime_api._session_payload",
                side_effect=lambda session, **_kwargs: {"session_id": session.session_id},
            ) as session_payload,
        ):
            payloads = _list_session_payloads(
                state,
                workspace_id="default",
                start_path="/repo",
            )

        self.assertEqual(
            payloads,
            [{"session_id": "session-1"}, {"session_id": "session-2"}],
        )
        build_context.assert_called_once_with(state)
        self.assertEqual(session_payload.call_count, 2)
        for call in session_payload.call_args_list:
            self.assertIs(
                call.kwargs["governance_projection_context"],
                projection_context,
            )


if __name__ == "__main__":
    unittest.main()
