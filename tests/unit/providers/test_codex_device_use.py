from __future__ import annotations

import hashlib
import io
import json
import queue
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from core.device_use.contract import DEVICE_USE_TOOL_CONTRACT_DIGEST
from core.device_use.errors import DeviceUseUnavailableError
from core.device_use.runtime_registry import register_device_use_session, unregister_device_use_session
from core.device_use.service import DeviceUseService
from core.providers.codex_app_server_device_use import process_device_use_request
from core.providers.codex_app_server_device_use_requests import stop_device_use_runtime
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime
from core.providers.codex_app_server_runtime_thread_params import codex_thread_params


class CodexDeviceUseTestCase(unittest.TestCase):
    def setUp(self):
        self.service = DeviceUseService()
        activation, ticket = self.service.create_activation(
            owner_user_id="user", auth_session_id="auth", workspace_id="default",
            session_generation="generation",
        )
        self.outbound: queue.Queue = queue.Queue(maxsize=8)
        self.service.connect_executor(
            ticket=ticket, protocol_version="maverick.device-use.v1", executor_contract="macos-v40",
            tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST, initial_app="com.apple.Safari",
            approved_apps=["com.apple.Safari"], outbound=self.outbound,
        )
        self.binding = self.service.binding_snapshot(
            activation["activation_id"], owner_user_id="user", workspace_id="default",
        )
        self.service.bind_session(self.binding, session_id="runtime")
        register_device_use_session("runtime", self.service)

    def tearDown(self):
        unregister_device_use_session("runtime")

    def test_thread_contract_is_ephemeral_read_only_and_dynamic_only(self):
        params = codex_thread_params(
            session=SimpleNamespace(device_use_binding=self.binding),
            launch_spec=SimpleNamespace(working_directory="/private/device-work", execution_mode="sandbox"),
        )
        self.assertTrue(params["ephemeral"])
        self.assertEqual(params["model"], "gpt-6-astra")
        self.assertEqual(params["sandbox"], "read-only")
        self.assertEqual({item["name"] for item in params["dynamicTools"]}, {
            "mac_computer", "mac_peekaboo", "mac_calendar",
        })
        self.assertEqual(params["config"], {"mcp_servers": {}, "project_doc_max_bytes": 0})

    def test_image_is_steered_while_reader_remains_available_then_text_result_returns(self):
        stdin = io.StringIO()
        runtime = _CodexAppServerRuntime(
            session_id="runtime", workspace_id="default", runtime_root="/tmp/runtime",
            process=SimpleNamespace(stdin=stdin, pid=1, poll=lambda: None),
            device_use_binding=self.binding, provider_thread_id="provider-thread",
            current_provider_turn_id="provider-turn", current_runtime_turn_id="runtime-turn",
            current_task_text="Osserva Safari",
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
                "result": {"success": True, "contentItems": [{"type": "inputText", "text": "metadata"}]},
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
        self.assertEqual(steer_input[1]["type"], "image")
        self.assertTrue(steer_input[1]["url"].startswith("data:image/jpeg;base64,"))
        response = json.loads(stdin.getvalue())
        self.assertEqual(response["id"], 7)
        self.assertNotIn("base64", json.dumps(response["result"]))

    def test_provider_exit_revokes_and_unregisters_the_device_lease(self):
        runtime = SimpleNamespace(
            session_id="runtime",
            device_use_binding=self.binding,
        )

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


if __name__ == "__main__":
    unittest.main()
