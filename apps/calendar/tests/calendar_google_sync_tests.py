from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
TEST_CLIENT_ID = "<redacted-google-client-id>"
TEST_CLIENT_SECRET = "<redacted-google-client-secret>"
TEST_REFRESH_TOKEN = "<redacted-calendar-refresh-token>"


class CalendarGoogleSyncTest(unittest.TestCase):
    def test_sync_refreshes_token_lists_calendars_and_paginates_event_full_sync(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        calls: list[tuple[str, str, dict[str, object]]] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append((method, url, request))
            if url == "https://oauth2.googleapis.com/token":
                data = request["data"]
                self.assertEqual(data["client_id"], TEST_CLIENT_ID)
                self.assertEqual(data["client_secret"], TEST_CLIENT_SECRET)
                self.assertEqual(data["refresh_token"], TEST_REFRESH_TOKEN)
                return 200, {"access_token": "access-token", "token_type": "Bearer"}
            if url.startswith("https://www.googleapis.com/calendar/v3/users/me/calendarList"):
                query = parse_qs(urlparse(url).query)
                if query.get("pageToken") == ["calendar-page-2"]:
                    return 200, {
                        "items": [
                            {
                                "id": "team@example.com",
                                "summary": "Team",
                                "timeZone": "America/New_York",
                                "selected": False,
                            }
                        ]
                    }
                return 200, {
                    "nextPageToken": "calendar-page-2",
                    "items": [
                        {
                            "id": "primary",
                            "summary": "Work",
                            "timeZone": "America/New_York",
                            "primary": True,
                            "selected": True,
                        }
                    ],
                }
            if url.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events"):
                query = parse_qs(urlparse(url).query)
                self.assertNotIn("syncToken", query)
                if query.get("pageToken") == ["event-page-2"]:
                    return 200, {
                        "nextSyncToken": "sync-primary-1",
                        "items": [
                            {
                                "id": "google-event-2",
                                "summary": "Planning",
                                "status": "tentative",
                                "start": {"date": "2026-05-29", "timeZone": "America/New_York"},
                                "end": {"date": "2026-05-30", "timeZone": "America/New_York"},
                                "updated": "2026-05-28T10:30:00Z",
                            }
                        ],
                    }
                return 200, {
                    "nextPageToken": "event-page-2",
                    "items": [
                        {
                            "id": "google-event-1",
                            "summary": "Demo",
                            "description": "Product demo",
                            "status": "confirmed",
                            "start": {"dateTime": "2026-05-28T09:00:00-04:00", "timeZone": "America/New_York"},
                            "end": {"dateTime": "2026-05-28T10:00:00-04:00", "timeZone": "America/New_York"},
                            "location": "Room 1",
                            "organizer": {"email": "ana@example.com"},
                            "attendees": [{"email": "ben@example.com"}],
                            "htmlLink": "https://calendar.google.com/event?eid=one",
                            "etag": "etag-1",
                            "iCalUID": "ical-1@example.com",
                            "created": "2026-05-27T10:00:00Z",
                            "updated": "2026-05-28T10:00:00Z",
                        }
                    ],
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root)
            status_code, synced = _handle_action(
                data_root,
                {"action": "calendar_sync", "connection_id": "cal_conn_work", "calendar_id": "primary", "calendar_limit": 5},
                app_secrets=_app_secrets(),
                oauth_transport=transport,
                oauth_now=fixed_now,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertTrue(synced["synced"])
        self.assertEqual(synced["calendar_count"], 1)
        self.assertEqual(synced["created"], 2)
        self.assertEqual(synced["events_changed"], 2)
        self.assertEqual(len(persisted["calendars"]), 2)
        self.assertEqual(len(persisted["events"]), 2)
        first = persisted["events"][0]
        self.assertEqual(first["title"], "Demo")
        self.assertEqual(first["startTime"], "2026-05-28T13:00:00Z")
        self.assertEqual(first["external_refs"]["calendar_connection_id"], "cal_conn_work")
        self.assertEqual(first["external_refs"]["provider_calendar_id"], "primary")
        self.assertEqual(first["external_refs"]["provider_event_id"], "google-event-1")
        self.assertEqual(first["external_refs"]["html_link"], "https://calendar.google.com/event?eid=one")
        self.assertEqual(persisted["sync_state"][0]["sync_token"], "sync-primary-1")
        persisted_text = json.dumps(persisted, sort_keys=True)
        result_text = json.dumps(synced, sort_keys=True)
        self.assertNotIn(TEST_REFRESH_TOKEN, persisted_text)
        self.assertNotIn("access-token", persisted_text)
        self.assertNotIn(TEST_REFRESH_TOKEN, result_text)
        self.assertEqual([call[0] for call in calls].count("POST"), 1)
        self.assertGreaterEqual([call[0] for call in calls].count("GET"), 4)

    def test_incremental_sync_deletes_cancelled_remote_event(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if url.startswith("https://www.googleapis.com/calendar/v3/users/me/calendarList"):
                return 200, {"items": [{"id": "primary", "summary": "Work", "timeZone": "UTC", "selected": True}]}
            if url.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events"):
                query = parse_qs(urlparse(url).query)
                self.assertEqual(query["syncToken"], ["sync-primary-1"])
                return 200, {
                    "nextSyncToken": "sync-primary-2",
                    "items": [{"id": "google-event-old", "status": "cancelled"}],
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True, sync_token="sync-primary-1")
            status_code, synced = _handle_action(
                data_root,
                {"action": "calendar_sync", "connection_id": "cal_conn_work"},
                app_secrets=_app_secrets(),
                oauth_transport=transport,
                oauth_now=fixed_now,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertEqual(synced["deleted"], 1)
        self.assertEqual(persisted["events"], [])
        self.assertEqual(persisted["sync_state"][0]["sync_token"], "sync-primary-2")

    def test_calendar_selection_controls_default_sync_targets(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        event_urls: list[str] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if url.startswith("https://www.googleapis.com/calendar/v3/users/me/calendarList"):
                return 200, {
                    "items": [
                        {"id": "primary", "summary": "Work", "timeZone": "UTC", "selected": True},
                        {"id": "team@example.com", "summary": "Team", "timeZone": "UTC", "selected": True},
                    ]
                }
            if url.startswith("https://www.googleapis.com/calendar/v3/calendars/"):
                event_urls.append(url)
                self.assertIn("/calendars/team%40example.com/events", url)
                return 200, {
                    "nextSyncToken": "sync-team-1",
                    "items": [
                        {
                            "id": "team-event",
                            "summary": "Team",
                            "start": {"dateTime": "2026-05-28T13:00:00Z"},
                            "end": {"dateTime": "2026-05-28T14:00:00Z"},
                        }
                    ],
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root)
            status_code, selected = _handle_action(
                data_root,
                {
                    "action": "calendar_calendars.select",
                    "connection_id": "cal_conn_work",
                    "calendar_id": "primary",
                    "sync_enabled": False,
                },
                oauth_now=fixed_now,
            )
            sync_status, synced = _handle_action(
                data_root,
                {"action": "calendar_sync", "connection_id": "cal_conn_work", "calendar_limit": 5},
                app_secrets=_app_secrets(),
                oauth_transport=transport,
                oauth_now=fixed_now,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertFalse(selected["calendar"]["sync_enabled"])
        self.assertEqual(sync_status, 200)
        self.assertEqual(synced["calendar_count"], 1)
        self.assertEqual(len(event_urls), 1)
        calendars_by_provider = {item["provider_calendar_id"]: item for item in persisted["calendars"]}
        self.assertFalse(calendars_by_provider["primary"]["sync_enabled"])
        self.assertTrue(calendars_by_provider["team@example.com"]["sync_enabled"])
        self.assertEqual(persisted["events"][0]["external_refs"]["provider_calendar_id"], "team@example.com")

    def test_disabled_calendar_hides_existing_mirror_events_without_deleting_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True)
            select_status, selected = _handle_action(
                data_root,
                {
                    "action": "calendar_calendars.select",
                    "connection_id": "cal_conn_work",
                    "calendar_id": "primary",
                    "sync_enabled": False,
                },
            )
            list_status, listed = _handle_action(data_root, {"action": "list"})
            availability_status, availability = _handle_action(
                data_root,
                {
                    "action": "check_availability",
                    "startTime": "2026-05-27T09:00:00Z",
                    "endTime": "2026-05-27T10:00:00Z",
                },
            )
            create_status, created = _handle_action(
                data_root,
                {
                    "action": "create",
                    "conflict_policy": "reject",
                    "event": {
                        "title": "Local overlap",
                        "startTime": "2026-05-27T09:00:00Z",
                        "endTime": "2026-05-27T10:00:00Z",
                    },
                },
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(select_status, 200)
        self.assertFalse(selected["calendar"]["sync_enabled"])
        self.assertEqual(list_status, 200)
        self.assertEqual(listed["events"], [])
        self.assertEqual(availability_status, 200)
        self.assertTrue(availability["available"])
        self.assertEqual(create_status, 201)
        self.assertEqual(created["event"]["title"], "Local overlap")
        self.assertEqual({event["id"] for event in persisted["events"]}, {"evt_existing_google", created["event"]["id"]})

    def test_calendar_selection_emits_calendar_and_event_data_events(self) -> None:
        self.assertEqual(
            _app_events_for_action("calendar_calendars.select"),
            [
                {"type": "maverick.app.data-changed", "owner_app_id": "calendar", "resource": "calendars"},
                {"type": "maverick.app.data-changed", "owner_app_id": "calendar", "resource": "events"},
            ],
        )

    def test_calendar_list_exposes_empty_known_remote_calendars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root)
            status_code, listed = _handle_action(
                data_root,
                {"action": "calendar_calendars.list", "connection_id": "cal_conn_work"},
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(listed["calendars"][0]["provider_calendar_id"], "primary")
        self.assertTrue(listed["calendars"][0]["sync_enabled"])

    def test_incremental_sync_token_gone_runs_full_resync_and_replaces_stale_events(self) -> None:
        fixed_now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        event_urls: list[str] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if url.startswith("https://www.googleapis.com/calendar/v3/users/me/calendarList"):
                return 200, {"items": [{"id": "primary", "summary": "Work", "timeZone": "UTC", "selected": True}]}
            if url.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events"):
                event_urls.append(url)
                query = parse_qs(urlparse(url).query)
                if query.get("syncToken") == ["stale-token"]:
                    return 410, {"error": {"status": "GONE"}}
                self.assertNotIn("syncToken", query)
                return 200, {
                    "nextSyncToken": "fresh-token",
                    "items": [
                        {
                            "id": "google-event-new",
                            "summary": "Fresh",
                            "start": {"dateTime": "2026-05-28T15:00:00Z"},
                            "end": {"dateTime": "2026-05-28T16:00:00Z"},
                            "updated": "2026-05-28T11:00:00Z",
                        }
                    ],
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True, sync_token="stale-token")
            status_code, synced = _handle_action(
                data_root,
                {"action": "calendar_sync", "connection_id": "cal_conn_work"},
                app_secrets=_app_secrets(),
                oauth_transport=transport,
                oauth_now=fixed_now,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertEqual(synced["full_resyncs"], 1)
        self.assertEqual(synced["created"], 1)
        self.assertEqual(synced["deleted"], 1)
        self.assertEqual(len(event_urls), 2)
        self.assertEqual(persisted["events"][0]["external_refs"]["provider_event_id"], "google-event-new")
        self.assertEqual(persisted["sync_state"][0]["sync_token"], "fresh-token")
        self.assertEqual(persisted["sync_state"][0]["last_full_sync_at"], "2026-05-28T12:00:00Z")

    def test_create_targeting_google_calendar_inserts_remote_event_before_local_persist(self) -> None:
        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "POST" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events":
                body = request["json"]
                self.assertEqual(body["summary"], "Remote Created")
                self.assertEqual(body["start"], {"dateTime": "2026-05-28T13:00:00Z", "timeZone": "UTC"})
                return 200, {
                    "id": "google-created",
                    "summary": "Remote Created",
                    "description": "Created from Maverick",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-05-28T13:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-05-28T14:00:00Z", "timeZone": "UTC"},
                    "htmlLink": "https://calendar.google.com/event?eid=created",
                    "etag": "etag-created",
                    "updated": "2026-05-28T12:30:00Z",
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root)
            status_code, created = _handle_action(
                data_root,
                {
                    "action": "create",
                    "event": {
                        "title": "Remote Created",
                        "description": "Created from Maverick",
                        "startTime": "2026-05-28T13:00:00Z",
                        "endTime": "2026-05-28T14:00:00Z",
                        "source": "google_calendar",
                        "external_refs": {
                            "calendar_connection_id": "cal_conn_work",
                            "provider_calendar_id": "primary",
                        },
                    },
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 201)
        self.assertTrue(created["remote_mutation"])
        self.assertEqual(created["event"]["external_refs"]["provider_event_id"], "google-created")
        self.assertEqual(created["event"]["external_refs"]["etag"], "etag-created")
        self.assertEqual(persisted["events"][0]["external_refs"]["html_link"], "https://calendar.google.com/event?eid=created")

    def test_create_rejects_read_only_google_calendar_before_remote_request(self) -> None:
        calls: list[str] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append(url)
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, access_role="reader")
            status_code, rejected = _handle_action(
                data_root,
                {
                    "action": "create",
                    "event": {
                        "title": "Read Only",
                        "startTime": "2026-05-28T13:00:00Z",
                        "endTime": "2026-05-28T14:00:00Z",
                        "source": "google_calendar",
                        "external_refs": {
                            "calendar_connection_id": "cal_conn_work",
                            "provider_calendar_id": "primary",
                        },
                    },
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )

        self.assertEqual(status_code, 403)
        self.assertEqual(rejected["error"], "google_calendar_read_only")
        self.assertEqual(calls, [])

    def test_google_account_level_create_defaults_to_primary_calendar(self) -> None:
        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "POST" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events":
                body = request["json"]
                self.assertEqual(body["summary"], "Primary Remote")
                return 200, {
                    "id": "google-primary-created",
                    "summary": "Primary Remote",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-05-28T13:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-05-28T14:00:00Z", "timeZone": "UTC"},
                    "etag": "etag-primary-created",
                    "updated": "2026-05-28T12:30:00Z",
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root)
            status_code, created = _handle_action(
                data_root,
                {
                    "action": "create",
                    "event": {
                        "title": "Primary Remote",
                        "startTime": "2026-05-28T13:00:00Z",
                        "endTime": "2026-05-28T14:00:00Z",
                        "source": "google_calendar",
                        "external_refs": {
                            "provider": "google",
                            "calendar_connection_id": "cal_conn_work",
                        },
                    },
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )

        self.assertEqual(status_code, 201)
        self.assertTrue(created["remote_mutation"])
        self.assertEqual(created["event"]["external_refs"]["provider_calendar_id"], "primary")
        self.assertEqual(created["event"]["external_refs"]["provider_event_id"], "google-primary-created")

    def test_update_google_event_patches_remote_before_local_state(self) -> None:
        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "PATCH" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events/google-event-old":
                self.assertEqual(request["headers"]["if-match"], "etag-old")
                body = request["json"]
                self.assertEqual(body["summary"], "Remote Updated")
                self.assertEqual(body["location"], "Room 2")
                return 200, {
                    "id": "google-event-old",
                    "summary": "Remote Updated",
                    "description": "",
                    "location": "Room 2",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-05-27T09:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-05-27T10:00:00Z", "timeZone": "UTC"},
                    "htmlLink": "https://calendar.google.com/event?eid=old",
                    "etag": "etag-new",
                    "updated": "2026-05-28T12:30:00Z",
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True)
            status_code, updated = _handle_action(
                data_root,
                {
                    "action": "update",
                    "id": "evt_existing_google",
                    "expected_revision": 1,
                    "event": {"title": "Remote Updated", "location": "Room 2", "source": "calendar", "external_refs": {}},
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertTrue(updated["remote_mutation"])
        self.assertEqual(updated["event"]["title"], "Remote Updated")
        self.assertEqual(updated["event"]["source"], "google_calendar")
        self.assertEqual(updated["event"]["revision"], 2)
        self.assertEqual(persisted["events"][0]["external_refs"]["etag"], "etag-new")

    def test_update_local_event_to_google_inserts_remote_and_keeps_local_id(self) -> None:
        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "POST" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events":
                body = request["json"]
                self.assertEqual(body["summary"], "Remote Attached")
                return 200, {
                    "id": "google-attached",
                    "summary": "Remote Attached",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-05-28T15:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-05-28T16:00:00Z", "timeZone": "UTC"},
                    "htmlLink": "https://calendar.google.com/event?eid=attached",
                    "etag": "etag-attached",
                    "updated": "2026-05-28T12:30:00Z",
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root)
            create_status, created = _handle_action(
                data_root,
                {
                    "action": "create",
                    "event": {
                        "title": "Local Draft",
                        "startTime": "2026-05-28T15:00:00Z",
                        "endTime": "2026-05-28T16:00:00Z",
                    },
                },
            )
            local_id = created["event"]["id"]
            status_code, updated = _handle_action(
                data_root,
                {
                    "action": "update",
                    "id": local_id,
                    "expected_revision": 1,
                    "event": {
                        "title": "Remote Attached",
                        "startTime": "2026-05-28T15:00:00Z",
                        "endTime": "2026-05-28T16:00:00Z",
                        "source": "google_calendar",
                        "external_refs": {
                            "calendar_connection_id": "cal_conn_work",
                            "provider_calendar_id": "primary",
                        },
                    },
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(create_status, 201)
        self.assertEqual(status_code, 200)
        self.assertTrue(updated["remote_mutation"])
        self.assertEqual(updated["event"]["id"], local_id)
        self.assertEqual(updated["event"]["external_refs"]["provider_event_id"], "google-attached")
        self.assertEqual(updated["event"]["external_refs"]["html_link"], "https://calendar.google.com/event?eid=attached")
        self.assertEqual(len(persisted["events"]), 1)
        self.assertEqual(persisted["events"][0]["id"], local_id)
        self.assertEqual(persisted["events"][0]["external_refs"]["etag"], "etag-attached")

    def test_update_rejects_read_only_google_event_before_remote_request(self) -> None:
        calls: list[str] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append(url)
            return 500, {}

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True, access_role="reader")
            status_code, rejected = _handle_action(
                data_root,
                {
                    "action": "update",
                    "id": "evt_existing_google",
                    "expected_revision": 1,
                    "event": {"title": "Blocked"},
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )

        self.assertEqual(status_code, 403)
        self.assertEqual(rejected["error"], "google_calendar_read_only")
        self.assertEqual(calls, [])

    def test_move_google_event_patches_remote_time(self) -> None:
        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "PATCH" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events/google-event-old":
                body = request["json"]
                self.assertEqual(body["start"], {"dateTime": "2026-05-28T15:00:00Z", "timeZone": "UTC"})
                self.assertEqual(body["end"], {"dateTime": "2026-05-28T16:00:00Z", "timeZone": "UTC"})
                return 200, {
                    "id": "google-event-old",
                    "summary": "Old",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-05-28T15:00:00Z", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-05-28T16:00:00Z", "timeZone": "UTC"},
                    "etag": "etag-moved",
                    "updated": "2026-05-28T12:30:00Z",
                }
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True)
            status_code, moved = _handle_action(
                data_root,
                {
                    "action": "move",
                    "id": "evt_existing_google",
                    "expected_revision": 1,
                    "startTime": "2026-05-28T15:00:00Z",
                    "endTime": "2026-05-28T16:00:00Z",
                },
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )

        self.assertEqual(status_code, 200)
        self.assertTrue(moved["remote_mutation"])
        self.assertEqual(moved["event"]["startTime"], "2026-05-28T15:00:00Z")
        self.assertEqual(moved["event"]["external_refs"]["etag"], "etag-moved")

    def test_delete_google_event_deletes_remote_before_local_state(self) -> None:
        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "DELETE" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events/google-event-old":
                self.assertEqual(request["headers"]["if-match"], "etag-old")
                return 204, {}
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True)
            status_code, deleted = _handle_action(
                data_root,
                {"action": "delete", "id": "evt_existing_google", "expected_revision": 1},
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 200)
        self.assertTrue(deleted["remote_mutation"])
        self.assertEqual(persisted["events"], [])

    def test_delete_rejects_read_only_google_event_before_remote_request(self) -> None:
        calls: list[str] = []

        def transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            calls.append(url)
            return 500, {}

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True, access_role="reader")
            status_code, rejected = _handle_action(
                data_root,
                {"action": "delete", "id": "evt_existing_google", "expected_revision": 1},
                app_secrets=_app_secrets(),
                oauth_transport=transport,
            )
            persisted = json.loads((data_root / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(status_code, 403)
        self.assertEqual(rejected["error"], "google_calendar_read_only")
        self.assertEqual(calls, [])
        self.assertEqual(len(persisted["events"]), 1)

    def test_google_provider_permission_errors_are_operational_status_codes(self) -> None:
        def forbidden_transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "PATCH" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events/google-event-old":
                return 403, {"error": {"status": "PERMISSION_DENIED"}}
            raise AssertionError(f"Unexpected request: {method} {url}")

        def unauthorized_transport(method: str, url: str, request: dict[str, object]) -> tuple[int, dict[str, object]]:
            if url == "https://oauth2.googleapis.com/token":
                return 200, {"access_token": "access-token"}
            if method == "PATCH" and url == "https://www.googleapis.com/calendar/v3/calendars/primary/events/google-event-old":
                return 401, {"error": {"status": "UNAUTHENTICATED"}}
            raise AssertionError(f"Unexpected request: {method} {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "data"
            _write_state(data_root, include_remote_event=True)
            status_code, rejected = _handle_action(
                data_root,
                {
                    "action": "update",
                    "id": "evt_existing_google",
                    "expected_revision": 1,
                    "event": {"title": "Remote Updated"},
                },
                app_secrets=_app_secrets(),
                oauth_transport=forbidden_transport,
            )
            unauthorized_status, unauthorized = _handle_action(
                data_root,
                {
                    "action": "update",
                    "id": "evt_existing_google",
                    "expected_revision": 1,
                    "event": {"title": "Remote Updated"},
                },
                app_secrets=_app_secrets(),
                oauth_transport=unauthorized_transport,
            )

        self.assertEqual(status_code, 403)
        self.assertEqual(rejected["error"], "google_calendar_forbidden")
        self.assertEqual(unauthorized_status, 401)
        self.assertEqual(unauthorized["error"], "google_calendar_unauthorized")


def _write_state(data_root: Path, *, include_remote_event: bool = False, sync_token: str = "", access_role: str = "owner") -> None:
    data_root.mkdir(parents=True)
    events = []
    if include_remote_event:
        events.append(
            {
                "id": "evt_existing_google",
                "title": "Old",
                "startTime": "2026-05-27T09:00:00Z",
                "endTime": "2026-05-27T10:00:00Z",
                "color": "blue",
                "source": "google_calendar",
                "external_refs": {
                    "provider": "google",
                    "calendar_connection_id": "cal_conn_work",
                    "provider_calendar_id": "primary",
                    "provider_event_id": "google-event-old",
                    "etag": "etag-old",
                },
            }
        )
    sync_state = []
    if sync_token:
        sync_state.append(
            {
                "id": "cal_conn_work:primary",
                "connection_id": "cal_conn_work",
                "calendar_id": "cal_conn_work:primary",
                "provider_calendar_id": "primary",
                "status": "ok",
                "sync_token": sync_token,
            }
        )
    (data_root / "state.json").write_text(
        json.dumps(
            {
                "schema_version": "3",
                "events": events,
                "connections": [
                    {
                        "id": "cal_conn_work",
                        "provider": "google",
                        "account_id": "ana@example.com",
                        "account_label": "Ana Work",
                        "status": "connected",
                    }
                ],
                "calendars": [
                    {
                        "id": "cal_conn_work:primary",
                        "connection_id": "cal_conn_work",
                        "provider_calendar_id": "primary",
                        "summary": "Work",
                        "timezone": "UTC",
                        "access_role": access_role,
                    }
                ],
                "sync_state": sync_state,
            }
        ),
        encoding="utf-8",
    )


def _app_secrets() -> dict[str, str]:
    return {
        "google-oauth-client-id": TEST_CLIENT_ID,
        "google-oauth-client-secret": TEST_CLIENT_SECRET,
        "google-calendar-refresh-token": TEST_REFRESH_TOKEN,
    }


def _handle_action(data_root: Path, body: dict[str, object], **kwargs):
    actions = _import_calendar_actions()
    try:
        return actions.handle_action(data_root, body, **kwargs)
    finally:
        _cleanup_calendar_backend_modules()


def _app_events_for_action(action: str):
    actions = _import_calendar_actions()
    try:
        return actions.app_events_for_action(action)
    finally:
        _cleanup_calendar_backend_modules()


def _import_calendar_actions():
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    import actions

    return actions


def _cleanup_calendar_backend_modules() -> None:
    sys.path[:] = [item for item in sys.path if item != str(BACKEND_ROOT)]
    for module_name, module in list(sys.modules.items()):
        module_file = getattr(module, "__file__", "")
        if module_file and str(module_file).startswith(str(BACKEND_ROOT)):
            sys.modules.pop(module_name, None)


if __name__ == "__main__":
    unittest.main()
