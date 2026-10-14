"""DeviceObservationTests fixtures extracted without changing assertions."""

from __future__ import annotations
import hashlib
import threading
import unittest
from core.device_use.errors import DeviceUseAuthorizationError
from core.device_use.service import encode_image_frame
from tests.unit.device_use.device_connection_fixture import DeviceConnectionFixture


class DeviceObservationTests(DeviceConnectionFixture, unittest.TestCase):
    def test_companion_observation_and_declared_input_image_use_the_existing_binary_route(self):
        cases = [("mac_browser", "observe", {})]
        cases += [("mac_browser", action, {"observe_after": True}) for action in
                  ["click", "click_element", "fill", "set_checked", "select_option", "select_text", "paste", "upload_files"]]
        cases += [("mac_peekaboo", action, {"observe_after": True, "bundle_id": "com.apple.TextEdit"})
                  for action in ["set_value", "select_text", "paste"]]
        for tool, action, extra in cases:
            with self.subTest(tool=tool, action=action):
                service, binding, outbound = self.connected()
                results, errors = [], []
                args = {"action": action, "tab_id": "companion-tab", **extra}
                worker = threading.Thread(target=lambda: self._capture_error(errors, lambda: results.append(service.invoke(
                    binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
                    provider_thread_id="provider-thread", provider_turn_id="provider-turn", call_id="browser-call",
                    tool_name=tool, arguments=args, task_text="verify exact native surface", timeout_seconds=1))))
                worker.start()
                frame = outbound.get(timeout=1)
                jpeg = b"\xff\xd8companion\xff\xd9"
                service.accept_invocation(binding.activation_id, frame)
                service.deliver_result(binding.activation_id, {
                    "invocation_id": frame["invocation_id"], "call_id": "browser-call", "arguments_digest": frame["arguments_digest"],
                    "result": {"success": True, "contentItems": [{"type": "inputText", "text": "execution_environment=parallel_companion"}]},
                    "has_image": True, "image_sha256": hashlib.sha256(jpeg).hexdigest(),
                })
                service.deliver_image(binding.activation_id, encode_image_frame(invocation_id=frame["invocation_id"], call_id="browser-call", jpeg=jpeg))
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(results[0].image_jpeg, jpeg)

    def test_one_input_with_declared_observation_returns_image_and_user_wait(self):
        service, binding, outbound = self.connected()
        results = []
        worker = threading.Thread(target=lambda: results.append(service.invoke(
            binding=binding, runtime_session_id="runtime-1", turn_id="turn-1",
            provider_thread_id="provider-thread", provider_turn_id="provider-turn", call_id="combined",
            tool_name="mac_peekaboo", arguments={"action": "click", "bundle_id": "com.apple.Safari",
            "snapshot": "snapshot-1", "element": "B1", "observe_after": True}, task_text="click", timeout_seconds=1)))
        worker.start()
        frame = outbound.get(timeout=1)
        jpeg = b"\xff\xd8after-input\xff\xd9"
        service.accept_invocation(binding.activation_id, frame)
        service.deliver_result(binding.activation_id, {
            "invocation_id": frame["invocation_id"], "call_id": "combined", "arguments_digest": frame["arguments_digest"],
            "result": {"success": True, "contentItems": [{"type": "inputText", "text": "action_outcome=confirmed_change"}]},
            "has_image": True, "image_sha256": hashlib.sha256(jpeg).hexdigest(),
            "native_duration_ms": 100, "native_user_wait_ms": 40,
        })
        service.deliver_image(binding.activation_id, encode_image_frame(invocation_id=frame["invocation_id"], call_id="combined", jpeg=jpeg))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].image_jpeg, jpeg)
        self.assertEqual(results[0].native_user_wait_ms, 40)

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
