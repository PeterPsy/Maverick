"""Tests for app-owned event publication guardrails."""

from __future__ import annotations

import unittest

from core.api.app_event_publication import publish_declared_app_events


class FakeAppEventBus:
    def __init__(self) -> None:
        self.events: list[dict[str, str]] = []

    def publish(self, event: dict[str, str]) -> None:
        self.events.append(event)


class AppEventPublicationTestCase(unittest.TestCase):
    def test_publisher_forces_current_app_identity_and_declared_resource(self) -> None:
        bus = FakeAppEventBus()
        result = {
            "app_events": [
                {
                    "type": "maverick.app.data-changed",
                    "owner_app_id": "other-app",
                    "resource": "records",
                }
            ]
        }

        publish_declared_app_events(
            bus,
            result,
            workspace_id="default",
            app_id="records",
            declared_resources=["records"],
        )

        self.assertEqual(
            bus.events,
            [
                {
                    "type": "maverick.app.data-changed",
                    "workspace_id": "default",
                    "owner_app_id": "records",
                    "resource": "records",
                }
            ],
        )
        self.assertIn("app_events", result)

    def test_publisher_ignores_spoofed_type_and_undeclared_resource(self) -> None:
        bus = FakeAppEventBus()
        result = {
            "app_events": [
                {"type": "maverick.app.frontend-changed", "resource": "records"},
                {"type": "maverick.widget.data-changed", "resource": "records"},
                {"type": "maverick.app.data-changed", "resource": "other"},
                {"type": "maverick.app.data-changed"},
                "not-an-event",
            ]
        }

        with self.assertLogs("core.api.app_event_publication", level="WARNING") as logs:
            publish_declared_app_events(
                bus,
                result,
                workspace_id="default",
                app_id="records",
                declared_resources=["records"],
            )

        self.assertEqual(bus.events, [])
        self.assertEqual(len(logs.output), 4)

    def test_publisher_can_remove_app_events_from_backend_response_payload(self) -> None:
        bus = FakeAppEventBus()
        result = {"app_events": [{"type": "maverick.app.data-changed", "resource": "view-state"}]}

        publish_declared_app_events(
            bus,
            result,
            workspace_id="default",
            app_id="sample-app",
            declared_resources=["view-state"],
            remove_from_result=True,
        )

        self.assertNotIn("app_events", result)
        self.assertEqual(bus.events[0]["owner_app_id"], "sample-app")


if __name__ == "__main__":
    unittest.main()
