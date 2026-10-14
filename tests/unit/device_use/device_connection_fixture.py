"""DeviceConnectionFixture fixtures extracted without changing assertions."""

from __future__ import annotations
import queue
from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT,
    DEVICE_USE_PROTOCOL_VERSION,
    DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.service import DeviceUseService


class DeviceConnectionFixture:
    def connected(self, *, mode="full"):
        service = DeviceUseService()
        activation, ticket = service.create_activation(
            owner_user_id="user-1",
            auth_session_id="auth-1",
            workspace_id="default",
            session_generation="generation-1",
        )
        outbound: queue.Queue = queue.Queue(maxsize=8)
        service.connect_executor(
            ticket=ticket,
            protocol_version=DEVICE_USE_PROTOCOL_VERSION,
            executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
            tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
            mode=mode,
            initial_app="com.apple.Safari",
            approved_apps=["com.apple.Safari"],
            outbound=outbound,
        )
        binding = service.binding_snapshot(
            activation["activation_id"],
            owner_user_id="user-1",
            workspace_id="default",
        )
        service.bind_session(binding, session_id="runtime-1")
        return service, binding, outbound

    @staticmethod
    def _capture_error(target, action):
        try: action()
        except Exception as error: target.append(error)
