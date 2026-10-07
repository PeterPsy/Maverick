from types import SimpleNamespace
import queue
import unittest

from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT, DEVICE_USE_PROTOCOL_VERSION, DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.service import DeviceUseService
from core.device_use.turn_authority import reconcile_device_use_login


class DeviceUseTurnAuthorityTest(unittest.TestCase):
    def test_native_lease_retains_the_owner_and_login_fence(self):
        for user, login, expected in (
            ("owner", "login", "bound"),
            ("owner", "new-login", "stopped"),
            ("other-user", "login", "stopped"),
        ):
            with self.subTest(user=user, login=login):
                service = DeviceUseService()
                activation, ticket = service.create_activation(
                    owner_user_id="owner", auth_session_id="login", workspace_id="default",
                    session_generation="generation",
                )
                service.connect_executor(
                    ticket=ticket, protocol_version=DEVICE_USE_PROTOCOL_VERSION,
                    executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
                    tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
                    mode="full", initial_app="com.apple.Safari",
                    approved_apps=["com.apple.Safari"], outbound=queue.Queue(maxsize=8),
                )
                binding = service.binding_snapshot(
                    activation["activation_id"], owner_user_id="owner", workspace_id="default",
                )
                service.bind_session(binding, session_id="chat")
                session = SimpleNamespace(
                    session_id="chat", workspace_id="default", device_use_binding=binding,
                )
                reconcile_device_use_login(
                    service, session=session, owner_user_id=user, auth_session_id=login,
                )
                self.assertEqual(service.public_activation(
                    binding.activation_id, owner_user_id="owner", workspace_id="default",
                )["status"], expected)
                service.stop_activation(binding.activation_id)
                reconcile_device_use_login(
                    service, session=session, owner_user_id=user, auth_session_id=login,
                )
