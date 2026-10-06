from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import handle_action, mcp_result_for_tool


class BrowserReadingTests(unittest.TestCase):
    def test_rendered_reads_require_an_existing_authorized_session(self) -> None:
        with TemporaryDirectory() as folder, patch("service.call_broker_action") as broker:
            status, result = mcp_result_for_tool(
                Path(folder), "browser_read_content", {"session_id": "unknown"}
            )
        self.assertEqual(status, 400)
        self.assertEqual(result["field"], "session_id")
        broker.assert_not_called()

    def test_fixed_reading_tools_reject_code_selectors_and_out_of_bounds_arguments(self) -> None:
        cases = [
            ("browser_read_content", {"script": "document.cookie"}, "script"),
            ("browser_read_content", {"max_chars": 100001}, "max_chars"),
            ("browser_read_content", {"max_items": True}, "max_items"),
            ("browser_scroll", {"direction": []}, "direction"),
            ("browser_scroll", {"steps": 6}, "steps"),
            ("browser_scroll", {"selector": "input"}, "selector"),
            ("browser_video_frame", {"time_seconds": None}, "time_seconds"),
            ("browser_video_frame", {"time_seconds": float("inf")}, "time_seconds"),
            ("browser_video_frame", {"video_index": -1}, "video_index"),
        ]
        with TemporaryDirectory() as folder, patch("service.call_broker_action") as broker:
            for tool, arguments, field in cases:
                with self.subTest(tool=tool, arguments=arguments):
                    status, result = mcp_result_for_tool(
                        Path(folder), tool, {"session_id": "unknown", **arguments}
                    )
                    self.assertEqual((status, result["field"]), (400, field))
        broker.assert_not_called()

    def test_new_observations_share_controller_session_authority_and_broker_handoff(self) -> None:
        def response(action, _body):
            return SimpleNamespace(status_code=200, payload={"session_id": "session-one", "action": action})

        cases = [
            ("browser_read_content", {"max_chars": 2000}, "content.read"),
            ("browser_scroll", {"steps": 2, "direction": "up"}, "scroll"),
            ("browser_video_frame", {"time_seconds": 1.5}, "video.frame"),
        ]
        with TemporaryDirectory() as folder, patch("service.call_broker_action", side_effect=response) as broker:
            root = Path(folder)
            handle_action(root, {"action": "session.create"}, workspace_id="test-workspace")
            for tool, arguments, action in cases:
                status, result = mcp_result_for_tool(
                    root, tool, {"session_id": "session-one", **arguments}, workspace_id="test-workspace"
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["action"], action)
                forwarded = broker.call_args.args[1]
                self.assertEqual(forwarded["mode"], "read_only")
                self.assertEqual(forwarded["workspace_id"], "test-workspace")
                self.assertEqual(forwarded["policy_context"], {"allow_admin_dev_targets": False})

    def test_reading_cannot_observe_an_admin_dev_session_as_an_unprivileged_caller(self) -> None:
        response = SimpleNamespace(status_code=201, payload={"session_id": "admin-session"})
        with TemporaryDirectory() as folder, patch("service.call_broker_action", return_value=response) as broker:
            root = Path(folder)
            handle_action(root, {"action": "session.create", "mode": "maverick_dev_inspector"}, platform_role="admin")
            broker.reset_mock()
            status, result = mcp_result_for_tool(root, "browser_read_content", {"session_id": "admin-session"})
        self.assertEqual(status, 403)
        self.assertEqual(result["error"], "policy_denied")
        broker.assert_not_called()
