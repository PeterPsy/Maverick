from __future__ import annotations

import hashlib
import queue
import threading
import unittest
from datetime import UTC, datetime, timedelta

from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT,
    DEVICE_USE_PROTOCOL_VERSION,
    DEVICE_USE_TOOL_CONTRACT_DIGEST,
)
from core.device_use.errors import (
    DeviceUseAuthorizationError,
    DeviceUseUnavailableError,
)
from core.device_use.models import device_use_binding_from_document
from core.device_use.service import DeviceUseService, encode_image_frame


class DeviceUseServiceTestCase(unittest.TestCase):
    def test_contract_digest_is_the_frozen_macos_v43_digest(self):
        self.assertEqual(
            DEVICE_USE_TOOL_CONTRACT_DIGEST,
            "d525d61fc31a5d873b189166be26d90bd613dc1e2e430f69a07744d920ea4dd1",
        )

    def test_persisted_binding_requires_mode_and_full_does_not_treat_discovery_as_scope(self):
        document = {
            "activation_id": "activation-1",
            "workspace_id": "default",
            "owner_user_id": "user-1",
            "protocol_version": DEVICE_USE_PROTOCOL_VERSION,
            "executor_contract": DEVICE_USE_EXECUTOR_CONTRACT,
            "tool_contract_digest": DEVICE_USE_TOOL_CONTRACT_DIGEST,
            "mode": "full",
            "initial_app": "com.example.NewApp",
            "approved_apps": ["com.apple.Safari"],
            "created_at": datetime(2026, 9, 14, tzinfo=UTC),
        }
        binding = device_use_binding_from_document(document)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.mode, "full")
        with self.assertRaisesRegex(ValueError, "mode"):
            device_use_binding_from_document({key: value for key, value in document.items() if key != "mode"})
        with self.assertRaisesRegex(ValueError, "initial app"):
            device_use_binding_from_document({**document, "mode": "on"})

    def connected(self):
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
            mode="on",
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

    def test_full_mode_has_no_app_catalog_or_request_count_ceiling(self):
        service = DeviceUseService()
        activation, ticket = service.create_activation(
            owner_user_id="user-1",
            auth_session_id="auth-1",
            workspace_id="default",
            session_generation="generation-1",
        )
        outbound: queue.Queue = queue.Queue(maxsize=8)
        apps = [f"com.example.App{index}" for index in range(40)]
        public = service.connect_executor(
            ticket=ticket,
            protocol_version=DEVICE_USE_PROTOCOL_VERSION,
            executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
            tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
            mode="full",
            initial_app=apps[0],
            approved_apps=apps,
            outbound=outbound,
        )
        binding = service.binding_snapshot(
            activation["activation_id"],
            owner_user_id="user-1",
            workspace_id="default",
        )
        service.bind_session(binding, session_id="runtime-full")
        self.assertEqual(public["mode"], "full")
        self.assertEqual(binding.mode, "full")
        self.assertEqual(len(binding.approved_apps), 40)
        service._seen_calls[(binding.activation_id, "turn-full")] = {
            f"previous-{index}" for index in range(512)
        }
        errors = []
        worker = threading.Thread(target=lambda: self._capture_error(errors, lambda: service.invoke(
            binding=binding,
            runtime_session_id="runtime-full",
            turn_id="turn-full",
            provider_thread_id="provider-thread",
            provider_turn_id="provider-turn",
            call_id="call-513",
            tool_name="mac_computer",
            arguments={"action": "observe"},
            task_text="continue",
            timeout_seconds=1,
        )))
        worker.start()
        self.assertEqual(outbound.get(timeout=1)["call_id"], "call-513")
        service.disconnect_executor(binding.activation_id)
        worker.join(timeout=1)
        self.assertEqual(str(errors[0]), "device_use_execution_unknown")

    def test_invocation_pairs_text_and_binary_image_without_replay(self):
        service, binding, outbound = self.connected()
        result_holder = []

        def invoke():
            result_holder.append(service.invoke(
                binding=binding,
                runtime_session_id="runtime-1",
                turn_id="turn-1",
                provider_thread_id="provider-thread",
                provider_turn_id="provider-turn",
                call_id="call-1",
                tool_name="mac_computer",
                arguments={"action": "observe"},
                task_text="Osserva Safari",
                timeout_seconds=1,
            ))

        worker = threading.Thread(target=invoke)
        worker.start()
        frame = outbound.get(timeout=1)
        self.assertNotIn("arguments", frame)
        self.assertEqual(frame["arguments_json"], '{"action":"observe"}')
        self.assertEqual(
            frame["arguments_digest"],
            hashlib.sha256(frame["arguments_json"].encode("utf-8")).hexdigest(),
        )
        jpeg = b"\xff\xd8device-use\xff\xd9"
        service.accept_invocation(binding.activation_id, frame)
        with self.assertRaises(DeviceUseAuthorizationError):
            service.accept_invocation(binding.activation_id, frame)
        service.deliver_result(binding.activation_id, {
            "invocation_id": frame["invocation_id"],
            "call_id": "call-1",
            "arguments_digest": frame["arguments_digest"],
            "result": {"success": True, "contentItems": [{"type": "inputText", "text": "metadata"}]},
            "has_image": True,
            "image_sha256": hashlib.sha256(jpeg).hexdigest(),
            "native_duration_ms": 12,
        })
        service.deliver_image(binding.activation_id, encode_image_frame(
            invocation_id=frame["invocation_id"], call_id="call-1", jpeg=jpeg,
        ))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result_holder[0].image_jpeg, jpeg)
        self.assertEqual(service.journal(runtime_session_id="runtime-1")[-1].status, "completed")
        metrics = service.activation_metrics(
            binding.activation_id,
            owner_user_id="user-1",
            workspace_id="default",
        )
        self.assertEqual(metrics["completed_count"], 1)
        self.assertEqual(metrics["execution_unknown_count"], 0)
        self.assertEqual(metrics["invocations"][0]["image_bytes"], len(jpeg))
        self.assertEqual(metrics["invocations"][0]["native_duration_ms"], 12.0)
        self.assertIsNotNone(metrics["invocations"][0]["bridge_end_to_end_ms"])
        self.assertEqual(metrics["summary"]["tool_counts"], {"mac_computer": 1})
        self.assertEqual(metrics["summary"]["action_counts"], {"mac_computer.observe": 1})
        self.assertEqual(metrics["summary"]["image_count"], 1)
        self.assertEqual(metrics["summary"]["image_bytes"], len(jpeg))
        self.assertEqual(metrics["summary"]["native_duration_ms"]["count"], 1)
        service.end_turn(
            binding,
            runtime_session_id="runtime-1",
            turn_id="turn-1",
        )
        self.assertEqual(outbound.get(timeout=1), {
            "type": "device_use.turn_end.v1",
            "activation_id": binding.activation_id,
            "runtime_session_id": "runtime-1",
            "turn_id": "turn-1",
        })
        with self.assertRaises(DeviceUseAuthorizationError):
            service.invoke(
                binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
                provider_thread_id="provider-thread", provider_turn_id="provider-turn",
                call_id="call-1", tool_name="mac_computer",
                arguments={"action": "observe"}, task_text="duplicate", timeout_seconds=.01,
            )

    def test_only_a_successful_observation_may_declare_an_image(self):
        service, binding, outbound = self.connected()
        errors = []
        worker = threading.Thread(target=lambda: self._capture_error(errors, lambda: service.invoke(
            binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
            provider_thread_id="provider-thread", provider_turn_id="provider-turn",
            call_id="call-1", tool_name="mac_calendar", arguments={"action": "create_event"},
            task_text="calendar", timeout_seconds=.05,
        )))
        worker.start(); frame = outbound.get(timeout=1)
        service.accept_invocation(binding.activation_id, frame)
        with self.assertRaises(DeviceUseAuthorizationError):
            service.deliver_result(binding.activation_id, {
                "invocation_id": frame["invocation_id"], "call_id": "call-1",
                "arguments_digest": frame["arguments_digest"],
                "result": {"success": True, "contentItems": [{"type": "inputText", "text": "bad"}]},
                "has_image": True, "image_sha256": "a" * 64,
            })
        service.disconnect_executor(binding.activation_id)
        worker.join(timeout=1)
        self.assertEqual(str(errors[0]), "device_use_execution_unknown")

    def test_observe_app_is_a_read_only_image_observation(self):
        service, binding, outbound = self.connected()
        results = []
        worker = threading.Thread(target=lambda: results.append(service.invoke(
            binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
            provider_thread_id="provider-thread", provider_turn_id="provider-turn",
            call_id="observe-main", tool_name="mac_peekaboo",
            arguments={"action": "observe_app", "bundle_id": "com.apple.Safari"},
            task_text="observe", timeout_seconds=1,
        )))
        worker.start(); frame = outbound.get(timeout=1)
        jpeg = b"\xff\xd8main-window\xff\xd9"
        service.accept_invocation(binding.activation_id, frame)
        service.deliver_result(binding.activation_id, {
            "invocation_id": frame["invocation_id"], "call_id": "observe-main",
            "arguments_digest": frame["arguments_digest"],
            "result": {"success": True, "contentItems": [{"type": "inputText", "text": "main"}]},
            "has_image": True, "image_sha256": hashlib.sha256(jpeg).hexdigest(),
        })
        service.deliver_image(binding.activation_id, encode_image_frame(
            invocation_id=frame["invocation_id"], call_id="observe-main", jpeg=jpeg,
        ))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].image_jpeg, jpeg)
        metric = service.activation_metrics(
            binding.activation_id, owner_user_id="user-1", workspace_id="default",
        )["invocations"][0]
        self.assertEqual(metric["effect_class"], "read")

    def test_project_contact_sheet_may_declare_one_image(self):
        service, binding, outbound = self.connected()
        results = []
        worker = threading.Thread(target=lambda: results.append(service.invoke(
            binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
            provider_thread_id="provider-thread", provider_turn_id="provider-turn",
            call_id="sample-frames", tool_name="mac_project",
            arguments={"action": "sample_frames", "project_id": "project-1", "source": "source.mov"},
            task_text="sample", timeout_seconds=1,
        )))
        worker.start(); frame = outbound.get(timeout=1)
        jpeg = b"\xff\xd8contact-sheet\xff\xd9"
        service.accept_invocation(binding.activation_id, frame)
        service.deliver_result(binding.activation_id, {
            "invocation_id": frame["invocation_id"], "call_id": "sample-frames",
            "arguments_digest": frame["arguments_digest"],
            "result": {"success": True, "contentItems": [{"type": "inputText", "text": "samples"}]},
            "has_image": True, "image_sha256": hashlib.sha256(jpeg).hexdigest(),
        })
        service.deliver_image(binding.activation_id, encode_image_frame(
            invocation_id=frame["invocation_id"], call_id="sample-frames", jpeg=jpeg,
        ))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].image_jpeg, jpeg)
        self.assertEqual(service.journal()[-1].effect_class, "control")

    def test_eventkit_result_budget_matches_the_direct_v40_executor(self):
        service, binding, outbound = self.connected()
        results = []
        worker = threading.Thread(target=lambda: results.append(service.invoke(
            binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
            provider_thread_id="provider-thread", provider_turn_id="provider-turn",
            call_id="calendar-read", tool_name="mac_calendar",
            arguments={"action": "list_events"}, task_text="calendar", timeout_seconds=1,
        )))
        worker.start(); frame = outbound.get(timeout=1)
        service.accept_invocation(binding.activation_id, frame)
        # Quotes exercise the worst-case JSON escaping of a direct EventKit text
        # result: 199,999 bytes become just over 400 KB in the relay envelope.
        eventkit_text = '"' * 199_999
        service.deliver_result(binding.activation_id, {
            "invocation_id": frame["invocation_id"], "call_id": "calendar-read",
            "arguments_digest": frame["arguments_digest"],
            "result": {"success": True, "contentItems": [{"type": "inputText", "text": eventkit_text}]},
            "has_image": False,
        })
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].result["contentItems"][0]["text"], eventkit_text)

    def test_disconnect_marks_dispatched_control_execution_unknown(self):
        service, binding, outbound = self.connected()
        errors = []
        worker = threading.Thread(target=lambda: self._capture_error(errors, lambda: service.invoke(
            binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
            provider_thread_id="provider-thread", provider_turn_id="provider-turn",
            call_id="call-1", tool_name="mac_computer", arguments={"action": "click", "x": 1, "y": 1},
            task_text="click", timeout_seconds=1,
        )))
        worker.start(); outbound.get(timeout=1)
        service.disconnect_executor(binding.activation_id)
        worker.join(timeout=1)
        self.assertEqual(str(errors[0]), "device_use_execution_unknown")
        self.assertEqual(service.journal()[-1].status, "execution_unknown")

    def test_disconnected_executor_cannot_be_bound_to_a_session(self):
        service = DeviceUseService()
        activation, ticket = service.create_activation(
            owner_user_id="user-1", auth_session_id="auth-1",
            workspace_id="default", session_generation="generation-1",
        )
        outbound: queue.Queue = queue.Queue(maxsize=8)
        service.connect_executor(
            ticket=ticket,
            protocol_version=DEVICE_USE_PROTOCOL_VERSION,
            executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
            tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
            mode="on",
            initial_app="com.apple.Safari",
            approved_apps=["com.apple.Safari"],
            outbound=outbound,
        )
        binding = service.binding_snapshot(
            activation["activation_id"],
            owner_user_id="user-1",
            workspace_id="default",
        )
        service.disconnect_executor(binding.activation_id)
        with self.assertRaises(DeviceUseUnavailableError):
            service.bind_session(binding, session_id="runtime-1")

    def test_activation_ticket_expires_and_cannot_be_redeemed(self):
        now = datetime(2026, 9, 13, 12, tzinfo=UTC)
        service = DeviceUseService(now=lambda: now)
        _activation, ticket = service.create_activation(
            owner_user_id="user-1", auth_session_id="auth-1",
            workspace_id="default", session_generation="generation-1",
        )
        now += timedelta(seconds=61)
        with self.assertRaises(DeviceUseAuthorizationError):
            service.connect_executor(
                ticket=ticket,
                protocol_version=DEVICE_USE_PROTOCOL_VERSION,
                executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
                tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST,
                mode="on",
                initial_app="com.apple.Safari",
                approved_apps=["com.apple.Safari"],
                outbound=queue.Queue(maxsize=8),
            )

    def test_activation_is_pinned_to_the_browser_auth_session(self):
        service, binding, _outbound = self.connected()
        with self.assertRaises(DeviceUseAuthorizationError):
            service.binding_snapshot(
                binding.activation_id,
                owner_user_id="user-1",
                workspace_id="default",
                auth_session_id="auth-2",
            )
        with self.assertRaises(DeviceUseAuthorizationError):
            service.activation_metrics(
                binding.activation_id,
                owner_user_id="user-1",
                workspace_id="default",
                auth_session_id="auth-2",
            )
        with self.assertRaises(DeviceUseAuthorizationError):
            service.stop_activation(
                binding.activation_id,
                owner_user_id="user-1",
                workspace_id="default",
                auth_session_id="auth-2",
            )

    def test_non_finite_arguments_are_rejected_before_dispatch(self):
        service, binding, outbound = self.connected()

        with self.assertRaisesRegex(
            DeviceUseAuthorizationError,
            "device_use_arguments_invalid",
        ):
            service.invoke(
                binding=binding,
                runtime_session_id="runtime-1",
                turn_id="turn-1",
                provider_thread_id="provider-thread",
                provider_turn_id="provider-turn",
                call_id="call-1",
                tool_name="mac_computer",
                arguments={"action": "click", "x": float("nan")},
                task_text="invalid",
            )
        self.assertTrue(outbound.empty())

    @staticmethod
    def _capture_error(target, action):
        try: action()
        except Exception as error: target.append(error)


if __name__ == "__main__":
    unittest.main()
