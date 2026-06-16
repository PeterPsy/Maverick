from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeThreadVisibilityApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_hidden_runtime_session_cannot_be_opened_as_chat_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            create_runtime_session(
                state.runtime_store,
                session_id="visible-session",
                workspace_id="default",
                agent_id="chat",
                source_app_id="chat",
                start_path=repo_root,
            )
            create_runtime_session(
                state.runtime_store,
                session_id="hidden-session",
                workspace_id="default",
                agent_id="child-agent",
                source_app_id="chat",
                session_kind="inter_agent_participant",
                thread_visibility="hidden",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            create_status, create_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                method="POST",
                body={"runtime_session_id": "hidden-session"},
                cookie=cookie,
            )
            open_status, open_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/hidden-session",
                cookie=cookie,
            )
            read_status, read_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/hidden-session/read",
                method="POST",
                cookie=cookie,
            )
            list_status, list_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads",
                cookie=cookie,
            )
            patch_status, patch_payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/visible-session",
                method="PATCH",
                body={"runtime_session_id": "hidden-session"},
                cookie=cookie,
            )

        self.assertEqual(create_status, 409)
        self.assertEqual(create_payload["error"], "runtime_session_hidden")
        self.assertEqual(open_status, 409)
        self.assertEqual(open_payload["error"], "runtime_session_hidden")
        self.assertEqual(read_status, 409)
        self.assertEqual(read_payload["error"], "runtime_session_hidden")
        self.assertEqual(list_status, 200)
        self.assertEqual([thread["runtime_session_id"] for thread in list_payload["threads"]], ["visible-session"])
        self.assertEqual(patch_status, 409)
        self.assertEqual(patch_payload["error"], "runtime_session_hidden")


if __name__ == "__main__":
    unittest.main()
