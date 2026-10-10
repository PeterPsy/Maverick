from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
import queue
from types import SimpleNamespace
import threading
import tomllib
import tempfile
import unittest
from unittest.mock import patch

from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT,
    DEVICE_USE_TOOL_CONTRACT_DIGEST,
    device_use_instructions,
)
from core.device_use.errors import DeviceUseUnavailableError
from core.device_use.runtime_registry import (
    device_use_service_for_session, register_device_use_session, unregister_device_use_session,
)
from core.device_use.service import DeviceUseService
from core.providers.codex_app_server_device_use import process_device_use_request
from core.providers.codex_app_server_device_use_turn import codex_turn_input, codex_turn_start_params
from core.providers.codex_app_server_device_use_requests import dispatch_server_request, stop_device_use_runtime
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.providers.codex_app_server_runtime_thread_params import codex_thread_params
from core.providers.errors import ProviderLaunchError
from core.providers.provider_codex import CodexProviderAdapter


class CodexDeviceUseTestCase(unittest.TestCase):
    def setUp(self):
        self.service = DeviceUseService()
        activation, ticket = self.service.create_activation(
            owner_user_id="user", auth_session_id="auth", workspace_id="default",
            session_generation="generation",
        )
        self.outbound: queue.Queue = queue.Queue(maxsize=8)
        self.service.connect_executor(
            ticket=ticket, protocol_version="maverick.device-use.v1", executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
            tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST, mode="on", initial_app="com.apple.Safari",
            approved_apps=["com.apple.Safari"], outbound=self.outbound,
        )
        self.binding = self.service.binding_snapshot(
            activation["activation_id"], owner_user_id="user", workspace_id="default",
        )
        self.service.bind_session(self.binding, session_id="runtime")
        register_device_use_session("runtime", self.service, activation_id=self.binding.activation_id)

    def tearDown(self):
        unregister_device_use_session("runtime")

    def test_mac_tools_extend_the_ordinary_workspace_thread(self):
        params = codex_thread_params(
            session=SimpleNamespace(
                device_use_binding=self.binding,
                execution_binding=SimpleNamespace(model_id="gpt-5.6-sol"),
                system_prompt="Use the official Maverick app surfaces.",
                skill_activation_mode="implicit",
            ),
            launch_spec=SimpleNamespace(working_directory="/workspace", execution_mode="full-access"),
        )
        self.assertFalse(params["ephemeral"])
        self.assertEqual(params["model"], "gpt-5.6-sol")
        self.assertEqual(params["sandbox"], "danger-full-access")
        self.assertEqual({item["name"] for item in params["dynamicTools"]}, {
            "mac_computer", "mac_peekaboo", "mac_calendar", "mac_project", "mac_browser", "mac_code",
            "computer_interact",
        })
        self.assertEqual(params["config"], {
            "mcp_servers": {}, "features": {"code_mode_host": True, "code_mode": False},
        })
        self.assertEqual(params["cwd"], "/workspace")
        self.assertIn("Use the official Maverick app surfaces.", params["developerInstructions"])
        self.assertIn("additional capability", params["developerInstructions"])
        self.assertNotIn("baseInstructions", params)

    def test_full_mode_instructions_remove_native_authority_limits(self):
        params = codex_thread_params(
            session=SimpleNamespace(
                device_use_binding=replace(self.binding, mode="full"),
                execution_binding=SimpleNamespace(model_id="gpt-5.6-terra"),
            ),
            launch_spec=SimpleNamespace(working_directory="/private/device-work", execution_mode="sandbox"),
        )
        instructions = params["developerInstructions"]
        self.assertIn("There is no application allowlist", instructions)
        self.assertIn("Only an explicit Stop or a positively detected screen lock", instructions)
        self.assertIn("inspect the source project/view", instructions)
        self.assertIn("brief intermediate updates", instructions)
        self.assertIn("opaque project_id", instructions)
        self.assertIn("not source code or a shell", instructions)
        self.assertNotIn("Never operate credential or security UI", instructions)

    def test_scoped_mode_requires_source_app_grounding_and_milestone_updates(self):
        instructions = device_use_instructions(
            mode="on",
            approved_apps=("com.apple.Safari",),
            initial_app="com.apple.Safari",
        )

        self.assertIn("Inspect the source project/view", instructions)
        self.assertIn("brief intermediate updates", instructions)
        self.assertNotIn("Do not narrate intermediate tool progress", instructions)

    def test_turn_uses_the_reasoning_effort_pinned_to_the_session(self):
        params = codex_turn_start_params(
            device_use=True,
            research=False,
            provider_thread_id="provider-thread",
            turn_input=[{"type": "text", "text": "Observe"}],
            reasoning_effort="max",
            launch_spec=SimpleNamespace(working_directory="/workspace"),
            sandbox_policy=lambda _spec: {"type": "dangerFullAccess"},
        )

        self.assertEqual(params["effort"], "max")
        self.assertEqual(params["sandboxPolicy"], {"type": "dangerFullAccess"})
        self.assertEqual(params["cwd"], "/workspace")

    def test_mac_turn_preserves_workspace_input_and_invoked_skills(self):
        session = SimpleNamespace(device_use_binding=self.binding, skill_activation_mode="implicit")
        runtime = SimpleNamespace(runtime_root="/runtime", runtime_home="/runtime/home")
        skills = [object()]
        with patch("core.providers.codex_app_server_device_use_turn.codex_provider_input_text", return_value="Workspace request") as wrap, patch("core.providers.codex_app_server_device_use_turn.codex_skill_input_items", return_value=[{"type": "skill", "name": "Storage"}]) as project:
            device, research, items = codex_turn_input(session, runtime, "Use Storage and the Mac", skills)
        self.assertTrue(device)
        self.assertFalse(research)
        self.assertEqual(items, [{"type": "text", "text": "Workspace request"}, {"type": "skill", "name": "Storage"}])
        wrap.assert_called_once_with("Use Storage and the Mac", skill_activation_mode="implicit")
        project.assert_called_once_with(runtime.runtime_root, skills, runtime_home=runtime.runtime_home)

    def test_workspace_server_requests_keep_the_normal_handler(self):
        runtime = SimpleNamespace(device_use_binding=self.binding, server_request_queue=queue.Queue())
        normal = {"id": 1, "method": "item/commandExecution/requestApproval", "params": {}}
        native = {"id": 2, "method": "item/tool/call", "params": {"tool": "mac_computer"}}
        with patch(__name__ + ".process_device_use_request") as fallback:
            dispatch_server_request(runtime, normal, fallback)
            dispatch_server_request(runtime, native, fallback)
            fallback.assert_called_once_with(runtime, normal)
        self.assertEqual(runtime.server_request_queue.get_nowait(), native)

    def test_mac_runtime_preserves_normal_config_and_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "config.toml").write_text("[features]\nshell_tool = true\nunified_exec = true\nmulti_agent = true\ncode_mode_host = true\n")
            (source / "rules").mkdir()
            (source / "rules" / "workspace.rules").write_text("Workspace rules")
            home = root / "runtime" / "codex-home"
            session = SimpleNamespace(device_use_binding=self.binding, workspace_root=str(root), runtime_root=str(home.parent), effective_mode="sandbox", skill_activation_mode="implicit")
            adapter = CodexProviderAdapter()
            with patch.object(adapter, "_source_codex_home", return_value=source), patch.object(adapter, "_runtime_home", return_value=home):
                adapter._prepare_runtime_home(session)
            config = tomllib.loads((home / "config.toml").read_text())
            for name in ("shell_tool", "unified_exec", "multi_agent"):
                self.assertIsNot(config["features"].get(name), False)
            self.assertEqual((home / "rules" / "workspace.rules").read_text(), "Workspace rules")
            self.assertIn("shell_environment_policy", config)

    def test_device_runtime_mounts_the_bundled_code_mode_host(self):
            self.assertFalse(config["features"]["unified_exec"])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vendor_bin = root / "vendor" / "target" / "bin"
            vendor_bin.mkdir(parents=True)
            codex = vendor_bin / "codex"
            code_mode_host = vendor_bin / "codex-code-mode-host"
            codex.touch()
            code_mode_host.touch()
            runtime_root = root / "runtime"

            command = CodexProviderAdapter()._build_command(
                workspace_root=root,
                runtime_root=runtime_root,
                runtime_home=runtime_root / "codex-home",
                execution_mode="sandbox",
                host_command=str(codex),
                require_code_mode_host=True,
            )
            standard_command = CodexProviderAdapter()._build_command(
                workspace_root=root,
                runtime_root=runtime_root,
                runtime_home=runtime_root / "codex-home",
                execution_mode="sandbox",
                host_command=str(codex),
            )

        self.assertIn(
            f"{code_mode_host}={runtime_root / 'bin' / code_mode_host.name}",
            command,
        )
        self.assertNotIn(str(code_mode_host), standard_command)

    def test_device_runtime_fails_closed_without_the_bundled_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vendor_bin = root / "vendor" / "target" / "bin"
            vendor_bin.mkdir(parents=True)
            codex = vendor_bin / "codex"
            codex.touch()

            with self.assertRaisesRegex(
                ProviderLaunchError,
                "codex_device_use_code_mode_host_missing",
            ):
                CodexProviderAdapter()._build_command(
                    workspace_root=root,
                    runtime_root=root / "runtime",
                    runtime_home=root / "runtime" / "codex-home",
                    execution_mode="sandbox",
                    host_command=str(codex),
                    require_code_mode_host=True,
                )

    def test_image_is_steered_while_reader_remains_available_then_text_result_returns(self):
        stdin = io.StringIO()
        events = []
        runtime = _CodexAppServerRuntime(
            session_id="runtime", workspace_id="default", runtime_root="/tmp/runtime",
            process=SimpleNamespace(stdin=stdin, pid=1, poll=lambda: None),
            device_use_binding=self.binding, provider_thread_id="provider-thread",
            current_provider_turn_id="provider-turn", current_runtime_turn_id="runtime-turn",
            current_task_text="Osserva Safari", current_event_sink=events.append,
        )
        payload = {"id": 7, "method": "item/tool/call", "params": {
            "threadId": "provider-thread", "turnId": "provider-turn", "callId": "call",
            "tool": "mac_computer", "arguments": {"action": "observe"},
        }}
        with patch("core.providers.codex_app_server_device_use._send_request", return_value={"turnId": "provider-turn"}) as steer:
            worker = threading.Thread(target=process_device_use_request, args=(runtime, payload))
            worker.start()
            frame = self.outbound.get(timeout=1)
            jpeg = b"\xff\xd8image\xff\xd9"
            self.service.accept_invocation(self.binding.activation_id, frame)
            self.service.deliver_result(self.binding.activation_id, {
                "invocation_id": frame["invocation_id"], "call_id": "call",
                "arguments_digest": frame["arguments_digest"],
                "result": {"success": True, "contentItems": [{"type": "inputText", "text": "PRIVATE_DYNAMIC_METADATA"}]},
                "has_image": True, "image_sha256": hashlib.sha256(jpeg).hexdigest(),
            })
            # Use the service encoder so identity fields and framing remain exact.
            from core.device_use.service import encode_image_frame
            self.service.deliver_image(self.binding.activation_id, encode_image_frame(
                invocation_id=frame["invocation_id"], call_id="call", jpeg=jpeg,
            ))
            worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        steer_input = steer.call_args.args[2]["input"]
        self.assertNotIn("PRIVATE_DYNAMIC_METADATA", steer_input[0]["text"])
        self.assertIn("call", steer_input[0]["text"])
        self.assertEqual(steer_input[1]["type"], "image")
        self.assertTrue(steer_input[1]["url"].startswith("data:image/jpeg;base64,"))
        response = json.loads(stdin.getvalue())
        self.assertEqual(response["id"], 7)
        self.assertEqual(
            response["result"]["contentItems"][0]["text"],
            "PRIVATE_DYNAMIC_METADATA",
        )
        self.assertNotIn("base64", json.dumps(response["result"]))
        self.assertEqual(
            [event.event_type for event in events],
            ["runtime.tool_call.started", "runtime.tool_call.completed"],
        )
        self.assertEqual(events[0].payload["tool_call_id"], "call")
        self.assertEqual(events[1].payload["status"], "completed")
        self.assertGreaterEqual(events[1].payload["provider_observation_delivery_ms"], 0)
        self.assertEqual(events[1].payload["result_text_char_count"], len("PRIVATE_DYNAMIC_METADATA"))
        self.assertNotIn("PRIVATE_DYNAMIC_METADATA", json.dumps([event.payload for event in events]))

    def test_failed_device_request_emits_a_visible_redacted_tool_lifecycle(self):
        stdin = io.StringIO()
        events = []
        runtime = _CodexAppServerRuntime(
            session_id="runtime", workspace_id="default", runtime_root="/tmp/runtime",
            process=SimpleNamespace(stdin=stdin, pid=1, poll=lambda: None),
            device_use_binding=self.binding, provider_thread_id="provider-thread",
            current_provider_turn_id="provider-turn", current_runtime_turn_id="runtime-turn",
            current_task_text="Osserva Safari", current_event_sink=events.append,
        )

        process_device_use_request(runtime, {
            "id": 8,
            "method": "item/tool/call",
            "params": {
                "threadId": "provider-thread",
                "turnId": "provider-turn",
                "callId": "bad-call",
                "tool": "not_a_device_tool",
                "arguments": {"action": "observe", "private": "do not expose"},
            },
        })

        response = json.loads(stdin.getvalue())
        self.assertFalse(response["result"]["success"])
        self.assertEqual(
            [event.event_type for event in events],
            ["runtime.tool_call.started", "runtime.tool_call.failed"],
        )
        self.assertEqual(events[1].payload["failure_reason_code"], "device_use_tool_not_allowed")
        self.assertNotIn("do not expose", json.dumps([event.payload for event in events]))

    def test_native_tool_failure_is_projected_as_failed_not_completed(self):
        stdin = io.StringIO()
        events = []
        runtime = _CodexAppServerRuntime(
            session_id="runtime", workspace_id="default", runtime_root="/tmp/runtime",
            process=SimpleNamespace(stdin=stdin, pid=1, poll=lambda: None),
            device_use_binding=self.binding, provider_thread_id="provider-thread",
            current_provider_turn_id="provider-turn", current_runtime_turn_id="runtime-turn",
            current_task_text="Osserva Safari", current_event_sink=events.append,
        )
        failed_result = SimpleNamespace(
            result={
                "success": False,
                "contentItems": [{"type": "inputText", "text": "PRIVATE_NATIVE_FAILURE"}],
            },
            image_jpeg=None,
            native_duration_ms=12.0, native_user_wait_ms=0.0,
        )

        with patch(
            "core.providers.codex_app_server_device_use.device_use_service_for_session",
            return_value=SimpleNamespace(invoke=lambda **_kwargs: failed_result),
        ):
            process_device_use_request(runtime, {
                "id": 9,
                "method": "item/tool/call",
                "params": {
                    "threadId": "provider-thread",
                    "turnId": "provider-turn",
                    "callId": "failed-call",
                    "tool": "mac_computer",
                    "arguments": {"action": "observe"},
                },
            })

        self.assertEqual(
            [event.event_type for event in events],
            ["runtime.tool_call.started", "runtime.tool_call.failed"],
        )
        self.assertNotIn("PRIVATE_NATIVE_FAILURE", json.dumps([event.payload for event in events]))
        self.assertEqual(events[1].payload["provider_observation_delivery_ms"], 0)

    def test_planner_ui_input_requires_internal_delegation_before_dispatch(self):
        stdin = io.StringIO()
        events = []
        runtime = _CodexAppServerRuntime(
            session_id="runtime", workspace_id="default", runtime_root="/tmp/runtime",
            process=SimpleNamespace(stdin=stdin, pid=1, poll=lambda: None),
            device_use_binding=self.binding, provider_thread_id="provider-thread",
            current_provider_turn_id="provider-turn", current_runtime_turn_id="runtime-turn",
            current_task_text="Select a target", current_event_sink=events.append)
        process_device_use_request(runtime, {"id": 10, "method": "item/tool/call", "params": {
            "threadId": "provider-thread", "turnId": "provider-turn", "callId": "call",
            "tool": "mac_peekaboo", "arguments": {"action": "click", "snapshot": "old"}}})
        self.assertFalse(json.loads(stdin.getvalue())["result"]["success"])
        self.assertTrue(self.outbound.empty())
        self.assertEqual(events[-1].payload["failure_reason_code"], "computer_actor_delegation_required")

    def _exit_runtime(self, *, active=False, completed=False):
        return _CodexAppServerRuntime(
            session_id="runtime", workspace_id="default", runtime_root="/tmp/runtime",
            process=SimpleNamespace(), device_use_binding=self.binding,
            current_event_sink=(lambda _event: None) if active else None,
            current_completion_received=completed,
        )

    def test_idle_provider_exit_preserves_the_device_lease(self):
        stop_device_use_runtime(self._exit_runtime(), reason="device_use_provider_process_ended")
        self.assertEqual(self.service.binding_snapshot(
            self.binding.activation_id, owner_user_id="user", workspace_id="default",
            bound_session_id="runtime",
        ), self.binding)
        self.assertIs(device_use_service_for_session("runtime"), self.service)
        self.assertTrue(self.outbound.empty())

    def test_provider_exit_after_completion_preserves_the_device_lease(self):
        stop_device_use_runtime(
            self._exit_runtime(active=True, completed=True), reason="device_use_provider_process_ended",
        )
        self.assertTrue(self.service.public_activation(
            self.binding.activation_id, owner_user_id="user", workspace_id="default",
        )["ready"])
        self.assertIs(device_use_service_for_session("runtime"), self.service)

    def test_unfinished_provider_exit_revokes_and_unregisters_the_device_lease(self):
        runtime = self._exit_runtime(active=True)

        stop_device_use_runtime(runtime, reason="device_use_provider_process_ended")

        with self.assertRaisesRegex(
            DeviceUseUnavailableError,
            "device_use_executor_not_ready",
        ):
            self.service.binding_snapshot(
                self.binding.activation_id,
                owner_user_id="user",
                workspace_id="default",
                bound_session_id="runtime",
            )
        # A second stop is deliberately idempotent after registry removal.
        stop_device_use_runtime(runtime, reason="device_use_provider_process_ended")
        self.assertIsNone(device_use_service_for_session("runtime"))

    def test_delayed_provider_exit_does_not_unregister_a_reconnected_lease(self):
        register_device_use_session("runtime", self.service, activation_id="new-activation")
        stop_device_use_runtime(self._exit_runtime(active=True), reason="device_use_provider_process_ended")
        self.assertIs(device_use_service_for_session("runtime"), self.service)


if __name__ == "__main__":
    unittest.main()
