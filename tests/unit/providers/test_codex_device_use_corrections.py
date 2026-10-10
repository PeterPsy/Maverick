"""Queued UI objectives cannot survive a correction on the same parent turn."""

import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.providers.codex_app_server_device_use import process_device_use_request
from core.providers.codex_app_server_device_use_authority import (
    capture_device_use_authority, device_use_correction,
)
from core.providers.codex_app_server_device_use_requests import dispatch_server_request
from core.providers.codex_app_server_device_use_turn import clear_device_use_turn, set_device_use_turn
from core.providers.codex_app_server_runtime_state import _CodexAppServerRuntime, _RUNTIMES
from core.providers.codex_app_server_runtime_steering import steer_codex_app_server_turn
from core.providers.codex_app_server_runtime_errors import (
    CodexAppServerDeliveryUncertainError, CodexAppServerRequestError,
)


class DeviceUseCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = _CodexAppServerRuntime(
            session_id="correction-test", workspace_id="default", runtime_root="/tmp/correction-test",
            process=SimpleNamespace(stdin=io.StringIO(), poll=lambda: None),
            device_use_binding=object(), provider_thread_id="thread", current_provider_turn_id="turn",
            current_runtime_turn_id="parent-turn", current_task_text="Click the old target",
        )
        self.payload = {"id": 1, "method": "item/tool/call", "params": {
            "threadId": "thread", "turnId": "turn", "callId": "old-click", "tool": "computer_interact",
            "arguments": {"objective": "Click the old target", "completion_criterion": "Old target selected"},
        }}
        self.service = Mock()
        self.registry = patch("core.providers.codex_app_server_device_use.device_use_service_for_session",
                              return_value=self.service)
        self.registry.start()
        self.addCleanup(self.registry.stop)
        _RUNTIMES[self.runtime.session_id] = self.runtime
        self.addCleanup(_RUNTIMES.pop, self.runtime.session_id)

    def enqueue(self):
        dispatch_server_request(self.runtime, self.payload, Mock())
        return self.runtime.server_request_queue.get_nowait()

    def process(self, request):
        payload, authority = request
        process_device_use_request(self.runtime, payload, authority=authority)

    def test_queued_objective_is_rejected_after_same_turn_correction(self):
        request = self.enqueue()
        with device_use_correction(self.runtime) as acknowledge:
            self.runtime.current_task_text = "Do not click the old target"
            acknowledge()
        with patch("core.providers.codex_app_server_device_use.invoke_computer_actor") as actor:
            self.process(request)
        actor.assert_not_called()
        self.service.invoke.assert_not_called()
        self.assertFalse(json.loads(self.runtime.process.stdin.getvalue())["result"]["success"])

    def test_request_received_while_correction_is_pending_stays_invalid_after_ack(self):
        with device_use_correction(self.runtime) as acknowledge:
            request = self.enqueue()
            acknowledge()
        self.assertFalse(request[1].active(self.runtime))
        with patch("core.providers.codex_app_server_device_use.invoke_computer_actor") as actor:
            self.process(request)
        actor.assert_not_called()

    def test_correction_fences_old_work_before_cancel_and_native_end_turn(self):
        request = self.enqueue()
        before = self.runtime.device_use_objective_revision

        def assert_fenced(*args, **kwargs):
            self.assertEqual(self.runtime.device_use_objective_revision, before + 1)
            self.assertFalse(request[1].active(self.runtime))
            self.assertTrue(self.runtime.device_use_correction_pending)

        native = Mock()
        native.end_turn.side_effect = assert_fenced
        with patch("core.device_use.computer_actor_registry.cancel_computer_actor", side_effect=assert_fenced), \
             patch("core.device_use.runtime_registry.device_use_service_for_session", return_value=native), \
             patch("core.providers.codex_app_server_runtime_steering._send_request", return_value={"turnId": "turn"}):
            result = steer_codex_app_server_turn(self.runtime.session_id, input_text="Do not click the old target")
        self.assertEqual(result.status, "steered")
        self.assertFalse(self.runtime.device_use_correction_pending)
        self.assertFalse(request[1].active(self.runtime))
        self.payload["params"]["arguments"]["objective"] = "Select the corrected target"
        fresh = self.enqueue()[1]
        self.assertTrue(fresh.active(self.runtime))
        self.assertIn("Do not click the old target", fresh.task_text)

    def test_uncertain_correction_does_not_restore_queued_authority(self):
        request = self.enqueue()
        with patch("core.providers.codex_app_server_runtime_steering._send_request",
                   side_effect=CodexAppServerDeliveryUncertainError("timeout")):
            result = steer_codex_app_server_turn(self.runtime.session_id, input_text="Do not click")
        self.assertEqual(result.status, "delivery_uncertain")
        self.assertFalse(request[1].active(self.runtime))
        self.assertTrue(self.runtime.device_use_correction_pending)
        self.assertFalse(self.enqueue()[1].active(self.runtime))

    def test_rejected_correction_keeps_future_old_goal_requests_fenced_until_new_turn(self):
        with patch("core.providers.codex_app_server_runtime_steering._send_request",
                   side_effect=CodexAppServerRequestError("turn/steer", code=-32600, message="not steerable")):
            result = steer_codex_app_server_turn(self.runtime.session_id, input_text="Do not click")
        self.assertEqual(result.status, "not_supported")
        self.assertFalse(self.enqueue()[1].active(self.runtime))
        set_device_use_turn(self.runtime, runtime_turn_id="new-turn", task_text="Do not click")
        self.runtime.current_provider_turn_id = "new-provider-turn"
        self.assertTrue(capture_device_use_authority(self.runtime).active(self.runtime))

    def test_authority_remains_invalid_when_task_text_is_restored(self):
        authority = capture_device_use_authority(self.runtime)
        with device_use_correction(self.runtime) as acknowledge:
            acknowledge()
        self.assertFalse(authority.active(self.runtime))

    def test_turn_clear_and_restart_invalidate_old_requests_even_with_same_ids(self):
        for change in (clear_device_use_turn,
                       lambda runtime: set_device_use_turn(runtime, runtime_turn_id="parent-turn",
                                                           task_text="Click the old target")):
            authority = capture_device_use_authority(self.runtime)
            change(self.runtime)
            self.assertFalse(authority.active(self.runtime))
