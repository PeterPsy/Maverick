from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarFreeTimeTest(unittest.TestCase):
    def test_find_free_time_returns_multiple_slots_inside_one_open_window(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "tool_name": "calendar_find_free_time",
                    "arguments": {
                        "start_after": "2026-05-22T09:00:00Z",
                        "end_before": "2026-05-22T11:00:00Z",
                        "duration_minutes": 30,
                        "limit": 3,
                    },
                },
            )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(
            [slot["startTime"] for slot in result["slots"]],
            ["2026-05-22T09:00:00Z", "2026-05-22T09:30:00Z", "2026-05-22T10:00:00Z"],
        )

    def test_list_events_uses_overlap_window_semantics(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            overnight = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Overnight deploy",
                        "startTime": "2026-05-22T23:00:00Z",
                        "endTime": "2026-05-23T01:00:00Z",
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
                    "arguments": {
                        "start_after": "2026-05-23T00:00:00Z",
                        "end_before": "2026-05-24T00:00:00Z",
                        "profile": "compact",
                    },
                },
            )

        self.assertEqual(overnight["status_code"], 201)
        self.assertEqual(listed["status_code"], 200)
        self.assertEqual([event["title"] for event in listed["events"]], ["Overnight deploy"])

    def test_move_event_can_use_first_free_strategy(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            original = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Customer call",
                        "startTime": "2026-05-22T08:00:00Z",
                        "endTime": "2026-05-22T08:30:00Z",
                        "attendees": ["Ana"],
                    },
                },
            )
            event_id = original["event"]["id"]
            run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Busy block",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T09:30:00Z",
                        "attendees": ["Ana"],
                    },
                },
            )
            moved = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_move_event",
                    "arguments": {
                        "id": event_id,
                        "expected_revision": original["event"]["revision"],
                        "move_strategy": "first_free",
                        "start_after": "2026-05-22T09:00:00Z",
                        "end_before": "2026-05-22T11:00:00Z",
                        "conflict_policy": "reject",
                    },
                },
            )

        self.assertEqual(moved["status_code"], 200)
        self.assertEqual(moved["event"]["startTime"], "2026-05-22T09:30:00Z")
        self.assertEqual(moved["event"]["endTime"], "2026-05-22T10:00:00Z")
        self.assertEqual(moved["availability"]["status"], "free")

    def test_first_free_move_preserves_event_duration(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            original = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Strategy review",
                        "startTime": "2026-05-22T08:00:00Z",
                        "endTime": "2026-05-22T09:00:00Z",
                        "attendees": ["Ana"],
                    },
                },
            )
            moved = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_move_event",
                    "arguments": {
                        "id": original["event"]["id"],
                        "expected_revision": original["event"]["revision"],
                        "move_strategy": "first_free",
                        "start_after": "2026-05-22T10:00:00Z",
                        "end_before": "2026-05-22T12:00:00Z",
                        "duration_minutes": 30,
                    },
                },
            )

        self.assertEqual(moved["status_code"], 200)
        self.assertEqual(moved["event"]["startTime"], "2026-05-22T10:00:00Z")
        self.assertEqual(moved["event"]["endTime"], "2026-05-22T11:00:00Z")

    def test_find_free_time_limit_error_reports_action_specific_maximum(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "tool_name": "calendar_find_free_time",
                    "arguments": {
                        "start_after": "2026-05-22T09:00:00Z",
                        "end_before": "2026-05-22T11:00:00Z",
                        "duration_minutes": 30,
                        "limit": 51,
                    },
                },
            )

        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["allowed_values"]["limit"]["maximum"], 50)

    def test_integer_validation_rejects_json_arrays_without_crashing(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "tool_name": "calendar_find_free_time",
                    "arguments": {
                        "start_after": "2026-05-22T09:00:00Z",
                        "end_before": "2026-05-22T11:00:00Z",
                        "duration_minutes": 30,
                        "limit": [],
                    },
                },
            )

        self.assertEqual(result["status_code"], 400)
        self.assertEqual(result["error"], "validation_error")
        self.assertEqual(result["detail"], "limit must be an integer between 1 and 50.")
