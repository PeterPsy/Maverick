from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.session_api import RequestSession
from core.api.settings_api import platform_settings_payload
from core.authorization.errors import AuthorizationError


class SettingsAgenticAdminTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SimpleNamespace(
            workspace_store=SimpleNamespace(),
            recovery_store=SimpleNamespace(),
        )
        self.context = RequestSession(
            user=SimpleNamespace(user_id="workspace-admin", platform_role="member"),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="workspace-1",
        )

    def test_workspace_admin_receives_agentic_binding_controls(self) -> None:
        with self._payload_dependencies(), patch(
            "core.api.settings_api.require_provider_selection_authority",
            return_value=None,
        ):
            payload = platform_settings_payload(self.state, self.context)

        self.assertEqual(payload["agentic_admin"], {"workspace_id": "workspace-1", "items": []})

    def test_workspace_member_does_not_receive_agentic_binding_controls(self) -> None:
        with self._payload_dependencies(), patch(
            "core.api.settings_api.require_provider_selection_authority",
            side_effect=AuthorizationError("provider_selection_forbidden"),
        ):
            payload = platform_settings_payload(self.state, self.context)

        self.assertNotIn("agentic_admin", payload)

    def _payload_dependencies(self):
        stack = ExitStack()
        stack.enter_context(patch("core.api.settings_api.public_user_payload", return_value={}))
        stack.enter_context(patch("core.api.settings_api.workspace_payload", return_value={}))
        stack.enter_context(patch("core.api.settings_api.workspace_provider_status", return_value={}))
        stack.enter_context(patch("core.api.settings_api.workspace_runtime_status", return_value={}))
        stack.enter_context(patch("core.api.settings_api.recovery_status", return_value={}))
        stack.enter_context(patch("core.api.settings_api._runtime_cleanup_scope", return_value="none"))
        stack.enter_context(
            patch(
                "core.api.settings_api.workspace_agentic_admin_status",
                return_value={"workspace_id": "workspace-1", "items": []},
            )
        )
        return stack


if __name__ == "__main__":
    unittest.main()
