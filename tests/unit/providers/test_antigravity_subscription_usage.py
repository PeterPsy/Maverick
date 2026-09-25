"""Antigravity subscription usage adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import unittest

from core.providers.errors import ProviderUsageUnavailableError
from core.providers.payloads import provider_subscription_usage_payload
from core.providers.provider_antigravity_usage import (
    read_antigravity_subscription_usage,
)


class AntigravitySubscriptionUsageTest(unittest.TestCase):
    def test_usage_parser_keeps_model_groups_windows_and_resets(self) -> None:
        captured: dict[str, object] = {}

        def runner(command: str, dependency_roots, auth_home) -> str:
            captured.update(
                command=command,
                dependency_roots=tuple(dependency_roots),
                auth_home=auth_home,
            )
            return json.dumps(
                {
                    "conversation_id": "",
                    "status": "SUCCESS",
                    "response": "human-readable summary",
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                    "command": {
                        "name": "usage",
                        "data": {
                            "description": "provider-owned copy",
                            "groups": [
                                {
                                    "name": "Gemini Models",
                                    "buckets": [
                                        {
                                            "id": "gemini-weekly",
                                            "name": "Weekly Limit Remaining",
                                            "window": "weekly",
                                            "remaining_fraction": 0.8602747321128845,
                                            "reset_time": "2026-10-01T10:53:59Z",
                                        },
                                        {
                                            "id": "gemini-5h",
                                            "name": "Five Hour Limit Remaining",
                                            "window": "5h",
                                            "remaining_fraction": 1,
                                            "reset_time": "2026-09-25T17:29:07Z",
                                        },
                                    ],
                                },
                                {
                                    "name": "Claude and GPT models",
                                    "buckets": [
                                        {
                                            "id": "3p-weekly",
                                            "name": "Weekly Limit Remaining",
                                            "window": "weekly",
                                            "remaining_fraction": 0,
                                            "reset_time": "2026-10-02T12:29:07Z",
                                        }
                                    ],
                                },
                            ],
                        },
                    },
                    "account_email": "must-not-leak@example.com",
                }
            )

        fetched_at = datetime(2026, 9, 25, 14, 29, 7, tzinfo=UTC)
        usage = read_antigravity_subscription_usage(
            "agy",
            dependency_roots=(Path("/usr/bin"),),
            auth_home=Path("/operator/profile"),
            runner=runner,
            now=fetched_at,
        )
        payload = provider_subscription_usage_payload(usage)

        self.assertEqual(captured["command"], "agy")
        self.assertEqual(captured["auth_home"], Path("/operator/profile"))
        self.assertEqual(payload["provider_id"], "antigravity-cli")
        self.assertEqual(
            [item["label"] for item in payload["limits"]],
            ["Gemini Models", "Claude and GPT models"],
        )
        gemini = payload["limits"][0]
        self.assertAlmostEqual(gemini["primary_window"]["used_percent"], 13.97252678871155)
        self.assertEqual(gemini["primary_window"]["limit_window_seconds"], 604800)
        self.assertEqual(gemini["primary_window"]["reset_after_seconds"], 505492)
        self.assertEqual(gemini["secondary_window"]["limit_window_seconds"], 18000)
        self.assertEqual(gemini["secondary_window"]["reset_after_seconds"], 10800)
        self.assertTrue(payload["limits"][1]["limit_reached"])
        serialized = json.dumps(payload)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("human-readable summary", serialized)
        self.assertNotIn("provider-owned copy", serialized)

    def test_missing_usage_groups_is_normalized(self) -> None:
        with self.assertRaises(ProviderUsageUnavailableError) as caught:
            read_antigravity_subscription_usage(
                "agy",
                runner=lambda *_args: json.dumps(
                    {"status": "SUCCESS", "command": {"name": "usage", "data": {}}}
                ),
            )

        self.assertEqual(caught.exception.reason, "usage_not_reported")

    def test_failed_usage_command_is_normalized(self) -> None:
        with self.assertRaises(ProviderUsageUnavailableError) as caught:
            read_antigravity_subscription_usage(
                "agy",
                runner=lambda *_args: json.dumps(
                    {"status": "ERROR", "error": "sensitive upstream detail"}
                ),
            )

        self.assertEqual(caught.exception.reason, "provider_unavailable")


if __name__ == "__main__":
    unittest.main()
