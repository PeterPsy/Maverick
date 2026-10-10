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

    def test_uncertain_action_cannot_be_replayed_by_changing_observation_options(self):
        click = {"action": "click", "bundle_id": "com.apple.Safari", "element": "B1", "snapshot": "old"}
        self.recovery.record("mac_peekaboo", click, self.result("MC-PEEKABOO-21"))
        observation = {"action": "observe_app", "bundle_id": "com.apple.Safari"}
        self.recovery.record("mac_peekaboo", observation, self.result("fresh", True, b"jpeg"))
        for options in ({"details": True}, {"details": False}, {"image_max_dimension": 640},
                        {"image_max_dimension": 3840}, {"observe_after": True},
                        {"window_id": 42}, {"text": "unused for a click", "key": "Return"},
                        {"details": True, "image_max_dimension": 1600, "observe_after": False}):
            with self.subTest(options=options):
                self.assertFalse(self.recovery.permits("mac_peekaboo", {**click, "snapshot": "fresh", **options}))
        self.assertTrue(self.recovery.permits("mac_peekaboo", {**click, "element": "B2", "snapshot": "fresh"}))

    def test_partial_input_requires_explicit_native_recovery(self):
        click = {"action": "click", "bundle_id": "com.apple.Safari", "element": "B1"}
        self.assertFalse(self.recovery.record("mac_peekaboo", click,
                         self.result("MC-PEEKABOO-22: partial input; stop")))
        self.assertTrue(self.recovery.record("mac_peekaboo", click,
                        self.result("MC-PEEKABOO-22: Full resta attivo: acquisisci una nuova osservazione")))
        self.assertFalse(self.recovery.permits("mac_peekaboo", click))

    def test_point_input_identity_uses_numeric_coordinates_and_actual_text(self):
        typing = {"action": "type_at_point", "bundle_id": "com.apple.Safari", "point_x": 0,
                  "point_y": 0.5, "text": "Prepared text", "snapshot": "old"}
        self.recovery.record("mac_peekaboo", typing, self.result("MC-PEEKABOO-21"))
        self.recovery.record("mac_peekaboo", {"action": "observe_app", "bundle_id": "com.apple.Safari"},
                             self.result("fresh", True, b"jpeg"))
        self.assertFalse(self.recovery.permits("mac_peekaboo", {**typing, "point_x": 0.0, "details": True}))
        self.assertTrue(self.recovery.permits("mac_peekaboo", {**typing, "point_x": 0.1}))
        self.assertTrue(self.recovery.permits("mac_peekaboo", {**typing, "text": "Other prepared text"}))

    def test_companion_recovery_is_bound_to_one_tab_and_requires_a_fresh_image(self):
        for code in ("MC-COMPANION-03", "MC-COMPANION-04"):
            with self.subTest(code=code):
                recovery = ComputerActorRecovery("com.apple.Safari")
                key = {"action": "keypress", "tab_id": "A", "key": "Return", "observation_id": "old"}
                self.assertTrue(recovery.record("mac_browser", key, self.result(code)))
                self.assertFalse(recovery.permits("mac_browser", {"action": "list_tabs"}))
                self.assertFalse(recovery.permits("mac_browser", {"action": "observe", "tab_id": "B"}))
                read = {"action": "observe", "tab_id": "A"}
                self.assertTrue(recovery.permits("mac_browser", read))
                recovery.record("mac_browser", read, self.result("no image", True))
                self.assertFalse(recovery.permits("mac_browser", key))
                recovery.record("mac_browser", read, self.result("fresh", True, b"jpeg"))
                self.assertEqual(recovery.permits("mac_browser", {**key, "observation_id": "new", "observe_after": True}),
                                 code == "MC-COMPANION-03")

    def test_unknown_tab_after_uncertain_creation_cannot_be_recreated_automatically(self):
        self.assertFalse(self.recovery.record("mac_browser", {"action": "open_tab", "url": "about:blank"},
                                             self.result("MC-COMPANION-04")))

    def test_uncertain_close_only_settles_when_inventory_proves_tab_absent(self):
        close = {"action": "close_tab", "tab_id": "A"}
        self.recovery.record("mac_browser", close, self.result("MC-COMPANION-04"))
        read = {"action": "list_tabs"}
        self.assertTrue(self.recovery.permits("mac_browser", read))
        self.recovery.record("mac_browser", read, self.result(
            '{"execution_environment":"parallel_companion","tabs":[{"tab_id":"A"}]}', True))
        self.assertIsNotNone(self.recovery.pending)
        self.recovery.record("mac_browser", read, self.result(
            '{"execution_environment":"parallel_companion","tabs":[]}', True))
        self.assertIsNone(self.recovery.pending)
        self.assertTrue(self.recovery.completion_verified)
        self.assertFalse(self.recovery.permits("mac_browser", close))

    def test_invalid_inventory_or_blind_input_cannot_verify_completion(self):
        for text in ("not json", "[]", '{"execution_environment":"other","tabs":[]}',
                     '{"execution_environment":"parallel_companion","tabs":[{}]}'):
            self.recovery.record("mac_browser", {"action": "list_tabs"}, self.result(text, True))
            self.assertFalse(self.recovery.completion_verified)
        inventory = '{"execution_environment":"parallel_companion","tabs":[]}'
        self.recovery.record("mac_browser", {"action": "list_tabs"}, self.result(inventory, True))
        self.assertTrue(self.recovery.completion_verified)
        self.recovery.record("mac_browser", {"action": "click", "tab_id": "A"}, self.result(inventory, True))
        self.assertFalse(self.recovery.completion_verified)

    def test_companion_replay_identity_normalizes_default_input_values(self):
        for original, repeated in (
            ({"action": "keypress", "key": "Return"}, {"action": "keypress", "key": "Return", "shift": False}),
            ({"action": "scroll", "direction": "down"},
             {"action": "scroll", "direction": "down", "amount": 300, "x": 0.5, "y": 0.5}),
        ):
            recovery = ComputerActorRecovery("com.apple.Safari")
            recovery.record("mac_browser", {**original, "tab_id": "A"}, self.result("MC-COMPANION-04"))
            recovery.record("mac_browser", {"action": "observe", "tab_id": "A"}, self.result("fresh", True, b"jpeg"))
            self.assertFalse(recovery.permits("mac_browser", {**repeated, "tab_id": "A", "observe_after": True}))
