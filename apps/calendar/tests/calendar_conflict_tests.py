from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint

class CalendarConflictTest(unittest.TestCase):
    def test_conflict_policy_reject_blocks_overlapping_event(self) -> None:
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
                        "title": "Planning",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T10:00:00Z",
                        "attendees": ["Ana"],
                    },
                },
            )
            rejected = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Overlap",
                        "startTime": "2026-05-22T09:30:00Z",
                        "endTime": "2026-05-22T10:30:00Z",
                        "attendees": ["Ana"],
                        "conflict_policy": "reject",
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

        self.assertEqual(first["status_code"], 201)
        self.assertEqual(rejected["status_code"], 409)
        self.assertEqual(rejected["error"], "calendar_conflict")
        self.assertEqual(rejected["conflicts"][0]["title"], "Planning")
        self.assertEqual(listed["status_code"], 200)
        self.assertEqual(len(listed["events"]), 1)

    def test_attendee_availability_matching_is_case_insensitive(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Ana planning",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T10:00:00Z",
                        "attendees": ["Ana"],
                    },
                },
            )
            availability = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_check_availability",
                    "arguments": {
                        "startTime": "2026-05-22T09:30:00Z",
                        "endTime": "2026-05-22T10:30:00Z",
                        "attendee": "ana",
                    },
                },
            )
            rejected = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Lowercase overlap",
                        "startTime": "2026-05-22T09:45:00Z",
                        "endTime": "2026-05-22T10:15:00Z",
                        "attendees": ["ana"],
                        "conflict_policy": "reject",
                    },
                },
            )

        self.assertEqual(availability["status_code"], 200)
        self.assertFalse(availability["available"])
        self.assertEqual(availability["conflicts"][0]["title"], "Ana planning")
        self.assertEqual(rejected["status_code"], 409)
        self.assertEqual(rejected["conflicts"][0]["title"], "Ana planning")

    def test_availability_and_warn_policy_report_conflicts(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Design review",
                        "startTime": "2026-05-22T13:00:00Z",
                        "endTime": "2026-05-22T14:00:00Z",
                        "attendees": ["Bea"],
                    },
                },
            )
            availability = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_check_availability",
                    "arguments": {
                        "startTime": "2026-05-22T13:30:00Z",
                        "endTime": "2026-05-22T14:30:00Z",
                        "attendees": ["Bea"],
                    },
                },
            )
            warned = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Follow-up",
                        "startTime": "2026-05-22T13:45:00Z",
                        "endTime": "2026-05-22T14:15:00Z",
                        "attendees": ["Bea"],
                        "conflict_policy": "warn",
                    },
                },
            )

        self.assertEqual(availability["status_code"], 200)
        self.assertFalse(availability["available"])
        self.assertEqual(availability["conflicts"][0]["title"], "Design review")
        self.assertEqual(warned["status_code"], 201)
        self.assertEqual(warned["availability"]["status"], "conflicting")
        self.assertEqual(warned["warnings"][0]["type"], "calendar_conflict")

    def test_cancelled_events_do_not_block_availability_or_free_time(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            cancelled = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Cancelled hold",
                        "startTime": "2026-05-22T10:00:00Z",
                        "endTime": "2026-05-22T10:30:00Z",
                        "attendees": ["Bea"],
                        "status": "cancelled",
                    },
                },
            )
            availability = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_check_availability",
                    "arguments": {
                        "startTime": "2026-05-22T10:00:00Z",
                        "endTime": "2026-05-22T10:30:00Z",
                        "attendees": ["Bea"],
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
                        "start_after": "2026-05-22T10:00:00Z",
                        "end_before": "2026-05-22T11:00:00Z",
                        "duration_minutes": 30,
                        "attendees": ["Bea"],
                        "limit": 1,
                    },
                },
            )

        self.assertEqual(cancelled["status_code"], 201)
        self.assertEqual(cancelled["event"]["status"], "cancelled")
        self.assertTrue(availability["available"])
        self.assertEqual(availability["conflicts"], [])
        self.assertEqual(slots["slots"][0]["startTime"], "2026-05-22T10:00:00Z")

    def test_cancelled_candidate_does_not_trigger_reject_conflict(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Busy planning",
                        "startTime": "2026-05-22T09:00:00Z",
                        "endTime": "2026-05-22T10:00:00Z",
                        "attendees": ["Ana"],
                    },
                },
            )
            cancelled = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Cancelled overlap",
                        "startTime": "2026-05-22T09:30:00Z",
                        "endTime": "2026-05-22T10:30:00Z",
                        "attendees": ["Ana"],
                        "status": "cancelled",
                        "conflict_policy": "reject",
                    },
                },
            )

        self.assertEqual(cancelled["status_code"], 201)
        self.assertEqual(cancelled["event"]["status"], "cancelled")
        self.assertEqual(cancelled["availability"]["status"], "free")
