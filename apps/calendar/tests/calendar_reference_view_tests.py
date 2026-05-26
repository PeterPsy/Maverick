from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarReferenceViewTest(unittest.TestCase):
    def test_cli_and_reference_surfaces_are_operational(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            manifest = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "arguments": {},
                },
            )
            created = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "arguments": {
                        "action": "create",
                        "title": "Referenceable event",
                        "startTime": "2026-05-22T15:00:00Z",
                        "endTime": "2026-05-22T16:00:00Z",
                    },
                },
            )
            event_id = created["event"]["id"]
            search = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar-reference",
                    "arguments": {"action": "references.search", "query": "Referenceable"},
                },
            )
            resolved = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar-reference",
                    "arguments": {"action": "references.resolve", "entity_id": event_id},
                },
            )
            summarized = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar-reference",
                    "arguments": {"action": "references.summarize", "entity_id": event_id},
                },
            )

        self.assertEqual(manifest["status_code"], 200)
        self.assertEqual(manifest["action"], "operations.manifest")
        self.assertEqual(created["status_code"], 201)
        self.assertEqual(search["status_code"], 200)
        self.assertEqual(search["results"][0]["entity_id"], event_id)
        self.assertEqual(search["results"][0]["app_page"], f"events/{event_id}")
        self.assertEqual(resolved["status_code"], 200)
        self.assertEqual(resolved["app_page"], f"events/{event_id}")
        self.assertEqual(resolved["reference"]["deep_link"], f"/app/calendar/events/{event_id}")
        self.assertEqual(summarized["status_code"], 200)
        self.assertEqual(summarized["safe_fields"]["id"], event_id)
        self.assertEqual(summarized["deep_link"], f"/app/calendar/events/{event_id}")

    def test_reference_resolve_missing_event_returns_tombstone(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            resolved = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "tool_name": "calendar_reference_resolve",
                    "arguments": {"entity_type": "event", "entity_id": "evt_missing"},
                },
            )
            summarized = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "tool_name": "calendar_reference_summarize",
                    "arguments": {"entity_type": "event", "entity_id": "evt_missing"},
                },
            )

        self.assertEqual(resolved["status_code"], 200)
        self.assertFalse(resolved["exists"])
        self.assertEqual(resolved["entity_type"], "event")
        self.assertEqual(resolved["entity_id"], "evt_missing")
        self.assertEqual(summarized["status_code"], 200)
        self.assertFalse(summarized["exists"])
        self.assertEqual(summarized["summary"], "")

    def test_mcp_reference_manifest_and_view_state_are_operational(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Launch planning",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T10:00:00Z",
                        "tags": ["Launch"],
                    },
                },
            )
            event_id = created["event"]["id"]
            manifest = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_reference_manifest",
                    "arguments": {},
                },
            )
            filtered = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_set_view_filter",
                    "arguments": {
                        "query": "launch",
                        "start_after": "2026-05-22T00:00:00Z",
                        "end_before": "2026-05-29T00:00:00Z",
                        "tags": ["Launch"],
                        "conflicts_only": True,
                    },
                },
            )
            read_filter = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_view_filter",
                    "arguments": {},
                },
            )
            view_state = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_set_custom_view",
                    "arguments": {"title": "Launch week", "entity_ids": [event_id]},
                },
            )
            refined_custom = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "arguments": {
                        "action": "set_view_filter",
                        "query": "launch",
                        "preserve_custom": True,
                    },
                },
            )
            cleared = run_json_entrypoint(
                app_root / "cli" / "app_cli.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "command_id": "app.calendar.calendar",
                    "arguments": {"action": "clear_custom_view"},
                },
            )

        self.assertEqual(manifest["status_code"], 200)
        self.assertEqual(manifest["entity_types"][0]["entity_type"], "event")
        self.assertTrue(manifest["entity_types"][0]["deep_link_supported"])
        self.assertEqual(filtered["status_code"], 200)
        self.assertEqual(filtered["view_state"]["mode"], "filter")
        self.assertEqual(filtered["view_state"]["query"], "launch")
        self.assertEqual(filtered["view_state"]["start_after"], "2026-05-22T00:00:00Z")
        self.assertEqual(filtered["view_state"]["tags"], ["Launch"])
        self.assertTrue(filtered["view_state"]["conflicts_only"])
        self.assertEqual(read_filter["status_code"], 200)
        self.assertEqual(read_filter["view_state"]["mode"], "filter")
        self.assertEqual(read_filter["view_state"]["end_before"], "2026-05-29T00:00:00Z")
        self.assertEqual(view_state["status_code"], 200)
        self.assertEqual(view_state["view_state"]["mode"], "custom")
        self.assertEqual(view_state["view_state"]["references"][0]["app_page"], f"events/{event_id}")
        self.assertEqual(view_state["app_events"][0]["resource"], "view-state")
        self.assertEqual(refined_custom["status_code"], 200)
        self.assertEqual(refined_custom["view_state"]["mode"], "custom")
        self.assertEqual(refined_custom["view_state"]["entity_ids"], [event_id])
        self.assertEqual(refined_custom["view_state"]["query"], "launch")
        self.assertEqual(cleared["status_code"], 200)
        self.assertEqual(cleared["view_state"]["mode"], "default")
        self.assertEqual(cleared["app_events"][0]["resource"], "view-state")

    def test_custom_view_rejects_missing_event_references(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            missing = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_set_custom_view",
                    "arguments": {"title": "Missing event", "entity_ids": ["evt_missing"]},
                },
            )
            read_filter = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_view_filter",
                    "arguments": {},
                },
            )

        self.assertEqual(missing["status_code"], 404)
        self.assertEqual(missing["error"], "not_found")
        self.assertIn("evt_missing", missing["detail"])
        self.assertEqual(read_filter["view_state"]["mode"], "default")
