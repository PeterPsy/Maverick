from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarBackendApiTest(unittest.TestCase):
    def test_backend_crud_persists_events(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "event": {
                            "title": "Team Standup",
                            "description": "Daily sync",
                            "startTime": "2026-05-21T09:00:00Z",
                            "endTime": "2026-05-21T09:30:00Z",
                            "color": "blue",
                            "category": "Meeting",
                            "tags": ["Work", "Team"],
                        },
                    },
                },
            )
            event_id = created["json"]["event"]["id"]
            updated = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "update",
                        "id": event_id,
                        "expected_revision": created["json"]["event"]["revision"],
                        "event": {
                            "title": "Team Standup",
                            "startTime": "2026-05-21T10:00:00Z",
                            "endTime": "2026-05-21T10:30:00Z",
                        },
                    },
                },
            )
            listed = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {"action": "list"},
                },
            )

        self.assertEqual(created["status_code"], 201)
        self.assertEqual(updated["status_code"], 200)
        self.assertEqual(updated["json"]["event"]["startTime"], "2026-05-21T10:00:00Z")
        self.assertEqual(listed["status_code"], 200)
        self.assertEqual(listed["json"]["events"][0]["id"], event_id)
        self.assertEqual(listed["json"]["events"][0]["tags"], ["Work", "Team"])

    def test_backend_validation_errors_are_json_responses(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "body": {"action": "create", "event": {"title": ""}},
                },
            )

        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["json"]["error"], "validation_error")
        self.assertIn("title", result["json"]["detail"])

    def test_backend_generates_ids_and_rejects_invalid_fields(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            created = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "event": {
                            "id": "client-controlled",
                            "title": "Planning",
                            "startTime": "2026-05-21T09:00:00Z",
                            "endTime": "2026-05-21T10:00:00Z",
                            "color": "blue",
                        },
                    },
                },
            )
            invalid = run_json_entrypoint(
                app_root / "backend" / "app_backend.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "body": {
                        "action": "create",
                        "event": {
                            "title": "Bad color",
                            "startTime": "2026-05-21T09:00:00Z",
                            "endTime": "2026-05-21T10:00:00Z",
                            "color": "chartreuse",
                        },
                    },
                },
            )

        self.assertEqual(created["status_code"], 201)
        self.assertNotEqual(created["json"]["event"]["id"], "client-controlled")
        self.assertTrue(created["json"]["event"]["id"].startswith("evt_"))
        self.assertEqual(invalid["status_code"], 400)
        self.assertIn("color", invalid["json"]["detail"])
