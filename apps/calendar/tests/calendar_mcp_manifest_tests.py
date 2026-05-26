from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarMcpManifestTest(unittest.TestCase):
    def test_mcp_manifest_and_event_tools_are_operational(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            manifest = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_operations_manifest",
                    "arguments": {},
                },
            )
            created = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Launch review",
                        "startTime": "2026-05-22T13:00:00Z",
                        "endTime": "2026-05-22T14:00:00Z",
                        "attendees": ["Ana"],
                        "tags": ["Launch"],
                    },
                },
            )
            slots = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_find_free_time",
                    "arguments": {
                        "start_after": "2026-05-22T12:00:00Z",
                        "end_before": "2026-05-22T15:00:00Z",
                        "duration_minutes": 30,
                    },
                },
            )
            listed = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_list_events",
                    "arguments": {"profile": "compact", "include_description": False},
                },
            )

        self.assertEqual(manifest["status_code"], 200)
        self.assertIn("calendar_create_event", [tool["name"] for tool in manifest["tools"]])
        self.assertEqual(created["status_code"], 201)
        self.assertTrue(created["event"]["id"].startswith("evt_"))
        self.assertEqual(slots["status_code"], 200)
        self.assertEqual(
            [slot["startTime"] for slot in slots["slots"]],
            [
                "2026-05-22T12:00:00Z",
                "2026-05-22T12:30:00Z",
                "2026-05-22T14:00:00Z",
                "2026-05-22T14:30:00Z",
            ],
        )
        self.assertEqual(listed["status_code"], 200)
        self.assertNotIn("description", listed["events"][0])

    def test_mcp_outputs_use_runtime_local_app_id(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            manifest = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "team-calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_operations_manifest",
                    "arguments": {},
                },
            )
            created = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "team-calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Aliased calendar event",
                        "startTime": "2026-05-22T15:00:00Z",
                        "endTime": "2026-05-22T16:00:00Z",
                    },
                },
            )
            event_id = created["event"]["id"]
            resolved = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "team-calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_reference_resolve",
                    "arguments": {"entity_id": event_id},
                },
            )

        self.assertEqual(manifest["app_id"], "team-calendar")
        self.assertEqual(created["app_id"], "team-calendar")
        self.assertEqual(created["app_events"][0]["owner_app_id"], "team-calendar")
        self.assertEqual(resolved["app_id"], "team-calendar")
        self.assertEqual(resolved["deep_link"], f"/app/team-calendar/events/{event_id}")
