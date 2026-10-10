"""Native executor WebSocket admission and control-frame limits."""

import asyncio
import json
import unittest

from core.api.device_use_websocket import (
    MAX_DEVICE_CONTROL_FRAME_BYTES, _json_message, stream_device_use_executor,
)
from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT, DEVICE_USE_PROTOCOL_VERSION, DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.service import DeviceUseService


class DeviceUseWebSocketTestCase(unittest.IsolatedAsyncioTestCase):
    def test_control_frame_preserves_worst_case_direct_eventkit_result(self) -> None:
        eventkit_text = '"' * 199_999
        encoded = json.dumps(
            {
                "type": "device_use.result.v1",
                "invocation_id": "invocation-1",
                "call_id": "call-1",
                "arguments_digest": "a" * 64,
                "result": {
                    "success": True,
                    "contentItems": [{"type": "inputText", "text": eventkit_text}],
                },
                "has_image": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertGreater(len(encoded.encode("utf-8")), 400_000)
        self.assertLessEqual(
            len(encoded.encode("utf-8")),
            MAX_DEVICE_CONTROL_FRAME_BYTES,
        )
        self.assertEqual(
            _json_message({"text": encoded})["result"]["contentItems"][0]["text"],
            eventkit_text,
        )
        with self.assertRaises(ValueError):
            _json_message({"text": "x" * (MAX_DEVICE_CONTROL_FRAME_BYTES + 1)})

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
                        "mode": "full",
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
        self.assertEqual(ready["mode"], "full")
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
