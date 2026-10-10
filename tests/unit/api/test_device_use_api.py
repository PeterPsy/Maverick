from __future__ import annotations

import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT,
    DEVICE_USE_PROTOCOL_VERSION,
    DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.runtime_registry import unregister_device_use_session
from core.providers.agentic_workspace_admin import (
    configure_workspace_agentic_default,
    default_actor_selection_policy,
    save_workspace_agentic_binding,
)
from core.providers.antigravity_agentic_profile import publish_antigravity_agentic_profile
from core.providers.native_agent_catalog import NativeAgentCatalogModel
from core.runtime.workspace_api_token import (
    issue_workspace_api_token,
    register_workspace_api_token,
)
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class DeviceUseHttpApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_activation_is_authenticated_one_time_and_revocable(self) -> None:
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
            app = PlatformHost(state, start_path=repo_root)

            unauthenticated_status, _, _ = self._invoke(
                app,
                path="/api/device-use/activations",
                method="POST",
                body={"client_generation": "native-window-1"},
            )
            self.assertEqual(unauthenticated_status, 401)

            cookie = self._login(app)
            status, activation, _ = self._invoke(
                app,
                path="/api/device-use/activations",
                method="POST",
                body={"client_generation": "native-window-1"},
                cookie=cookie,
            )
            self.assertEqual(status, 201)
            self.assertEqual(activation["status"], "awaiting_device")
            self.assertEqual(activation["websocket_path"], "/ws/device-use/executor")
            self.assertGreaterEqual(len(activation["ticket"]), 32)

            status, public, _ = self._invoke(
                app,
                path=f"/api/device-use/activations/{activation['activation_id']}",
                cookie=cookie,
            )
            self.assertEqual(status, 200)
            self.assertNotIn("ticket", public)
            self.assertNotIn("model_id", public)
            self.assertNotIn("reasoning_effort", public)

            status, metrics, _ = self._invoke(
                app,
                path=f"/api/device-use/activations/{activation['activation_id']}/metrics",
                cookie=cookie,
            )
            self.assertEqual(status, 200)
            self.assertEqual(metrics["invocation_count"], 0)

            second_cookie = self._login(app)
            status, forbidden, _ = self._invoke(
                app,
                path=f"/api/device-use/activations/{activation['activation_id']}",
                cookie=second_cookie,
            )
            self.assertEqual(status, 403)
            self.assertEqual(forbidden["error"], "device_use_activation_forbidden")

            status, stopped, _ = self._invoke(
                app,
                path=f"/api/device-use/activations/{activation['activation_id']}",
                method="DELETE",
                body={},
                cookie=cookie,
            )
            self.assertEqual(status, 200)
            self.assertEqual(stopped, {"status": "stopped"})

    def test_runtime_session_consumes_one_activation_with_the_selected_codex_pin(self) -> None:
        self._assert_codex_activation_consumed(source_app_id="chat", agent_id="chat", agent_type_id="", mode="full")

    def test_custom_agent_session_preserves_its_identity_with_full_mac_access(self) -> None:
        self._assert_codex_activation_consumed(
            source_app_id="agents", agent_id="Video Editor", agent_type_id="video-editor", mode="full",
        )

    def _assert_codex_activation_consumed(
        self, *, source_app_id: str, agent_id: str, agent_type_id: str, mode: str,
    ) -> None:
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
            binding = configure_workspace_agentic_default(
                state.provider_store,
                state.provider_registry,
                workspace_id="default",
                provider_id="codex",
                model_id="gpt-5.6-sol",
                model_reasoning_effort="max",
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            status, activation, _ = self._invoke(
                app,
                path="/api/device-use/activations",
                method="POST",
                body={"client_generation": "native-window-1"},
                cookie=cookie,
            )
            self.assertEqual(status, 201)
            state.device_use_service.connect_executor(
                ticket=activation["ticket"],
                protocol_version=DEVICE_USE_PROTOCOL_VERSION,
                executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
                tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
                mode=mode,
                initial_app="com.apple.Safari",
                approved_apps=["com.apple.Safari"],
                outbound=queue.Queue(maxsize=8),
            )
            request = {
                "agent_id": agent_id,
                "agent_type_id": agent_type_id,
                "source_app_id": source_app_id,
                "runtime_mode": "agentic",
                "requested_mode": "full-access",
                "workspace_profile_binding_id": binding.binding_id,
                "reasoning_effort": "max",
                "device_use_activation_id": activation["activation_id"],
                "system_prompt": "Use Maverick app surfaces and the Mac",
                "skill_activation_mode": "implicit",
                "project_id": "mac-project",
            }
            with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
                status, session, _ = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=request,
                    cookie=cookie,
                )
            self.assertEqual(status, 201)
            self.assertTrue(session["device_use_enabled"])
            self.assertEqual(session["device_use"]["mode"], mode)
            self.assertEqual(session["agent_id"], agent_id)
            self.assertEqual(session["agent_type_id"], agent_type_id)
            self.assertEqual(session["source_app_id"], source_app_id)
            self.assertNotIn("device_use_binding", session)
            self.assertEqual(session["execution_binding"]["runtime_engine_id"], "codex")
            self.assertEqual(session["execution_binding"]["model_id"], "gpt-5.6-sol")
            self.assertEqual(session["execution_binding"]["reasoning_effort"], "max")
            self.assertEqual(session["requested_mode"], "full-access")
            self.assertEqual(session["effective_mode"], "full-access")
            self.assertEqual(session["system_prompt"], "Use Maverick app surfaces and the Mac")
            self.assertEqual(session["skill_ids"], [])
            self.assertEqual(session["skill_activation_mode"], "implicit")
            self.assertEqual(session["project_id"], "mac-project")

            before = state.runtime_store.list_all_sessions()
            with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
                status, duplicate, _ = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body=request,
                    cookie=cookie,
                )
            self.assertEqual(status, 409)
            self.assertEqual(duplicate["error"], "device_use_activation_already_bound")
            self.assertEqual(state.runtime_store.list_all_sessions(), before)
            public = state.device_use_service.public_activation(
                activation["activation_id"],
                owner_user_id="user:admin",
                workspace_id="default",
            )
            self.assertEqual(public["status"], "bound")
            unregister_device_use_session(session["session_id"])
            state.device_use_service.stop_activation(
                activation["activation_id"],
                reason="test_complete",
            )

    def test_runtime_session_consumes_activation_with_antigravity_cli_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                    "MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME": "1",
                    "MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW": "1",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
                installation = state.provider_registry.get_native_agent_installation("antigravity-cli")
                self.assertIsNotNone(installation)
                profile = publish_antigravity_agentic_profile(
                    state.provider_store,
                    installation=installation,
                    model=NativeAgentCatalogModel(
                        model_provider_id="google",
                        model_id="gemini-3.8-flash-high",
                        model_revision=None,
                        revision_policy="provider_alias",
                        reasoning_efforts=("low", "medium", "high"),
                        default_reasoning_effort="high",
                    ),
                )
                binding = save_workspace_agentic_binding(
                    state.provider_store,
                    state.provider_registry,
                    workspace_id="default",
                    definition_id=profile.definition_id,
                    credential_binding_id=None,
                    enabled=True,
                    is_default=True,
                    actor_policy=default_actor_selection_policy(),
                    policy_patch={},
                )
                app = PlatformHost(state, start_path=repo_root)
                cookie = self._login(app)
                status, activation, _ = self._invoke(
                    app,
                    path="/api/device-use/activations",
                    method="POST",
                    body={"client_generation": "native-window-cli-1"},
                    cookie=cookie,
                )
                self.assertEqual(status, 201)
                state.device_use_service.connect_executor(
                    ticket=activation["ticket"],
                    protocol_version=DEVICE_USE_PROTOCOL_VERSION,
                    executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
                    tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
                    mode="full",
                    initial_app="com.apple.Safari",
                    approved_apps=["com.apple.Safari"],
                    outbound=queue.Queue(maxsize=8),
                )
                request = {
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "agentic",
                    "requested_mode": "sandbox",
                    "workspace_profile_binding_id": binding.binding_id,
                    "device_use_activation_id": activation["activation_id"],
                }
                with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
                    status, session, _ = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body=request,
                        cookie=cookie,
                    )
                self.assertEqual(status, 201)
                self.assertTrue(session["device_use_enabled"])
                self.assertEqual(session["execution_binding"]["runtime_engine_id"], "antigravity-cli")
                self.assertEqual(session["execution_binding"]["model_id"], "gemini-3.8-flash-high")
                unregister_device_use_session(session["session_id"])
                state.device_use_service.stop_activation(
                    activation["activation_id"],
                    reason="test_complete",
                )

    def test_device_use_tools_and_invoke_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                    "MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME": "1",
                    "MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW": "1",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
                installation = state.provider_registry.get_native_agent_installation("antigravity-cli")
                self.assertIsNotNone(installation)
                profile = publish_antigravity_agentic_profile(
                    state.provider_store,
                    installation=installation,
                    model=NativeAgentCatalogModel(
                        model_provider_id="google",
                        model_id="gemini-3.8-flash-high",
                        model_revision=None,
                        revision_policy="provider_alias",
                        reasoning_efforts=("low", "medium", "high"),
                        default_reasoning_effort="high",
                    ),
                )
                binding = save_workspace_agentic_binding(
                    state.provider_store,
                    state.provider_registry,
                    workspace_id="default",
                    definition_id=profile.definition_id,
                    credential_binding_id=None,
                    enabled=True,
                    is_default=True,
                    actor_policy=default_actor_selection_policy(),
                    policy_patch={},
                )
                app = PlatformHost(state, start_path=repo_root)
                cookie = self._login(app)
                status, activation, _ = self._invoke(
                    app,
                    path="/api/device-use/activations",
                    method="POST",
                    body={"client_generation": "native-window-tools-1"},
                    cookie=cookie,
                )
                self.assertEqual(status, 201)
                outbound: queue.Queue = queue.Queue(maxsize=8)
                state.device_use_service.connect_executor(
                    ticket=activation["ticket"],
                    protocol_version=DEVICE_USE_PROTOCOL_VERSION,
                    executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
                    tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
                    mode="full",
                    initial_app="com.apple.Safari",
                    approved_apps=["com.apple.Safari"],
                    outbound=outbound,
                )
                with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
                    status, session, _ = self._invoke(
                        app,
                        path="/api/runtime/sessions",
                        method="POST",
                        body={
                            "agent_id": "chat",
                            "source_app_id": "chat",
                            "runtime_mode": "agentic",
                            "requested_mode": "sandbox",
                            "workspace_profile_binding_id": binding.binding_id,
                            "device_use_activation_id": activation["activation_id"],
                        },
                        cookie=cookie,
                    )
                self.assertEqual(status, 201)
                token = issue_workspace_api_token(
                    workspace_id="default",
                    runtime_session_id=session["session_id"],
                    effective_mode="sandbox",
                )
                register_workspace_api_token(state.runtime_store, token)

                # Test GET /api/device-use/tools
                status, tools_resp, _ = self._invoke(
                    app,
                    path="/api/device-use/tools",
                    auth_token=token,
                )
                self.assertEqual(status, 200)
                tool_names = [t["name"] for t in tools_resp["tools"]]
                self.assertIn("mac_computer", tool_names)
                self.assertIn("mac_peekaboo", tool_names)
                self.assertIn("mac_calendar", tool_names)
                self.assertIn("mac_project", tool_names)

                # Test POST /api/device-use/invoke
                invoke_res = []

                def invoke_client():
                    status, res, _ = self._invoke(
                        app,
                        path="/api/device-use/invoke",
                        method="POST",
                        body={
                            "tool": "mac_peekaboo",
                            "arguments": {"action": "list_windows"},
                        },
                        auth_token=token,
                    )
                    invoke_res.append((status, res))

                thread = threading.Thread(target=invoke_client)
                thread.start()
                frame = outbound.get(timeout=2)
                self.assertEqual(frame["tool"], "mac_peekaboo")
                state.device_use_service.accept_invocation(activation["activation_id"], frame)
                state.device_use_service.deliver_result(
                    activation["activation_id"],
                    {
                        "invocation_id": frame["invocation_id"],
                        "call_id": frame["call_id"],
                        "arguments_digest": frame["arguments_digest"],
                        "result": {
                            "success": True,
                            "contentItems": [{"type": "inputText", "text": "windows: [1]"}],
                        },
                    },
                )
                thread.join(timeout=2)
                self.assertEqual(len(invoke_res), 1)
                self.assertEqual(invoke_res[0][0], 200)
                self.assertEqual(invoke_res[0][1]["result"]["contentItems"][0]["text"], "windows: [1]")
                self.assertFalse(invoke_res[0][1]["is_error"])

                # Test POST /api/device-use/end-turn
                status, end_turn_res, _ = self._invoke(
                    app,
                    path="/api/device-use/end-turn",
                    method="POST",
                    body={},
                    auth_token=token,
                )
                self.assertEqual(status, 200)
                self.assertEqual(end_turn_res, {"status": "ok"})

                unregister_device_use_session(session["session_id"])
                state.device_use_service.stop_activation(
                    activation["activation_id"],
                    reason="test_complete",
                )


if __name__ == "__main__":
    unittest.main()
