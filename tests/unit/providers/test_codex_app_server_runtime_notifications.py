from __future__ import annotations

import importlib
from threading import Lock
from types import SimpleNamespace
import unittest

importlib.import_module("core.providers.codex_app_server_runtime")
from core.providers.codex_app_server_runtime_protocol import _handle_notification
from core.providers.codex_app_server_runtime_notifications import _handle_generic_notification


class CodexAppServerRuntimeNotificationTestCase(unittest.TestCase):
    def test_token_usage_notification_emits_exact_cumulative_usage(self) -> None:
        emitted = []
        runtime = SimpleNamespace(
            current_event_sink=emitted.append,
            current_provider_turn_id="turn-provider-1",
            event_lock=Lock(),
            provider_thread_id="thread-provider-1",
        )

        _handle_notification(
            runtime,
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread-provider-1",
                    "turnId": "turn-provider-1",
                    "tokenUsage": {
                        "total": {
                            "inputTokens": 120,
                            "cachedInputTokens": 20,
                            "outputTokens": 30,
                            "reasoningOutputTokens": 10,
                            "totalTokens": 150,
                        },
                        "last": {"totalTokens": 75},
                        "modelContextWindow": 200,
                    },
                },
            },
        )

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].event_type, "runtime.usage.reported")
        self.assertEqual(emitted[0].payload["semantics"], "cumulative")
        self.assertEqual(emitted[0].payload["token_accuracy"], "exact")
        self.assertEqual(emitted[0].payload["total_tokens"], 150)
        self.assertEqual(emitted[0].payload["context_tokens"], 75)
        self.assertEqual(emitted[0].payload["context_window_tokens"], 200)

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
