from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.shared.entrypoints import run_json_entrypoint


class CalendarEventModelTest(unittest.TestCase):
    def test_event_model_includes_orchestration_metadata(self) -> None:
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
                        "title": "Launch rehearsal",
                        "startTime": "2026-05-22T14:00:00-04:00",
                        "endTime": "2026-05-22T15:00:00-04:00",
                        "timezone": "America/New_York",
                        "location": "Demo room",
                        "organizer": "Ana",
                        "all_day": False,
                        "source": "agent",
                        "external_refs": {
                            "crm_deal": "deal_123",
                            "calendarAccountId": "ana@example.com",
                            "calendarAccountLabel": "Ana Work",
                            "calendarConnectionId": "cal_conn_work",
                            "providerCalendarId": "primary",
                            "providerEventId": "google_evt_123",
                            "htmlLink": "https://calendar.google.com/event?eid=abc",
                            "etag": "etag-123",
                            "iCalUID": "ical-123@example.com",
                        },
                        "recurrence": {"frequency": "weekly", "count": 2},
                        "reminders": [{"minutes_before": 15, "method": "popup"}],
                        "idempotency_key": "launch-rehearsal-2026-05-22",
                    },
                },
            )
            event_id = created["event"]["id"]
            created_at = created["event"]["created_at"]
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
                        "expected_revision": 1,
                        "location": "Main demo room",
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
                    "arguments": {"profile": "compact"},
                },
            )

        self.assertEqual(created["status_code"], 201)
        self.assertEqual(created["event"]["startTime"], "2026-05-22T18:00:00Z")
        self.assertEqual(created["event"]["endTime"], "2026-05-22T19:00:00Z")
        self.assertEqual(created["event"]["timezone"], "America/New_York")
        self.assertEqual(created["event"]["location"], "Demo room")
        self.assertEqual(created["event"]["organizer"], "Ana")
        self.assertFalse(created["event"]["all_day"])
        self.assertEqual(created["event"]["revision"], 1)
        self.assertEqual(created["event"]["source"], "agent")
        self.assertEqual(created["event"]["external_refs"]["crm_deal"], "deal_123")
        self.assertEqual(created["event"]["external_refs"]["calendar_account_id"], "ana@example.com")
        self.assertEqual(created["event"]["external_refs"]["calendar_account_label"], "Ana Work")
        self.assertEqual(created["event"]["external_refs"]["calendar_connection_id"], "cal_conn_work")
        self.assertEqual(created["event"]["external_refs"]["provider_calendar_id"], "primary")
        self.assertEqual(created["event"]["external_refs"]["provider_event_id"], "google_evt_123")
        self.assertEqual(created["event"]["external_refs"]["html_link"], "https://calendar.google.com/event?eid=abc")
        self.assertEqual(created["event"]["external_refs"]["etag"], "etag-123")
        self.assertEqual(created["event"]["external_refs"]["ical_uid"], "ical-123@example.com")
        self.assertEqual(created["event"]["recurrence"], {"count": 2, "frequency": "weekly"})
        self.assertEqual(created["event"]["reminders"], [{"method": "popup", "minutes_before": 15}])
        self.assertEqual(created["event"]["idempotency_key"], "launch-rehearsal-2026-05-22")
        self.assertIn("created_at", created["event"])
        self.assertIn("updated_at", created["event"])
        self.assertEqual(updated["status_code"], 200)
        self.assertEqual(updated["event"]["created_at"], created_at)
        self.assertEqual(updated["event"]["revision"], 2)
        self.assertEqual(updated["event"]["location"], "Main demo room")
        self.assertEqual(listed["status_code"], 200)
        self.assertEqual(listed["events"][0]["timezone"], "America/New_York")
        self.assertEqual(listed["events"][0]["location"], "Main demo room")
        self.assertEqual(listed["events"][0]["revision"], 2)

    def test_legacy_events_are_normalized_with_phase_7_defaults(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            data_root.mkdir(parents=True)
            (data_root / "state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "events": [
                            {
                                "id": "evt_legacy",
                                "title": "Legacy event",
                                "startTime": "2026-05-22T09:00:00Z",
                                "endTime": "2026-05-22T10:00:00Z",
                                "color": "blue",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
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
            health = run_json_entrypoint(
                app_root / "hooks" / "health_check.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                },
            )
            migrated = run_json_entrypoint(
                app_root / "hooks" / "migrate.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                },
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        event = listed["json"]["events"][0]
        self.assertEqual(listed["status_code"], 200)
        self.assertEqual(event["timezone"], "UTC")
        self.assertEqual(event["location"], "")
        self.assertEqual(event["organizer"], "")
        self.assertFalse(event["all_day"])
        self.assertEqual(event["created_at"], "2026-05-22T09:00:00Z")
        self.assertEqual(event["updated_at"], "2026-05-22T09:00:00Z")
        self.assertEqual(event["revision"], 1)
        self.assertEqual(event["source"], "calendar")
        self.assertEqual(event["external_refs"], {})
        self.assertEqual(event["recurrence"], {})
        self.assertEqual(event["reminders"], [])
        self.assertEqual(event["idempotency_key"], "")
        self.assertEqual(health["schema_version"], "3")
        self.assertEqual(health["connection_count"], 0)
        self.assertEqual(health["calendar_count"], 0)
        self.assertEqual(health["sync_cursor_count"], 0)
        self.assertEqual(migrated["schema_version"], "3")
        self.assertEqual(persisted["schema_version"], "3")
        self.assertEqual(persisted["view_filter"]["schema_version"], "3")
        self.assertEqual(persisted["connections"], [])
        self.assertEqual(persisted["calendars"], [])
        self.assertEqual(persisted["sync_state"], [])
        persisted_event = persisted["events"][0]
        self.assertEqual(persisted_event["timezone"], "UTC")
        self.assertEqual(persisted_event["created_at"], "2026-05-22T09:00:00Z")
        self.assertEqual(persisted_event["updated_at"], "2026-05-22T09:00:00Z")
        self.assertEqual(persisted_event["revision"], 1)
        self.assertEqual(persisted_event["source"], "calendar")
        self.assertEqual(persisted_event["external_refs"], {})
        self.assertEqual(persisted_event["recurrence"], {})
        self.assertEqual(persisted_event["reminders"], [])
        self.assertEqual(persisted_event["idempotency_key"], "")

    def test_naive_event_timestamps_are_interpreted_in_event_timezone(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            created = run_json_entrypoint(
                app_root / "mcp" / "server.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(Path(temp_dir) / "data"),
                    "tool_name": "calendar_create_event",
                    "arguments": {
                        "title": "Local planning",
                        "startTime": "2026-05-22T14:00:00",
                        "endTime": "2026-05-22T15:00:00",
                        "timezone": "America/New_York",
                    },
                },
            )

        self.assertEqual(created["status_code"], 201)
        self.assertEqual(created["event"]["timezone"], "America/New_York")
        self.assertEqual(created["event"]["startTime"], "2026-05-22T18:00:00Z")
        self.assertEqual(created["event"]["endTime"], "2026-05-22T19:00:00Z")

    def test_google_calendar_storage_records_are_normalized_without_secret_values(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            data_root.mkdir(parents=True)
            (data_root / "state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "2",
                        "events": [],
                        "connections": [
                            {
                                "id": "cal_conn_work",
                                "provider": "google",
                                "calendarAccountId": "ana@example.com",
                                "calendarAccountLabel": "Ana Work",
                                "status": "connected",
                                "scopes": ["https://www.googleapis.com/auth/calendar.events"],
                                "createdAt": "2026-05-22T09:00:00Z",
                            }
                        ],
                        "calendars": [
                            {
                                "connectionId": "cal_conn_work",
                                "providerCalendarId": "primary",
                                "summary": "Work",
                                "timeZone": "America/New_York",
                                "primary": True,
                                "etag": "calendar-etag",
                            }
                        ],
                        "syncState": [
                            {
                                "connectionId": "cal_conn_work",
                                "providerCalendarId": "primary",
                                "syncToken": "cursor-001",
                                "status": "ok",
                                "lastSyncAt": "2026-05-22T10:00:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            migrated = run_json_entrypoint(
                app_root / "hooks" / "migrate.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                },
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(migrated["schema_version"], "3")
        self.assertEqual(persisted["schema_version"], "3")
        self.assertEqual(persisted["connections"][0]["resource_type"], "calendar_connection")
        self.assertEqual(persisted["connections"][0]["account_id"], "ana@example.com")
        self.assertEqual(persisted["connections"][0]["account_label"], "Ana Work")
        self.assertEqual(
            persisted["connections"][0]["token_resource"],
            {
                "logical_name": "google-calendar-refresh-token",
                "resource_type": "calendar_connection",
                "resource_id": "cal_conn_work",
            },
        )
        self.assertNotIn("refresh_token", persisted["connections"][0])
        self.assertEqual(persisted["calendars"][0]["connection_id"], "cal_conn_work")
        self.assertEqual(persisted["calendars"][0]["provider_calendar_id"], "primary")
        self.assertEqual(persisted["calendars"][0]["timezone"], "America/New_York")
        self.assertEqual(persisted["sync_state"][0]["connection_id"], "cal_conn_work")
        self.assertEqual(persisted["sync_state"][0]["provider_calendar_id"], "primary")
        self.assertEqual(persisted["sync_state"][0]["sync_token"], "cursor-001")

    def test_install_hook_creates_default_view_state(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            installed = run_json_entrypoint(
                app_root / "hooks" / "install.py",
                cwd=app_root,
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": str(data_root),
                },
            )
            state = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertTrue(installed["ok"])
        self.assertEqual(installed["schema_version"], "3")
        self.assertEqual(state["schema_version"], "3")
        self.assertEqual(state["view_filter"]["mode"], "default")
        self.assertEqual(state["connections"], [])
        self.assertEqual(state["calendars"], [])
        self.assertEqual(state["sync_state"], [])
        self.assertFalse(state["view_filter"]["conflicts_only"])
