from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarMcpRevisionTest(unittest.TestCase):
    def test_create_event_is_idempotent_by_idempotency_key(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            payload = {
                "title": "Idempotent planning",
                "startTime": "2026-05-22T09:00:00Z",
                "endTime": "2026-05-22T10:00:00Z",
                "idempotency_key": "planning-2026-05-22",
            }
            first = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": payload,
                },
            )
            replay = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": payload,
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
                    "arguments": {},
                },
            )

        self.assertEqual(first["status_code"], 201)
        self.assertEqual(replay["status_code"], 200)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(replay["event"]["id"], first["event"]["id"])
        self.assertNotIn("app_events", replay)
        self.assertEqual(len(listed["events"]), 1)

    def test_idempotency_key_is_create_only(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            first = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Original event",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T10:00:00Z",
                    },
                },
            )
            rejected_update = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_update_event",
                    "arguments": {
                        "id": first["event"]["id"],
                        "expected_revision": 1,
                        "idempotency_key": "poisoned-key",
                    },
                },
            )
            second = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Second event",
                        "startTime": "2026-05-23T09:00:00Z",
                        "endTime": "2026-05-23T10:00:00Z",
                        "idempotency_key": "poisoned-key",
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
                    "arguments": {},
                },
            )

        self.assertEqual(rejected_update["status_code"], 400)
        self.assertEqual(rejected_update["error"], "validation_error")
        self.assertIn("create-only", rejected_update["detail"])
        self.assertEqual(second["status_code"], 201)
        self.assertFalse(second.get("idempotent_replay", False))
        self.assertNotEqual(second["event"]["id"], first["event"]["id"])
        self.assertEqual(len(listed["events"]), 2)

    def test_expected_revision_blocks_stale_update_and_delete(self) -> None:
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
                        "title": "Revisioned event",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T10:00:00Z",
                    },
                },
            )
            event_id = created["event"]["id"]
            missing_revision_update = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_update_event",
                    "arguments": {
                        "id": event_id,
                        "title": "Unrevisioned update",
                    },
                },
            )
            updated = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_update_event",
                    "arguments": {
                        "id": event_id,
                        "title": "Revisioned event v2",
                        "expected_revision": 1,
                    },
                },
            )
            stale_update = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_update_event",
                    "arguments": {
                        "id": event_id,
                        "title": "Stale update",
                        "expected_revision": 1,
                    },
                },
            )
            stale_delete = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_delete_event",
                    "arguments": {"id": event_id, "expected_revision": 1},
                },
            )
            deleted = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_delete_event",
                    "arguments": {"id": event_id, "expected_revision": 2},
                },
            )

        self.assertEqual(missing_revision_update["status_code"], 400)
        self.assertEqual(missing_revision_update["error"], "validation_error")
        self.assertIn("expected_revision", missing_revision_update["detail"])
        self.assertEqual(updated["status_code"], 200)
        self.assertEqual(updated["event"]["revision"], 2)
        self.assertEqual(stale_update["status_code"], 409)
        self.assertEqual(stale_update["error"], "revision_conflict")
        self.assertEqual(stale_update["expected_revision"], 1)
        self.assertEqual(stale_update["actual_revision"], 2)
        self.assertEqual(stale_update["current_event"]["id"], event_id)
        self.assertEqual(stale_delete["status_code"], 409)
        self.assertEqual(stale_delete["error"], "revision_conflict")
        self.assertEqual(deleted["status_code"], 200)
        self.assertTrue(deleted["deleted"])
