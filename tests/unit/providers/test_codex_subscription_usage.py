"""Codex subscription usage adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from core.providers.errors import ProviderUsageUnavailableError
from core.providers.payloads import provider_subscription_usage_payload
from core.providers.provider_codex_usage import CODEX_USAGE_ENDPOINT, read_codex_subscription_usage


class CodexSubscriptionUsageTest(unittest.TestCase):
    def make_codex_home(self, *, access_token: str = "access-secret", account_id: str = "account-secret") -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": access_token, "account_id": account_id}}),
            encoding="utf-8",
        )
        return root

    def test_usage_parser_keeps_limits_and_redacts_authentication(self) -> None:
        captured: dict[str, object] = {}

        def transport(url: str, headers: dict[str, str], timeout: float):
            captured.update(url=url, headers=headers, timeout=timeout)
            return 200, {
                "plan_type": "pro",
                "rate_limit": {
                    "limit_reached": False,
                    "primary_window": {
                        "used_percent": 11,
                        "limit_window_seconds": 604800,
                        "reset_after_seconds": 467405,
                        "reset_at": 1787011169,
                    },
                    "secondary_window": None,
                },
                "additional_rate_limits": [
                    {
                        "limit_name": "GPT-5.3-Codex-Spark",
                        "metered_feature": "codex_bengalfox",
                        "rate_limit": {
                            "limit_reached": False,
                            "primary_window": {
                                "used_percent": 0,
                                "limit_window_seconds": 604800,
                                "reset_after_seconds": 467405,
                                "reset_at": 1787011169,
                            },
                        },
                    }
                ],
                "credits": {"balance": "0", "unlimited": False},
                "account_id": "must-not-leak",
                "email": "must-not-leak@example.com",
            }

        usage = read_codex_subscription_usage(
            self.make_codex_home(),
            transport=transport,
            now=datetime(2026, 8, 12, 16, 30, tzinfo=UTC),
        )
        payload = provider_subscription_usage_payload(usage)

        self.assertEqual(captured["url"], CODEX_USAGE_ENDPOINT)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer access-secret")
        self.assertEqual(captured["headers"]["ChatGPT-Account-ID"], "account-secret")
        self.assertEqual(payload["plan_type"], "pro")
        self.assertEqual([item["label"] for item in payload["limits"]], ["Codex", "GPT-5.3-Codex-Spark"])
        self.assertEqual(payload["limits"][0]["primary_window"]["used_percent"], 11.0)
        serialized = json.dumps(payload)
        self.assertNotIn("access-secret", serialized)
        self.assertNotIn("account-secret", serialized)
        self.assertNotIn("must-not-leak", serialized)

    def test_missing_login_reports_authentication_required(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        with self.assertRaises(ProviderUsageUnavailableError) as caught:
            read_codex_subscription_usage(Path(temporary.name), transport=lambda *_args: (200, {}))

        self.assertEqual(caught.exception.reason, "authentication_required")

    def test_authentication_failure_is_normalized(self) -> None:
        with self.assertRaises(ProviderUsageUnavailableError) as caught:
            read_codex_subscription_usage(
                self.make_codex_home(),
                transport=lambda *_args: (401, {"detail": "sensitive upstream error"}),
            )

        self.assertEqual(caught.exception.reason, "authentication_required")
