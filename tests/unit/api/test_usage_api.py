"""Administrative usage time-series API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.session_api import RequestSession
from core.api.usage_api import handle_usage_api
from core.shared.in_memory_collection import InMemoryCollection
from core.usage.models import UsageSampleRecord
from core.usage.store import UsageCollections, UsageDocumentStore


class UsageApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = UsageDocumentStore(
            UsageCollections(
                samples=InMemoryCollection(),
                buckets=InMemoryCollection(),
                quota_snapshots=InMemoryCollection(),
            )
        )
        self.store.save_sample_if_absent(
            UsageSampleRecord(
                sample_id="usage-1",
                workspace_id="default",
                root_session_id="runtime-root",
                session_id="runtime-root",
                turn_id="turn-1",
                provider_id="codex",
                model_id="gpt-test",
                source="test",
                semantics="incremental",
                token_accuracy="exact",
                context_accuracy="estimated",
                input_tokens=80,
                cached_input_tokens=10,
                cache_write_input_tokens=0,
                output_tokens=10,
                reasoning_output_tokens=0,
                total_tokens=100,
                reported_input_tokens=90,
                reported_cached_input_tokens=10,
                reported_cache_write_input_tokens=0,
                reported_output_tokens=10,
                reported_reasoning_output_tokens=0,
                reported_total_tokens=100,
                context_tokens=100,
                context_window_tokens=200,
                estimated_cost_microusd=None,
                observed_at=datetime.now(tz=UTC),
            )
        )

    def test_platform_admin_can_read_gap_filled_hourly_usage(self) -> None:
        status, payload = self.invoke(platform_role="admin", query="resolution=hour&periods=2")

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["workspace_id"], "default")
        self.assertEqual(payload["resolution"], "hour")
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["totals"]["total_tokens"], 100)
        self.assertEqual(
            payload["facets"],
            {"providers": [{"provider_id": "codex", "model_ids": ["gpt-test"]}]},
        )

    def test_non_admin_cannot_read_usage_history(self) -> None:
        status, payload = self.invoke(platform_role="member")

        self.assertEqual(status, "403 Forbidden")
        self.assertEqual(payload["error"], "usage_timeseries_forbidden")

    def test_invalid_resolution_is_rejected(self) -> None:
        status, payload = self.invoke(platform_role="admin", query="resolution=week")

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["error"], "usage_resolution_invalid")

    def invoke(self, *, platform_role: str, query: str = "") -> tuple[str, dict]:
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role=platform_role),
            session=SimpleNamespace(session_id="session-1"),
            workspace_id="default",
        )
        environ = {
            "PATH_INFO": "/api/usage/timeseries",
            "QUERY_STRING": query,
            "REQUEST_METHOD": "GET",
            "wsgi.input": BytesIO(b""),
            "CONTENT_LENGTH": "0",
            "CONTENT_TYPE": "application/json",
        }
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        with patch("core.api.usage_api.require_session", return_value=context):
            body = handle_usage_api(SimpleNamespace(usage_store=self.store), environ, start_response)

        assert body is not None
        return str(captured["status"]), json.loads(b"".join(body).decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
