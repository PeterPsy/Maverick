from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.service import (
    create_runtime_session,
    queue_runtime_turn,
    transition_runtime_session,
)
from core.runtime.turn_submission import (
    prewarm_runtime_session_async,
    runtime_session_prewarm_status,
)
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport
from tests.support.repo import make_temp_repo_root


class RuntimeTurnQueueFenceTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_queue_uses_session_lifecycle_handoff(self) -> None:
        root = make_temp_repo_root(self)
        state = bootstrap_platform_state(
            start_path=root,
            install_builtin_apps=False,
        )
        session = create_runtime_session(
            state.runtime_store,
            session_id="queue-fence-session",
            workspace_id="default",
            agent_id="chat",
            start_path=root,
        )

        original = state.runtime_store.session_lifecycle_handoff
        with patch.object(
            state.runtime_store,
            "session_lifecycle_handoff",
            wraps=original,
        ) as lifecycle_handoff:
            queue_runtime_turn(
                state.runtime_store,
                turn_id="queue-fence-turn",
                session_id=session.session_id,
                input_text="serialize this turn",
            )

        lifecycle_handoff.assert_called_once_with(
            workspace_id="default",
            session_id=session.session_id,
        )

    def test_stopped_session_rejects_queue_without_persisting_turn(self) -> None:
        root = make_temp_repo_root(self)
        state = bootstrap_platform_state(
            start_path=root,
            install_builtin_apps=False,
        )
        session = create_runtime_session(
            state.runtime_store,
            session_id="stopped-queue-session",
            workspace_id="default",
            agent_id="chat",
            start_path=root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="stopped",
        )

        with self.assertRaises(RuntimeTurnQueueRejectedError):
            queue_runtime_turn(
                state.runtime_store,
                turn_id="rejected-stopped-turn",
                session_id=session.session_id,
                input_text="must not be queued",
            )

        self.assertEqual(state.runtime_store.list_turns(session.session_id), [])

    def test_prewarm_skips_a_stopped_session_before_provider_resolution(self) -> None:
        root = make_temp_repo_root(self)
        state = bootstrap_platform_state(
            start_path=root,
            install_builtin_apps=False,
        )
        session = create_runtime_session(
            state.runtime_store,
            session_id="stopped-prewarm-session",
            workspace_id="default",
            agent_id="chat",
            start_path=root,
        )
        transition_runtime_session(
            state.runtime_store,
            session_id=session.session_id,
            target_status="stopped",
        )
        with patch(
            "core.runtime.turn_submission_service_runtime.Thread",
            _ImmediateThread,
        ), patch(
            "core.runtime.turn_submission_service_runtime.resolve_runtime_engine_for_session"
        ) as resolve_engine:
            prewarm_runtime_session_async(state, session=session)

        resolve_engine.assert_not_called()
        self.assertEqual(
            runtime_session_prewarm_status(session.session_id).status,
            "skipped_session_not_executable",
        )

    def test_http_turn_submission_reports_non_executable_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=root)
            app = PlatformHost(state, start_path=root)
            cookie = self._login(app)
            status, payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={"agent_id": "chat", "source_app_id": "chat"},
                cookie=cookie,
            )
            self.assertEqual(status, 201)
            session_id = payload["session_id"]
            transition_runtime_session(
                state.runtime_store,
                session_id=session_id,
                target_status="stopped",
            )

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/turns",
                method="POST",
                body={"input_text": "do not revive implicitly", "async": True},
                cookie=cookie,
            )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "runtime_session_not_executable")
            self.assertEqual(state.runtime_store.list_turns(session_id), [])

class _ImmediateThread:
    def __init__(self, *, target, name, daemon) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


if __name__ == "__main__":
    unittest.main()
