"""Provider-independent operator routing and native caller authority."""

import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.api.device_use_api import handle_device_use_api
from core.device_use.errors import DeviceUseAuthorizationError, DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult


class ComputerActorApiTests(unittest.TestCase):
    def setUp(self):
        self.binding = SimpleNamespace(activation_id="activation")
        self.session = SimpleNamespace(owner_user_id="owner", workspace_id="default", device_use_binding=self.binding)
        self.service = Mock()
        self.state = SimpleNamespace(device_use_service=self.service, runtime_store=SimpleNamespace(
            get_session=Mock(return_value=self.session),
            get_state=lambda sid: SimpleNamespace(current_turn_id="parent-turn"),
            get_turn=lambda tid: SimpleNamespace(input_text="Original task"),
            get_provider_state=lambda sid: SimpleNamespace(provider_thread_id="parent-thread")))
        self.context = SimpleNamespace(workspace_id="default", user=SimpleNamespace(user_id="owner"),
                                       session=SimpleNamespace(session_id="login"))

    def request(self, tool="computer_interact", *, arguments=None, bearer=False):
        body = json.dumps({"session_id": "parent", "tool": tool, "arguments": arguments or {
            "objective": "Select target", "completion_criterion": "Target selected"}}).encode()
        environ = {"PATH_INFO": "/api/device-use/invoke", "REQUEST_METHOD": "POST",
            "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
        if bearer:
            environ["HTTP_AUTHORIZATION"] = "Bearer fixture"
        responses = []
        with patch("core.api.device_use_api.require_session", return_value=self.context), patch(
            "core.api.device_use_api.device_use_service_for_session", return_value=self.service):
            payload = handle_device_use_api(self.state, environ, lambda status, headers: responses.append(status))
        return responses[0], json.loads(b"".join(payload))

    def test_mcp_route_delegates_under_authenticated_parent_identity(self):
        result = DeviceUseResult("internal", "call", {"success": True, "contentItems": [
            {"type": "inputText", "text": '{"status":"completed"}'}]}, b"jpeg", None, None)
        with patch("core.api.device_use_api.invoke_computer_actor", return_value=result) as invoke:
            status, payload = self.request()
        self.assertEqual(status, "200 OK")
        self.assertEqual(invoke.call_args.args, ("parent",))
        self.assertEqual(invoke.call_args.kwargs["turn_id"], "parent-turn")
        self.assertEqual(invoke.call_args.kwargs["provider_thread_id"], "parent-thread")
        self.assertEqual(payload["image_base64"], "anBlZw==")
        self.service.invoke.assert_not_called()
        self.service.binding_snapshot.assert_called_once_with("activation", owner_user_id="owner",
            workspace_id="default", auth_session_id="login", bound_session_id="parent")

    def test_direct_planner_ui_input_is_rejected_without_dispatch(self):
        status, payload = self.request("mac_browser", arguments={"action": "click"})
        self.assertEqual(status, "403 Forbidden")
        self.assertEqual(payload["error"], "computer_actor_delegation_required")
        self.service.invoke.assert_not_called()

    def test_operator_failure_does_not_revoke_the_parent_lease(self):
        with patch("core.api.device_use_api.invoke_computer_actor",
                   side_effect=DeviceUseUnavailableError("computer_actor_unavailable")):
            status, payload = self.request()
        self.assertEqual(status, "200 OK")
        self.assertTrue(payload["is_error"])
        self.service.stop_activation.assert_not_called()

    def test_cookie_caller_cannot_delegate_another_owner_or_workspace(self):
        for attribute, value in (("owner_user_id", "foreign"), ("workspace_id", "other")):
            with self.subTest(attribute=attribute):
                original = getattr(self.session, attribute)
                setattr(self.session, attribute, value)
                with patch("core.api.device_use_api.invoke_computer_actor") as invoke:
                    status, _ = self.request()
                self.assertEqual(status, "403 Forbidden")
                invoke.assert_not_called()
                setattr(self.session, attribute, original)

    def test_cookie_caller_must_own_the_native_login(self):
        self.service.binding_snapshot.side_effect = DeviceUseAuthorizationError("device_use_activation_forbidden")
        with patch("core.api.device_use_api.invoke_computer_actor") as invoke:
            status, _ = self.request()
        self.assertEqual(status, "403 Forbidden")
        invoke.assert_not_called()

    def test_bearer_identity_overrides_the_body_session(self):
        with patch("core.api.device_use_api.validate_workspace_api_token_lifecycle", return_value=(
            {"runtime_session_id": "token-parent", "workspace_id": "default"}, None)), patch(
            "core.api.device_use_api.invoke_computer_actor", side_effect=DeviceUseUnavailableError("unavailable")) as invoke:
            self.request(bearer=True)
        self.assertEqual(invoke.call_args.args, ("token-parent",))
        self.service.binding_snapshot.assert_not_called()
