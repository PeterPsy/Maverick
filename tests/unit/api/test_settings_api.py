from __future__ import annotations

from contextlib import ExitStack
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.session_api import RequestSession
from core.api.settings_api import handle_settings_api, platform_settings_payload
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
        projection_context = object()
        with self._payload_dependencies(), patch(
            "core.api.settings_api.provider_projection_context",
            return_value=projection_context,
        ) as build_projection_context, patch(
            "core.api.settings_api.workspace_provider_status",
            return_value={"workspace_id": "workspace-1"},
        ) as provider_status, patch(
            "core.api.settings_api.workspace_agentic_admin_status",
            return_value={"workspace_id": "workspace-1", "items": []},
        ) as agentic_admin, patch(
            "core.api.settings_api.require_provider_selection_authority",
            return_value=None,
        ):
            payload = platform_settings_payload(self.state, self.context)

        self.assertEqual(payload["agentic_admin"], {"workspace_id": "workspace-1", "items": []})
        self.assertEqual(
            payload["runtime"],
            {"sessions": [], "cleanup_allowed": False, "cleanup_scope": "none"},
        )
        build_projection_context.assert_called_once_with(
            self.state,
            reconcile_model_catalog=True,
        )
        provider_status.assert_called_once_with(
            self.state,
            workspace_id="workspace-1",
            projection_context=projection_context,
        )
        agentic_admin.assert_called_once_with(
            self.state,
            workspace_id="workspace-1",
            compact=True,
            projection_context=projection_context,
        )

    def test_workspace_member_does_not_receive_agentic_binding_controls(self) -> None:
        with self._payload_dependencies(), patch(
            "core.api.settings_api.require_provider_selection_authority",
            side_effect=AuthorizationError("provider_selection_forbidden"),
        ):
            payload = platform_settings_payload(self.state, self.context)

        self.assertNotIn("agentic_admin", payload)

    def test_context_read_does_not_probe_catalogs_computer_use_or_recovery(self) -> None:
        with self._payload_dependencies(), patch("core.api.settings_api.provider_projection_context") as catalog, patch(
            "core.api.settings_api.computer_actor_settings"
        ) as computer, patch("core.api.settings_api.recovery_status") as recovery:
            timings = {}
            payload = platform_settings_payload(self.state, self.context, section="context", timings=timings)
        catalog.assert_not_called()
        computer.assert_not_called()
        recovery.assert_not_called()
        self.assertEqual(set(timings), {"workspace"})
        self.assertEqual(payload["provider"]["active_provider"], None)

    def test_models_read_does_not_load_computer_use_or_recovery(self) -> None:
        with self._payload_dependencies(), patch("core.api.settings_api.computer_actor_settings") as computer, patch(
            "core.api.settings_api.recovery_status"
        ) as recovery:
            with patch("core.api.settings_api.require_provider_selection_authority"):
                payload = platform_settings_payload(self.state, self.context, section="models")
        computer.assert_not_called()
        recovery.assert_not_called()
        self.assertIn("agentic_admin", payload)

    def test_computer_use_read_does_not_load_provider_catalog(self) -> None:
        with self._payload_dependencies(), patch("core.api.settings_api.provider_projection_context") as catalog:
            payload = platform_settings_payload(self.state, self.context, section="computer-use")
        catalog.assert_not_called()
        self.assertIn("computer_use", payload)

    def test_voice_read_does_not_project_native_or_agentic_models(self) -> None:
        with self._payload_dependencies(), patch("core.api.settings_api.workspace_hosted_text_status", return_value={"models": []}), patch(
            "core.api.settings_api.workspace_speech_stt_status", return_value={"speech": True}
        ), patch("core.api.settings_api.workspace_provider_status") as providers, patch(
            "core.api.settings_api.workspace_agentic_admin_status"
        ) as agentic:
            payload = platform_settings_payload(self.state, self.context, section="voice")
        providers.assert_not_called()
        agentic.assert_not_called()
        self.assertEqual(payload["provider"]["speech_stt"], {"speech": True})

    def test_invalid_section_is_rejected_before_domain_reads(self) -> None:
        with self.assertRaisesRegex(ValueError, "settings_section_invalid"):
            platform_settings_payload(self.state, self.context, section="unsupported")

    def test_context_route_reports_timings_and_invalid_sections_fail_locally(self) -> None:
        responses = []
        def start_response(status, headers):
            responses.append((status, dict(headers)))
        with self._payload_dependencies(), patch("core.api.settings_api.require_session", return_value=self.context):
            body = handle_settings_api(self.state, {"PATH_INFO": "/api/settings/platform", "QUERY_STRING": "section=context"}, start_response)
            self.assertEqual(json.loads(b"".join(body))["provider"]["active_provider"], None)
            self.assertIn("workspace;dur=", responses[-1][1]["Server-Timing"])
            self.assertEqual(responses[-1][1]["Cache-Control"], "private, no-store")
            handle_settings_api(self.state, {"PATH_INFO": "/api/settings/platform", "QUERY_STRING": "section=invalid"}, start_response)
            self.assertEqual(responses[-1][0], "400 Bad Request")

    def _payload_dependencies(self):
        stack = ExitStack()
        stack.enter_context(patch("core.api.settings_api.public_user_payload", return_value={}))
        stack.enter_context(patch("core.api.settings_api.workspace_payload", return_value={}))
        stack.enter_context(patch("core.api.settings_api.workspace_provider_status", return_value={}))
        stack.enter_context(patch("core.api.settings_api.provider_projection_context", return_value=object()))
        stack.enter_context(patch("core.api.settings_api.recovery_status", return_value={}))
        stack.enter_context(patch("core.api.settings_api.computer_actor_settings", return_value={}))
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
