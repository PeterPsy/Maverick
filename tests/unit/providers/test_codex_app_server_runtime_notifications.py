from __future__ import annotations

from threading import Lock
from types import SimpleNamespace
import unittest

from core.providers.codex_app_server_runtime_notifications import _handle_generic_notification


class CodexAppServerRuntimeNotificationTestCase(unittest.TestCase):
    def test_turn_diff_updates_do_not_fall_back_to_noisy_runtime_steps(self) -> None:
        emitted = []
        runtime = SimpleNamespace(event_lock=Lock(), current_event_sink=emitted.append)

        _handle_generic_notification(
            runtime,
            method="turn/diff/updated",
            params={"diff": "large cumulative diff"},
        )

        self.assertEqual(emitted, [])

    def test_unknown_notifications_still_emit_generic_runtime_steps(self) -> None:
        emitted = []
        runtime = SimpleNamespace(event_lock=Lock(), current_event_sink=emitted.append)

        _handle_generic_notification(
            runtime,
            method="future/capability/updated",
            params={"state": "ready"},
        )

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].event_type, "runtime.step.updated")
        self.assertEqual(emitted[0].payload["provider_event_type"], "future.capability.updated")


if __name__ == "__main__":
    unittest.main()
