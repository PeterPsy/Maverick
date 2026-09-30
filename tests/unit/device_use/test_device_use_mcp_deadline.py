from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from core.runtime.runtime_cli_wrapper import runtime_device_use_mcp_wrapper_source


class DeviceUseMCPDeadlineTestCase(unittest.TestCase):
    def test_generated_mcp_client_does_not_cut_off_long_media_invocations(self):
        namespace = {"__name__": "device_use_wrapper_test"}
        exec(compile(runtime_device_use_mcp_wrapper_source(), "device_use_wrapper", "exec"), namespace)
        for tool, action, expected in (
            ("mac_computer", "observe", 195.0),
            ("mac_project", "sample_frames", 315.0),
            ("mac_project", "transcribe_media", 915.0),
            ("mac_project", "prepare_subclip", 915.0),
            ("mac_project", "run_project_script", 1215.0),
        ):
            with self.subTest(action=action), patch(
                "urllib.request.urlopen",
                return_value=io.BytesIO(b'{"result":{"success":true,"contentItems":[{"text":"done"}]}}'),
            ) as opened:
                result = namespace["call_tool"](tool, {"action": action})
                self.assertEqual(opened.call_args.kwargs["timeout"], expected)
                self.assertFalse(result["isError"])
                self.assertEqual(result["content"], [{"type": "text", "text": "done"}])

    def test_failed_media_call_is_not_retried(self):
        namespace = {"__name__": "device_use_wrapper_test"}
        exec(compile(runtime_device_use_mcp_wrapper_source(), "device_use_wrapper", "exec"), namespace)
        with patch("urllib.request.urlopen", side_effect=TimeoutError("transport lost")) as opened:
            result = namespace["call_tool"]("mac_project", {"action": "prepare_subclip"})
        self.assertTrue(result["isError"])
        opened.assert_called_once()
