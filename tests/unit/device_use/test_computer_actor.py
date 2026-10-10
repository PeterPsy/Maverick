"""Authority and lifecycle tests for internal UI delegation."""

import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.device_use.computer_actor import ComputerInteraction
from core.device_use.computer_actor_contract import (
    actor_device_use_tools, planner_action_allowed, planner_device_use_tools,
    validate_actor_task,
)
from core.device_use.errors import DeviceUseAuthorizationError, DeviceUseUnavailableError
from core.device_use.models import DeviceUseResult
from core.device_use.computer_actor_registry import (
    cancel_computer_actor, invoke_computer_actor, register_computer_actor,
)


class ComputerActorTests(unittest.TestCase):
    def setUp(self):
        self.binding = SimpleNamespace(activation_id="activation", workspace_id="default", owner_user_id="owner")
        self.session = SimpleNamespace(device_use_binding=self.binding, workspace_id="default", owner_user_id="owner", status="running")
        self.turn = SimpleNamespace(session_id="parent", status="active", input_text="Original task",
                                    cancellation_requested_at=None)
        self.store = SimpleNamespace(get_session=lambda sid: self.session, get_turn=lambda tid: self.turn,
                                    get_state=lambda sid: SimpleNamespace(current_turn_id="parent-turn"))
        self.service = Mock()
        self.service.binding_connected.return_value = True
        self.service.invoke.return_value = DeviceUseResult("native", "native-call", {"success": True}, b"jpeg", None, 1)
        self.client = Mock(cancelled=threading.Event())
        self.client.run.side_effect = self.operator_run
        self.factory = Mock(return_value=self.client)
        self.actor = ComputerInteraction(SimpleNamespace(runtime_store=self.store, usage_store=None,
            runtime_event_bus=None, device_use_service=self.service), "parent", "activation", client_factory=self.factory)

    def operator_run(self, task, *, invoke, active, usage_sink):
        self.assertTrue(active())
        invoke("mac_peekaboo", {"action": "observe_app"}, "call-1")
        return {"status": "completed", "summary": "Done", "evidence": "Verified", "steps": 1}, b"jpeg"

    def run_actor(self, **kwargs):
        return self.actor.run(binding=self.binding, turn_id="parent-turn", provider_thread_id="parent-thread",
            provider_turn_id="parent-provider-turn", call_id="parent-call", task_text="Untrusted caller task",
            arguments={"objective": "Select prepared target", "completion_criterion": "Target selected"}, **kwargs)

    def test_dispatch_keeps_parent_authority_and_original_task(self):
        result = self.run_actor()
        authority = self.service.invoke.call_args.kwargs
        self.assertEqual(authority["runtime_session_id"], "parent")
        self.assertEqual(authority["provider_thread_id"], "parent-thread")
        self.assertEqual(authority["provider_turn_id"], "parent-provider-turn")
        self.assertEqual(authority["task_text"], "Original task")
        self.assertIs(authority["binding"], self.binding)
        self.assertNotEqual(authority["call_id"], "parent-call")
        self.assertEqual(result.image_jpeg, b"jpeg")
        self.assertEqual(result.native_duration_ms, 1)

    def test_completed_parent_or_cancellation_fences_inference(self):
        for status in ("completed", "cancelled", "waiting_for_tool_confirmation"):
            with self.subTest(status=status):
                self.turn.status = status
                with self.assertRaises(DeviceUseAuthorizationError):
                    self.run_actor()
        self.factory.assert_not_called()

    def test_pending_cancellation_fences_input_before_provider_ack(self):
        self.turn.cancellation_requested_at = object()
        with self.assertRaises(DeviceUseAuthorizationError):
            self.run_actor()
        self.service.invoke.assert_not_called()

    def test_terminal_session_fences_a_turn_whose_status_has_not_caught_up(self):
        self.session.status = "stopping"
        with self.assertRaises(DeviceUseAuthorizationError):
            self.run_actor()
        self.factory.assert_not_called()

    def test_owner_and_activation_changes_are_rejected(self):
        self.session.owner_user_id = "another-owner"
        with self.assertRaises(DeviceUseAuthorizationError):
            self.run_actor()
        self.service.invoke.assert_not_called()

    def test_user_correction_during_operator_work_fences_next_action(self):
        current = ["Latest task"]
        def run(task, *, invoke, active, usage_sink):
            current[0] = "New user correction"
            self.assertFalse(active())
            with self.assertRaises(DeviceUseAuthorizationError):
                invoke("mac_peekaboo", {"action": "click"}, "call-1")
            return {"status": "completed", "summary": "Stale", "evidence": "", "steps": 0}, b"stale"
        self.client.run.side_effect = run
        result = self.actor.run(binding=self.binding, turn_id="parent-turn", provider_thread_id="thread",
            provider_turn_id="turn", call_id="call", task_text="Latest task", authority_active=lambda: current[0] == "Latest task",
            arguments={"objective": "Select target", "completion_criterion": "Selected"})
        self.assertFalse(result.result["success"])
        self.assertIsNone(result.image_jpeg)
        self.service.invoke.assert_not_called()

    def test_correction_before_operator_admission_cannot_be_cleared_by_new_task(self):
        self.actor.cancel()
        with self.assertRaisesRegex(DeviceUseAuthorizationError, "computer_actor_parent_not_active"):
            self.run_actor(authority_active=lambda: False)
        self.factory.assert_not_called()
        self.service.invoke.assert_not_called()

    def test_operator_unavailable_does_not_dispatch_or_revoke_native_lease(self):
        self.factory.side_effect = RuntimeError("Unavailable")
        with self.assertRaises(DeviceUseUnavailableError):
            self.run_actor()
        self.service.invoke.assert_not_called()
        self.service.stop_activation.assert_not_called()

    def test_operator_cannot_author_text_not_supplied_by_the_planner(self):
        def run(task, *, invoke, active, usage_sink):
            with self.assertRaisesRegex(DeviceUseAuthorizationError, "computer_actor_unprepared_text"):
                invoke("mac_peekaboo", {"action": "type", "text": "Invented content"}, "call-1")
            return {"status": "needs_decision", "summary": "Exact text needed", "evidence": "", "steps": 0}, None
        self.client.run.side_effect = run
        self.run_actor()
        self.service.invoke.assert_not_called()

    def test_idle_process_is_retained_and_closed_on_disconnect(self):
        self.run_actor()
        self.actor.cancel()
        self.client.cancel.assert_not_called()
        self.actor.cancel(close=True)
        self.client.cancel.assert_called_once()

    def test_new_subtask_does_not_clear_the_cancelled_previous_subtasks_guard(self):
        guards = []

        def run(task, *, invoke, active, usage_sink):
            guards.append(active)
            if len(guards) == 1:
                self.actor.cancel()
                self.assertFalse(active())
            else:
                self.assertTrue(active())
                self.assertFalse(guards[0]())
            return {"status": "needs_decision", "summary": "Stopped", "evidence": "", "steps": 0}, None

        self.client.run.side_effect = run
        self.run_actor()
        self.run_actor()
        self.assertFalse(guards[0]())

    def test_native_catalog_is_not_mutated_by_planner_projection(self):
        tools = {tool["name"]: tool for tool in planner_device_use_tools()}
        self.assertIn("computer_interact", tools)
        self.assertNotIn("click", tools["mac_peekaboo"]["inputSchema"]["properties"]["action"]["enum"])
        self.assertIn("click", next(tool for tool in actor_device_use_tools() if tool["name"] == "mac_peekaboo")
                      ["inputSchema"]["properties"]["action"]["enum"])
        self.assertFalse(planner_action_allowed("mac_browser", {"action": "type_text"}))
        self.assertTrue(planner_action_allowed("mac_project", {"action": "generate_srt"}))
        self.assertEqual({tool["name"] for tool in actor_device_use_tools()}, {"mac_computer", "mac_peekaboo", "mac_browser"})

    def test_invalid_or_unbounded_task_is_rejected(self):
        for value in ({}, {"objective": "x", "completion_criterion": "y", "model": "other"},
                      {"objective": "x" * 4001, "completion_criterion": "y"}):
            with self.subTest(value=list(value)):
                with self.assertRaises(ValueError):
                    validate_actor_task(value)


class ComputerActorRegistryTests(unittest.TestCase):
    def test_provider_retirement_closes_idle_process_but_keeps_controller_for_reuse(self):
        controller = Mock(activation_id="activation")
        self.addCleanup(cancel_computer_actor, "registry-test", forget=True)
        with patch("core.device_use.computer_actor.ComputerInteraction", return_value=controller):
            register_computer_actor(object(), "registry-test", "activation")
        cancel_computer_actor("registry-test", close=True)
        controller.cancel.assert_called_once_with(close=True)
        invoke_computer_actor("registry-test", arguments={"objective": "New task"})
        controller.run.assert_called_once()
