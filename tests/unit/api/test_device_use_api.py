from __future__ import annotations

import asyncio
import json
import queue
import tempfile
import unittest
from unittest.mock import patch

from core.api.device_use_websocket import stream_device_use_executor
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT,
    DEVICE_USE_PROTOCOL_VERSION,
    DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.service import DeviceUseService
from core.device_use.runtime_registry import unregister_device_use_session
from core.providers.agentic_workspace_admin import configure_workspace_agentic_default
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

    def test_runtime_session_consumes_one_activation_with_the_exact_mono_agent_pin(self) -> None:
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
                model_id="gpt-6-astra",
                model_reasoning_effort="high",
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
                "reasoning_effort": "high",
                "device_use_activation_id": activation["activation_id"],
                "system_prompt": "must be ignored",
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
            self.assertNotIn("device_use_binding", session)
            self.assertEqual(session["execution_binding"]["runtime_engine_id"], "codex")
            self.assertEqual(session["execution_binding"]["model_id"], "gpt-6-astra")
            self.assertEqual(session["execution_binding"]["reasoning_effort"], "high")
            self.assertEqual(session["requested_mode"], "sandbox")
            self.assertEqual(session["system_prompt"], None)
            self.assertEqual(session["skill_ids"], [])
            self.assertEqual(session["skill_activation_mode"], "explicit")

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


class DeviceUseWebSocketTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_redeems_exact_contract_and_disconnects_fail_closed(self) -> None:
        service = DeviceUseService()
        activation, ticket = service.create_activation(
            owner_user_id="user-1",
            auth_session_id="auth-1",
            workspace_id="default",
            session_generation="native-window-1",
        )
        incoming: asyncio.Queue[dict] = asyncio.Queue()
        sent: list[dict] = []
        await incoming.put({"type": "websocket.connect"})
        await incoming.put(
            {
                "type": "websocket.receive",
                "text": json.dumps(
                    {
                        "type": "device_use.hello.v1",
                        "protocol_version": DEVICE_USE_PROTOCOL_VERSION,
                        "executor_contract": DEVICE_USE_EXECUTOR_CONTRACT,
                        "tool_contract_digest": DEVICE_USE_TOOL_CONTRACT_DIGEST,
                        "initial_app": "com.apple.Safari",
                        "approved_apps": ["com.apple.Safari"],
                    }
                ),
            }
        )

        async def receive() -> dict:
            return await incoming.get()

        async def send(message: dict) -> None:
            sent.append(message)

        task = asyncio.create_task(
            stream_device_use_executor(
                service=service,
                scope={
                    "path": "/ws/device-use/executor",
                    "headers": [(b"authorization", f"Bearer {ticket}".encode("latin1"))],
                },
                receive=receive,
                send=send,
            )
        )
        for _ in range(100):
            if any("device_use.ready.v1" in str(item.get("text")) for item in sent):
                break
            await asyncio.sleep(0.01)
        self.assertEqual(sent[0]["type"], "websocket.accept")
        ready = next(
            json.loads(item["text"])
            for item in sent
            if "device_use.ready.v1" in str(item.get("text"))
        )
        self.assertEqual(ready["activation_id"], activation["activation_id"])
        self.assertTrue(ready["ready"])

        await incoming.put({"type": "websocket.disconnect"})
        await asyncio.wait_for(task, timeout=1)
        public = service.public_activation(
            activation["activation_id"],
            owner_user_id="user-1",
            workspace_id="default",
        )
        self.assertEqual(public["status"], "offline")

    async def test_invalid_ticket_is_rejected_before_accept(self) -> None:
        sent: list[dict] = []

        async def receive() -> dict:
            return {"type": "websocket.connect"}

        async def send(message: dict) -> None:
            sent.append(message)

        await stream_device_use_executor(
            service=DeviceUseService(),
            scope={
                "path": "/ws/device-use/executor",
                "headers": [(b"authorization", b"Bearer not-a-ticket")],
            },
            receive=receive,
            send=send,
        )
        self.assertEqual(sent, [{"type": "websocket.close", "code": 4401}])


if __name__ == "__main__":
    unittest.main()
