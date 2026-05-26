from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarAgentPayloadTest(unittest.TestCase):
    def test_agent_list_surfaces_default_to_bounded_compact_payloads(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            data_root.mkdir(parents=True)
            events = [
                {
                    "id": f"evt_seed_{index:03d}",
                    "title": f"Seed {index:03d}",
                    "description": "Hidden in compact payloads",
                    "startTime": f"2026-05-{22 + (index // 24):02d}T{index % 24:02d}:{(index % 2) * 30:02d}:00Z",
                    "endTime": f"2026-05-{22 + (index // 24):02d}T{index % 24:02d}:{((index % 2) * 30) + 20:02d}:00Z",
                    "color": "blue",
                    "category": "Meeting",
                    "attendees": [],
                    "tags": [],
                }
                for index in range(55)
            ]
            (data_root / "state.json").write_text(json.dumps({"schema_version": "1", "events": events}), encoding="utf-8")
            mcp_list = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_list_events",
                    "arguments": {},
                },
            )
            cli_alias_list = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "arguments": {"action": "events.list"},
                },
            )

        self.assertEqual(mcp_list["status_code"], 200)
        self.assertEqual(mcp_list["content_profile"], "compact")
        self.assertEqual(len(mcp_list["events"]), 50)
        self.assertEqual(mcp_list["pagination"]["limit"], 50)
        self.assertTrue(mcp_list["pagination"]["has_more"])
        self.assertNotIn("description", mcp_list["events"][0])
        self.assertEqual(cli_alias_list["status_code"], 200)
        self.assertEqual(cli_alias_list["content_profile"], "compact")
        self.assertEqual(len(cli_alias_list["events"]), 50)
        self.assertNotIn("description", cli_alias_list["events"][0])
