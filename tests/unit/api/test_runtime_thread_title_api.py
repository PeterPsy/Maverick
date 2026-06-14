from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.thread_title_jobs import thread_title_input_hash
from core.runtime.thread_titles import DEFAULT_THREAD_TITLE
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeThreadTitleApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_first_async_turn_marks_thread_title_pending_and_schedules_ai_title(self) -> None:
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
            message = "questo è un test per testare che il naming della chat con ai funzioni davvero"
            captured: dict[str, object] = {}

            def fake_submit_runtime_turn(*_args, **kwargs):
                session = kwargs["session"]
                now = datetime.now(timezone.utc)
                turn = RuntimeTurnRecord(
                    turn_id="turn-1",
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    status="queued",
                    input_text=kwargs["input_text"],
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                )
                kwargs["on_queued"](turn, [])
                return turn, []

            with patch.object(state.runtime_thread_event_bus, "publish", wraps=state.runtime_thread_event_bus.publish) as publish_thread, patch(
                "core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn
            ), patch("core.api.runtime_api.schedule_runtime_thread_title_generation") as schedule_title:
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "input_text": message,
                        "async": True,
                    },
                    cookie=cookie,
                )
                captured["schedule_call"] = schedule_title.call_args
                captured["published_events"] = [call.kwargs["event"] for call in publish_thread.call_args_list]

        self.assertEqual(status, 202)
        thread = payload["thread"]
        self.assertEqual(thread["title"], DEFAULT_THREAD_TITLE)
        self.assertTrue(thread["title_pending"])
        self.assertEqual(thread["title_source"], "pending")
        self.assertEqual(thread["title_generation_input_hash"], thread_title_input_hash(message))
        published_events = captured["published_events"]
        self.assertGreaterEqual(len(published_events), 2)
        created_thread = published_events[0]["thread"]
        self.assertEqual(created_thread["title"], DEFAULT_THREAD_TITLE)
        self.assertFalse(created_thread["title_pending"])
        self.assertEqual(created_thread["title_source"], "placeholder")
        self.assertTrue(all(event.get("thread", {}).get("title_source") != "deterministic" for event in published_events))
        self.assertEqual(published_events[-1]["thread"]["title_source"], "pending")
        schedule_call = captured["schedule_call"]
        self.assertIsNotNone(schedule_call)
        assert schedule_call is not None
        self.assertTrue(schedule_call.kwargs["thread"].title_pending)
        self.assertEqual(schedule_call.kwargs["input_text"], message)


if __name__ == "__main__":
    unittest.main()
