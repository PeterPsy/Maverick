from __future__ import annotations

import json
import unittest

from core.runtime.execution_events import parse_provider_json_event


class RuntimeExecutionEventsTestCase(unittest.TestCase):
    def test_provider_warning_is_diagnostic_instead_of_assistant_output(self) -> None:
        message = "Under-development features enabled: skip_host_skill_discovery."
        for payload in (
            {"type": "warning", "message": message},
            {"type": "warning", "item": {"message": message}},
        ):
            with self.subTest(payload=payload):
                event = parse_provider_json_event(json.dumps(payload))
                self.assertEqual(event.event_type, "runtime.warning")
                self.assertEqual(event.payload, {"message": message, "provider_event_type": "warning"})

        event = parse_provider_json_event(message)
        self.assertEqual(event.event_type, "runtime.output.delta")
        self.assertEqual(event.payload["text"], message)

    def test_account_updates_are_filtered_before_runtime_event_emission(self) -> None:
        for event_type in ("account.updated", "account/updated", "account_updated", "account updated"):
            with self.subTest(event_type=event_type):
                event = parse_provider_json_event(
                    json.dumps({"type": event_type, "item": {"authMode": "chatgpt", "planType": "pro"}})
                )
                self.assertIsNone(event)

    def test_account_update_labels_are_not_assistant_output(self) -> None:
        self.assertIsNone(parse_provider_json_event("account updated"))

    def test_account_mentions_and_unknown_notifications_remain_visible(self) -> None:
        text = "The account updated successfully."
        event = parse_provider_json_event(text)
        self.assertEqual(event.event_type, "runtime.output.delta")
        self.assertEqual(event.payload["text"], text)

        event = parse_provider_json_event('{"type": "future.capability.updated", "item": {"state": "ready"}}')
        self.assertEqual(event.event_type, "runtime.step.updated")
        self.assertEqual(event.payload["provider_event_type"], "future.capability.updated")


if __name__ == "__main__":
    unittest.main()
