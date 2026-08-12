"""Provider subscription usage API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.provider_api import handle_provider_api
from core.api.session_api import RequestSession
from core.providers.models import ProviderSubscriptionUsage, ProviderUsageLimit, ProviderUsageWindow


class ProviderUsageApiTest(unittest.TestCase):
    def test_admin_can_read_redaction_safe_subscription_usage(self) -> None:
        usage = ProviderSubscriptionUsage(
            provider_id="codex",
            provider_label="Codex",
            available=True,
            fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
            plan_type="pro",
            limits=[
                ProviderUsageLimit(
                    limit_id="codex",
                    label="Codex",
                    limit_reached=False,
                    primary_window=ProviderUsageWindow(used_percent=11, limit_window_seconds=604800),
                )
            ],
        )
        with patch("core.api.provider_api.read_workspace_provider_subscription_usage", return_value=[usage]):
            status, payload = self.invoke(platform_role="admin")

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["workspace_id"], "default")
        self.assertEqual(payload["items"][0]["limits"][0]["primary_window"]["used_percent"], 11)
        self.assertNotIn("token", json.dumps(payload).lower())
        self.assertNotIn("account_id", json.dumps(payload).lower())

    def test_non_admin_cannot_read_subscription_usage(self) -> None:
        status, payload = self.invoke(platform_role="member")

        self.assertEqual(status, "403 Forbidden")
        self.assertEqual(payload["error"], "provider_usage_forbidden")

    def invoke(self, *, platform_role: str) -> tuple[str, dict]:
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role=platform_role),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        environ = {
            "PATH_INFO": "/api/providers/usage",
            "QUERY_STRING": "",
            "REQUEST_METHOD": "GET",
            "wsgi.input": BytesIO(b""),
            "CONTENT_LENGTH": "0",
            "CONTENT_TYPE": "application/json",
        }
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        state = SimpleNamespace(provider_store=object())
        with patch("core.api.provider_api.require_session", return_value=context):
            body = handle_provider_api(state, environ, start_response)

        assert body is not None
        return str(captured["status"]), json.loads(b"".join(body).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
