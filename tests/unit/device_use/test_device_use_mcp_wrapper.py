"""Real stdio discovery of the native planner tool projection."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from core.runtime.runtime_cli_wrapper import write_runtime_device_use_mcp_wrapper


class DeviceUseMcpWrapperTests(unittest.TestCase):
    def test_device_use_mcp_wrapper_stdio_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wrapper_path = Path(temp_dir) / "maverick-device-use-mcp"
            write_runtime_device_use_mcp_wrapper(wrapper_path)
            self.assertTrue(wrapper_path.exists())
            self.assertTrue(os.access(wrapper_path, os.X_OK))

            input_data = (
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                + "\n"
                + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                + "\n"
            )
            proc = subprocess.run(
                [sys.executable, str(wrapper_path)],
                input=input_data,
                capture_output=True,
                text=True,
                env={**os.environ, "MAVERICK_API_BASE": "http://127.0.0.1:1",
                     "MAVERICK_RUNTIME_API_TOKEN": ""},
                timeout=5,
            )
            self.assertEqual(proc.returncode, 0)
            lines = [json.loads(line) for line in proc.stdout.strip().split("\n") if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "maverick-device-use-mcp")
            tool_names = [t["name"] for t in lines[1]["result"]["tools"]]
            self.assertIn("mac_computer", tool_names)
            self.assertIn("mac_peekaboo", tool_names)
            self.assertIn("mac_calendar", tool_names)
            self.assertIn("mac_project", tool_names)
            self.assertIn("computer_interact", tool_names)
            peekaboo = next(tool for tool in lines[1]["result"]["tools"] if tool["name"] == "mac_peekaboo")
            self.assertNotIn("click", peekaboo["inputSchema"]["properties"]["action"]["enum"])
