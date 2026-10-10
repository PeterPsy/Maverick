"""The operator follows only the recovery boundary returned by native tools."""

import unittest

from core.device_use.computer_actor_recovery import ComputerActorRecovery
from core.device_use.models import DeviceUseResult


class ComputerActorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.recovery = ComputerActorRecovery("com.apple.Safari")

    @staticmethod
    def result(text, success=False, image=None):
        return DeviceUseResult("invocation", "call", {"success": success, "contentItems": [
            {"type": "inputText", "text": text}]}, image, None, 1)

    def test_explicit_native_pre_dispatch_recovery_reacquires_same_selected_app(self):
        arguments = {"action": "select_app", "bundle_id": "com.apple.Notes"}
        self.assertTrue(self.recovery.record("mac_computer", arguments, self.result(
            "MC-FOCUS-01: Questo errore pre-dispatch non blocca il turno: acquisisci una nuova osservazione.")))
        self.assertTrue(self.recovery.permits("mac_computer", {"action": "observe"}))
        self.assertFalse(self.recovery.permits("mac_computer", {"action": "open_app"}))
        self.assertFalse(self.recovery.permits("mac_computer", {"action": "select_app", "bundle_id": "com.apple.Safari"}))
        self.assertFalse(self.recovery.permits("mac_peekaboo", {"action": "observe_app", "bundle_id": "com.apple.Notes"}))
        self.assertTrue(self.recovery.record("mac_computer", {"action": "observe"}, self.result("fresh", True, b"jpeg")))
        self.assertTrue(self.recovery.permits("mac_computer", {"action": "open_app"}))

    def test_code_without_declared_pre_dispatch_recovery_is_terminal(self):
        self.assertFalse(self.recovery.record("mac_computer", {"action": "click"},
                                             self.result("MC-FOCUS-01: failure")))

    def test_recovery_code_on_wrong_engine_or_read_action_cannot_authorize_more_work(self):
        for tool, arguments, code in (
            ("mac_computer", {"action": "observe"}, "MC-PEEKABOO-25"),
            ("mac_peekaboo", {"action": "click", "bundle_id": "com.apple.Safari"}, "MC-PEEKABOO-25"),
            ("mac_peekaboo", {"action": "observe_app", "bundle_id": "com.apple.Safari"}, "MC-PEEKABOO-21"),
            ("mac_peekaboo", {"action": "click"}, "MC-PEEKABOO-21"),
        ):
            with self.subTest(tool=tool, action=arguments["action"]):
                self.assertFalse(self.recovery.record(tool, arguments, self.result(code)))

    def test_window_list_without_image_does_not_unlock_input(self):
        arguments = {"action": "observe", "bundle_id": "com.apple.Safari", "window_id": "expired"}
        self.recovery.record("mac_peekaboo", arguments, self.result("MC-PEEKABOO-25"))
        read = {"action": "list_windows", "bundle_id": "com.apple.Safari"}
        self.assertTrue(self.recovery.permits("mac_peekaboo", read))
        self.recovery.record("mac_peekaboo", read, self.result("current windows", True))
        self.assertFalse(self.recovery.permits("mac_peekaboo", {"action": "click", "bundle_id": "com.apple.Safari"}))
        self.assertTrue(self.recovery.permits("mac_peekaboo", {"action": "observe", "bundle_id": "com.apple.Safari"}))
