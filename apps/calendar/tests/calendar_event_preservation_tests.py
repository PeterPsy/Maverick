"""Regression coverage for narrow Google edits and civil-day planning."""

import sys
import tempfile
import unittest
from pathlib import Path
from apps.calendar.tests.calendar_google_sync_tests import (
    _cleanup_calendar_backend_modules,
)


class CalendarEventPreservationTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

    def tearDown(self):
        _cleanup_calendar_backend_modules()

    def sample(self):
        from google_event_mapping import google_event_payload
        from event_records import normalize_event

        remote = {
            "id": "remote",
            "summary": "Demo",
            "colorId": "8",
            "start": {"dateTime": "2026-10-12T09:30:00+02:00"},
            "end": {"dateTime": "2026-10-12T11:00:00+02:00"},
            "attendees": [
                {
                    "email": "guest@example.com",
                    "displayName": "Guest",
                    "optional": True,
                    "responseStatus": "accepted",
                }
            ],
            "conferenceData": {
                "entryPoints": [
                    {
                        "entryPointType": "video",
                        "uri": "https://meet.google.com/aaa-bbbb-ccc",
                    }
                ]
            },
        }
        connection = {"id": "connection"}
        calendar = {"provider_calendar_id": "primary", "timezone": "Europe/Rome"}
        event = normalize_event(
            google_event_payload(remote, connection=connection, calendar=calendar),
            event_id="evt",
        )
        return remote, connection, calendar, event

    def test_title_patch_does_not_resend_invitees_color_or_reminders(self):
        from google_event_body import google_event_patch, google_event_body

        _, _, _, event = self.sample()
        self.assertEqual(
            google_event_patch(event, {**event, "title": "Changed"}),
            {"summary": "Changed"},
        )
        body = google_event_body(event)
        self.assertEqual(body["colorId"], "8")
        self.assertEqual(body["attendees"][0]["responseStatus"], "accepted")
        self.assertTrue(body["attendees"][0]["optional"])
        self.assertTrue(event["conference"]["entry_points"])

    def test_adding_invitee_keeps_existing_response_and_optional_flag(self):
        from google_event_body import google_event_patch

        _, _, _, event = self.sample()
        patch = google_event_patch(
            event, {**event, "attendees": [*event["attendees"], "new@example.com"]}
        )
        self.assertEqual(patch["attendees"][0]["responseStatus"], "accepted")
        self.assertTrue(patch["attendees"][0]["optional"])
        self.assertEqual(patch["attendees"][1], {"email": "new@example.com"})

    def test_legacy_mirror_invitee_edit_merges_current_google_metadata(self):
        from google_event_body import merge_google_people, google_attendees

        remote, _, _, event = self.sample()
        old = {**event, "attendee_details": []}
        edited = {
            **old,
            "attendees": [*old["attendees"], "new@example.com"],
            "attendee_details": [{"email": "guest@example.com", "optional": False}],
        }
        merged = google_attendees(merge_google_people(old, edited, remote))
        self.assertEqual(merged[0]["responseStatus"], "accepted")
        self.assertEqual(merged[0]["displayName"], "Guest")
        self.assertFalse(merged[0]["optional"])

    def test_local_classification_survives_remote_response_and_sync(self):
        from google_mutations import _local_payload_from_remote
        from google_reconciliation import _merge_remote_events
        from google_event_mapping import google_event_payload
        from datetime import UTC, datetime

        remote, connection, calendar, event = self.sample()
        event.update(category="Meeting", tags=["client"])
        accepted = _local_payload_from_remote(
            remote,
            fallback=event,
            connection=connection,
            calendar=calendar,
            for_update=True,
        )
        self.assertEqual(accepted["tags"], ["client"])
        self.assertEqual(accepted["category"], "Meeting")
        merged = _merge_remote_events(
            [event],
            connection=connection,
            calendar=calendar,
            remote_events=[{**remote, "summary": "Remote update"}],
            full_sync=False,
            stale_time_min="",
            stale_time_max="",
            now=datetime.now(UTC),
            baseline=[event],
            seen_remote_ids=set(),
            mapper=google_event_payload,
        )
        self.assertEqual(merged["events"][0]["tags"], ["client"])

    def test_whole_day_search_ignores_work_hours_and_preserves_dst_dates(self):
        from availability import find_free_time
        from operations import create_event

        with tempfile.TemporaryDirectory() as root:
            data = Path(root)
            create_event(
                data,
                {
                    "title": "Busy",
                    "timezone": "Europe/Rome",
                    "startTime": "2026-03-28",
                    "endTime": "2026-03-29",
                    "all_day": True,
                },
            )
            result = find_free_time(
                data,
                {
                    "start_after": "2026-03-27T23:00:00Z",
                    "end_before": "2026-03-31T22:00:00Z",
                    "timezone": "Europe/Rome",
                    "all_day": True,
                    "duration_days": 1,
                    "work_start": "09:00",
                    "work_end": "18:00",
                },
            )
            self.assertEqual(result["slots"][0]["startTime"], "2026-03-28T23:00:00Z")
            self.assertEqual(result["slots"][0]["endTime"], "2026-03-29T22:00:00Z")
