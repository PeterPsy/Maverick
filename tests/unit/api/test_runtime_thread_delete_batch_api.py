"""Focused API contract tests for runtime-thread batch deletion."""

from __future__ import annotations

from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.runtime_thread_delete_api import handle_thread_delete_batch
from core.api.session_api import RequestSession
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeThreadDeleteBatchApiTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_api_accepts_a_large_sidebar_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            thread_ids = [f"missing-thread-{index}" for index in range(165)]

            status, payload, _headers = self._invoke(
                app,
                path="/api/runtime/threads/delete-batch",
                method="POST",
                body={"thread_ids": thread_ids},
                cookie=cookie,
            )

            self.assertEqual(status, 200)
            self.assertEqual(payload["deleted_thread_ids"], [])
            self.assertEqual(
                payload["results"],
                [{"thread_id": thread_id, "status": "not_found"} for thread_id in thread_ids],
            )

    def test_preflight_reads_the_workspace_thread_catalog_once(self) -> None:
        runtime_store = SimpleNamespace(
            list_threads=Mock(return_value=[]),
            get_thread=Mock(side_effect=AssertionError("per-thread catalog lookup")),
            delete_threads=Mock(return_value=0),
        )
        state = SimpleNamespace(
            runtime_store=runtime_store,
            runtime_thread_event_bus=SimpleNamespace(publish=Mock()),
        )
        context = RequestSession(
            user=SimpleNamespace(user_id="user-1", platform_role="admin"),
            session=SimpleNamespace(session_id="browser-session"),
            workspace_id="default",
        )
        captured: dict[str, object] = {}

        body = handle_thread_delete_batch(
            state,
            context,
            "POST",
            {"thread_ids": [f"missing-thread-{index}" for index in range(165)]},
            lambda status, headers: captured.update(status=status, headers=headers),
            start_path=None,
        )

        self.assertIsNotNone(body)
        self.assertEqual(captured["status"], "200 OK")
        runtime_store.list_threads.assert_called_once_with("default")
        runtime_store.get_thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
