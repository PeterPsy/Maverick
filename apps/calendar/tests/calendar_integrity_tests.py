"""Regressions for data loss, civil dates, availability and series scopes."""

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from apps.calendar.tests.calendar_google_sync_tests import _write_state, _app_secrets


class CalendarIntegrityTest(unittest.TestCase):
    def setUp(self):
        from apps.calendar.tests.calendar_google_sync_tests import (
            _import_calendar_actions,
            _cleanup_calendar_backend_modules,
        )

        self.actions = _import_calendar_actions()
        self.addCleanup(_cleanup_calendar_backend_modules)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        _write_state(self.root, include_remote_event=True)

    def action(self, body, transport=None):
        return self.actions.handle_action(
            self.root,
            body,
            app_secrets=_app_secrets(),
            oauth_transport=transport,
            oauth_now=datetime(2026, 5, 28, tzinfo=UTC),
        )

    def transport(self, events):
        def call(method, url, request):
            if "oauth2" in url:
                return 200, {"access_token": "test"}
            if "calendarList" in url:
                return 200, {
                    "items": [
                        {"id": "primary", "timeZone": "UTC", "accessRole": "owner"}
                    ]
                }
            return events(method, url, request)

        return call

    def test_sync_keeps_concurrent_create_and_revision_changes(self):
        def remote(method, url, request):
            self.assertEqual(
                self.action(
                    {
                        "action": "create",
                        "event": {
                            "title": "Concurrent",
                            "startTime": "2026-05-28T10:00:00Z",
                            "endTime": "2026-05-28T11:00:00Z",
                        },
                    }
                )[0],
                201,
            )
            # Local revision changes while remote fetch is outstanding.
            from store import update_state

            def edit(state):
                state["events"][0].update(title="Concurrent edit", revision=2)
                return state

            update_state(self.root, edit)
            return 200, {"items": [], "nextSyncToken": "next"}

        status, result = self.action(
            {"action": "calendar_sync", "connection_id": "cal_conn_work"},
            self.transport(remote),
        )
        self.assertEqual(status, 200)
        titles = {e["title"] for e in self.action({"action": "list"})[1]["events"]}
        self.assertEqual(titles, {"Concurrent", "Concurrent edit"})

    def test_partial_sync_preserves_events_and_resumes_exact_query(self):
        calls = []

        def remote(method, url, request):
            calls.append(url)
            if "pageToken=next-page" in url:
                return 200, {"items": [], "nextSyncToken": "complete"}
            return 200, {"items": [], "nextPageToken": "next-page"}

        body = {
            "action": "calendar_sync",
            "connection_id": "cal_conn_work",
            "page_limit": 1,
        }
        status, first = self.action(body, self.transport(remote))
        self.assertEqual(status, 200)
        self.assertFalse(first["synced"])
        self.assertEqual(first["status"], "partial")
        self.assertEqual(len(self.action({"action": "list"})[1]["events"]), 1)
        status, second = self.action(body, self.transport(remote))
        self.assertTrue(second["synced"])
        self.assertIn("pageToken=next-page", calls[-1])
        self.assertEqual(self.action({"action": "list"})[1]["events"], [])

    def test_all_day_roundtrip_across_offsets_and_dst(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from google_mutations import _google_event_body

        for zone, start, end in [
            ("Europe/Rome", "2026-10-04", "2026-10-05"),
            ("America/New_York", "2026-11-01", "2026-11-02"),
            ("Europe/Rome", "2026-03-29", "2026-03-30"),
            ("Pacific/Auckland", "2026-04-04", "2026-04-06"),
        ]:
            with self.subTest(zone=zone, start=start):
                payload = google_event_payload(
                    {
                        "id": "remote",
                        "summary": "Day",
                        "start": {"date": start},
                        "end": {"date": end},
                    },
                    connection={"id": "c"},
                    calendar={"timezone": zone, "provider_calendar_id": "primary"},
                )
                event = normalize_event(payload, event_id="event")
                body = _google_event_body(event)
                self.assertEqual(body["start"], {"date": start})
                self.assertEqual(body["end"], {"date": end})

    def test_visibility_sync_and_availability_are_independent(self):
        self.action(
            {
                "action": "calendar_calendars.select",
                "connection_id": "cal_conn_work",
                "calendar_id": "primary",
                "selected": False,
                "sync_enabled": False,
            }
        )
        self.assertEqual(self.action({"action": "list"})[1]["events"], [])
        probe = {
            "action": "check_availability",
            "startTime": "2026-05-27T09:00:00Z",
            "endTime": "2026-05-27T10:00:00Z",
        }
        self.assertFalse(self.action(probe)[1]["available"])
        self.action(
            {
                "action": "calendar_calendars.select",
                "connection_id": "cal_conn_work",
                "calendar_id": "primary",
                "availability_enabled": False,
            }
        )
        self.assertTrue(self.action(probe)[1]["available"])

    def test_transparent_event_does_not_block(self):
        from store import update_state

        def edit(state):
            state["events"][0]["transparency"] = "transparent"
            return state

        update_state(self.root, edit)
        self.assertTrue(
            self.action(
                {
                    "action": "check_availability",
                    "startTime": "2026-05-27T09:00:00Z",
                    "endTime": "2026-05-27T10:00:00Z",
                }
            )[1]["available"]
        )

    def test_local_series_occurrence_exception_and_future_split(self):
        status, created = self.action(
            {
                "action": "create",
                "event": {
                    "title": "Weekly",
                    "timezone": "Europe/Rome",
                    "startTime": "2026-10-18T09:30:00+02:00",
                    "endTime": "2026-10-18T10:30:00+02:00",
                    "recurrence": {"frequency": "weekly", "count": 3},
                },
            }
        )
        self.assertEqual(status, 201)
        window = {
            "action": "list",
            "start_after": "2026-10-24T00:00:00Z",
            "end_before": "2026-11-03T00:00:00Z",
        }
        occurrences = self.action(window)[1]["events"]
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(occurrences[0]["startTime"], "2026-10-25T08:30:00Z")
        self.assertFalse(
            self.action(
                {
                    "action": "check_availability",
                    "startTime": "2026-10-25T09:00:00Z",
                    "endTime": "2026-10-25T09:15:00Z",
                }
            )[1]["available"]
        )
        oid = occurrences[0]["id"]
        self.assertEqual(
            self.action(
                {
                    "action": "update",
                    "id": oid,
                    "expected_revision": 1,
                    "recurrence_scope": "occurrence",
                    "event": {"title": "Exception"},
                }
            )[0],
            200,
        )
        self.assertEqual(self.action(window)[1]["events"][0]["title"], "Exception")
        self.assertEqual(self.action(window)[1]["events"][1]["title"], "Weekly")
        self.assertEqual(
            self.action(
                {
                    "action": "update",
                    "id": oid,
                    "expected_revision": 2,
                    "recurrence_scope": "future",
                    "event": {"title": "New series"},
                }
            )[0],
            200,
        )
        self.assertEqual(
            [e["title"] for e in self.action(window)[1]["events"]],
            ["New series", "New series"],
        )

    def test_transfer_uses_move_and_updates_destination_refs(self):
        from store import update_state

        def edit(state):
            state["calendars"].append(
                {
                    "connection_id": "cal_conn_work",
                    "provider_calendar_id": "secondary",
                    "access_role": "writer",
                }
            )
            return state

        update_state(self.root, edit)
        methods = []

        def remote(method, url, request):
            methods.append((method, url))
            return 200, {
                "id": "google-event-old",
                "summary": "Moved",
                "etag": "new",
                "start": {"dateTime": "2026-05-27T09:00:00Z"},
                "end": {"dateTime": "2026-05-27T10:00:00Z"},
            }

        status, result = self.action(
            {
                "action": "update",
                "id": "evt_existing_google",
                "expected_revision": 1,
                "event": {
                    "source": "google_calendar",
                    "external_refs": {
                        "provider": "google",
                        "calendar_connection_id": "cal_conn_work",
                        "provider_calendar_id": "secondary",
                    },
                },
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(methods[0][0], "POST")
        self.assertIn("/move?destination=secondary", methods[0][1])
        self.assertEqual(len(methods), 1, "Moving without edits must not issue a redundant PATCH")
        self.assertEqual(result["event"]["external_refs"]["etag"], "new")
        self.assertEqual(
            result["event"]["external_refs"]["provider_calendar_id"], "secondary"
        )

    def test_concurrent_accounts_do_not_overwrite_each_other(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from store import update_state

        barrier = Barrier(2)

        def add_account(state):
            state["connections"].append(
                {**state["connections"][0], "id": "cal_conn_other"}
            )
            state["calendars"].append(
                {**state["calendars"][0], "connection_id": "cal_conn_other"}
            )
            return state

        update_state(self.root, add_account)

        def run(connection):
            def remote(method, url, request):
                barrier.wait(timeout=5)
                return 200, {
                    "items": [
                        {
                            "id": connection,
                            "summary": connection,
                            "start": {"dateTime": "2026-05-28T09:00:00Z"},
                            "end": {"dateTime": "2026-05-28T10:00:00Z"},
                        }
                    ]
                }

            return self.action(
                {"action": "calendar_sync", "connection_id": connection},
                self.transport(remote),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["cal_conn_work", "cal_conn_other"]))
        self.assertTrue(
            all(status == 200 and result["synced"] for status, result in results),
            results,
        )
        events = self.action({"action": "list"})[1]["events"]
        self.assertEqual(
            {e["title"] for e in events}, {"cal_conn_work", "cal_conn_other"}
        )

    def test_continuation_keeps_edits_made_between_pages(self):
        from store import update_state

        body = {
            "action": "calendar_sync",
            "connection_id": "cal_conn_work",
            "page_limit": 1,
            "page_size": 10,
        }

        def remote(method, url, request):
            if "pageToken=next-page" in url:
                self.assertIn("maxResults=10", url)
                return 200, {"items": []}
            return 200, {"items": [], "nextPageToken": "next-page"}

        self.action(body, self.transport(remote))

        def edit(state):
            state["events"][0].update(title="Edited between pages", revision=2)
            return state

        update_state(self.root, edit)
        status, result = self.action({**body, "page_size": 250}, self.transport(remote))
        self.assertEqual(status, 200)
        self.assertFalse(result["synced"])
        self.assertEqual(
            self.action({"action": "list"})[1]["events"][0]["title"],
            "Edited between pages",
        )

    def test_full_history_expands_master_and_exceptions_without_duplicates(self):
        def remote(method, url, request):
            return 200, {
                "items": [
                    {
                        "id": "series",
                        "summary": "Series",
                        "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
                        "start": {"dateTime": "2026-05-28T09:00:00Z"},
                        "end": {"dateTime": "2026-05-28T10:00:00Z"},
                    },
                    {
                        "id": "moved",
                        "summary": "Moved",
                        "recurringEventId": "series",
                        "originalStartTime": {"dateTime": "2026-06-04T09:00:00Z"},
                        "start": {"dateTime": "2026-06-05T11:00:00Z"},
                        "end": {"dateTime": "2026-06-05T12:00:00Z"},
                    },
                    {
                        "id": "cancelled",
                        "status": "cancelled",
                        "recurringEventId": "series",
                        "originalStartTime": {"dateTime": "2026-06-11T09:00:00Z"},
                    },
                ],
                "nextSyncToken": "complete",
            }

        status, result = self.action(
            {
                "action": "calendar_sync",
                "connection_id": "cal_conn_work",
                "sync_mode": "full_history",
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        events = self.action(
            {
                "action": "list",
                "start_after": "2026-05-28T00:00:00Z",
                "end_before": "2026-06-15T00:00:00Z",
            }
        )[1]["events"]
        self.assertEqual([e["title"] for e in events], ["Series", "Moved"])

    def test_future_split_partitions_dates_counts_and_keeps_exceptions(self):
        from event_records import normalize_event
        from recurrence import expand_events
        from recurrence_rules import split_rules

        event = normalize_event(
            {
                "id": "s",
                "title": "Dates",
                "startTime": "2026-10-01T09:00:00Z",
                "endTime": "2026-10-01T10:00:00Z",
                "recurrence": {
                    "rules": [
                        "RRULE:FREQ=DAILY;COUNT=4",
                        "EXDATE:20261002T090000Z",
                        "RDATE:20261010T090000Z",
                    ]
                },
            }
        )
        old, future = split_rules(event, "2026-10-03T09:00:00Z")
        old_event = {**event, "recurrence": {"rules": old}}
        future_event = {
            **event,
            "id": "future",
            "startTime": "2026-10-03T09:00:00Z",
            "endTime": "2026-10-03T10:00:00Z",
            "recurrence": {"rules": future},
        }
        rows = expand_events(
            [old_event, future_event], "2026-10-01T00:00:00Z", "2026-10-12T00:00:00Z"
        )
        self.assertEqual(
            [e["startTime"] for e in rows],
            [
                "2026-10-01T09:00:00Z",
                "2026-10-03T09:00:00Z",
                "2026-10-04T09:00:00Z",
                "2026-10-10T09:00:00Z",
            ],
        )

    def test_date_only_until_and_rdate_respect_civil_timezone(self):
        from event_records import normalize_event
        from recurrence import expand_events

        event = normalize_event(
            {
                "id": "s",
                "title": "Day",
                "timezone": "Europe/Rome",
                "all_day": True,
                "startTime": "2026-10-24",
                "endTime": "2026-10-25",
                "recurrence": {
                    "rules": [
                        "RRULE:FREQ=DAILY;UNTIL=20261026",
                        "RDATE;VALUE=DATE:20261029",
                        "EXDATE;VALUE=DATE:20261025",
                    ]
                },
            }
        )
        rows = expand_events([event], "2026-10-23T00:00:00Z", "2026-10-30T00:00:00Z")
        self.assertEqual(
            [e["all_day_start"] for e in rows],
            ["2026-10-24", "2026-10-26", "2026-10-29"],
        )
        self.assertEqual(rows[1]["endTime"], "2026-10-26T23:00:00Z")

    def test_google_default_reminders_and_transparency_roundtrip(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from google_mutations import _google_event_body

        payload = google_event_payload(
            {
                "id": "remote",
                "summary": "Free",
                "transparency": "transparent",
                "reminders": {"useDefault": True},
                "start": {"dateTime": "2026-10-04T09:00:00Z"},
                "end": {"dateTime": "2026-10-04T10:00:00Z"},
            },
            connection={"id": "c"},
            calendar={"timezone": "UTC", "provider_calendar_id": "primary"},
        )
        body = _google_event_body(normalize_event(payload, event_id="e"))
        self.assertEqual(body["transparency"], "transparent")
        self.assertEqual(body["reminders"], {"useDefault": True})

    def test_google_virtual_occurrence_patches_instance_not_master(self):
        from store import update_state
        from event_records import normalize_event
        from google_event_mapping import google_event_payload

        master = {
            "id": "series",
            "summary": "Series",
            "etag": "master-etag",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
        }
        local = normalize_event(
            google_event_payload(
                master,
                connection={"id": "cal_conn_work"},
                calendar={
                    "timezone": "UTC",
                    "provider_calendar_id": "primary",
                    "access_role": "owner",
                },
            ),
            event_id="master",
        )
        update_state(self.root, lambda s: {**s, "events": [local]})
        instance = {
            "id": "instance",
            "summary": "Series",
            "etag": "instance-etag",
            "recurringEventId": "series",
            "originalStartTime": {"dateTime": "2026-06-04T09:00:00Z"},
            "start": {"dateTime": "2026-06-04T09:00:00Z"},
            "end": {"dateTime": "2026-06-04T10:00:00Z"},
        }

        def remote(method, url, request):
            if "/instances" in url:
                return 200, {"items": [instance]}
            if method == "GET":
                return 200, master
            self.assertIn("/events/instance", url)
            self.assertNotIn("recurrence", request["json"])
            return 200, {**instance, "summary": "Edited instance"}

        rows = self.action(
            {
                "action": "list",
                "start_after": "2026-06-01T00:00:00Z",
                "end_before": "2026-06-15T00:00:00Z",
            }
        )[1]["events"]
        status, result = self.action(
            {
                "action": "update",
                "id": rows[0]["id"],
                "expected_revision": 1,
                "event": {"title": "Edited instance"},
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["event"]["title"], "Edited instance")

    def test_all_day_move_keeps_civil_duration_over_dst(self):
        status, created = self.action(
            {
                "action": "create",
                "event": {
                    "title": "Day",
                    "timezone": "Europe/Rome",
                    "all_day": True,
                    "startTime": "2026-03-28",
                    "endTime": "2026-03-29",
                },
            }
        )
        status, moved = self.action(
            {
                "action": "move",
                "id": created["event"]["id"],
                "expected_revision": 1,
                "startTime": "2026-03-29T00:00:00+01:00",
            }
        )
        self.assertEqual(status, 200, moved)
        self.assertEqual(moved["event"]["all_day_start"], "2026-03-29")
        self.assertEqual(moved["event"]["all_day_end"], "2026-03-30")

    def test_nonexistent_dst_times_do_not_consume_repetition_count(self):
        from event_records import normalize_event
        from recurrence import expand_events

        series = normalize_event(
            {
                "id": "s",
                "title": "Early",
                "timezone": "Europe/Rome",
                "startTime": "2026-03-28T02:30:00+01:00",
                "endTime": "2026-03-28T03:00:00+01:00",
                "recurrence": {"frequency": "daily", "count": 3},
            }
        )
        rows = expand_events([series], "2026-03-27T00:00:00Z", "2026-04-02T00:00:00Z")
        self.assertEqual(
            [e["startTime"] for e in rows],
            ["2026-03-28T01:30:00Z", "2026-03-30T00:30:00Z", "2026-03-31T00:30:00Z"],
        )

    def test_google_series_edit_preserves_moved_exception(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from store import update_state

        master = {
            "id": "series",
            "summary": "Series",
            "etag": "master",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
        }
        instance = {
            "id": "edited",
            "summary": "Special",
            "recurringEventId": "series",
            "originalStartTime": {"dateTime": "2026-06-04T09:00:00Z"},
            "start": {"dateTime": "2026-06-05T11:00:00Z"},
            "end": {"dateTime": "2026-06-05T12:00:00Z"},
        }
        events = [
            normalize_event(
                google_event_payload(
                    remote,
                    connection={"id": "cal_conn_work"},
                    calendar={"timezone": "UTC", "provider_calendar_id": "primary"},
                ),
                event_id=remote["id"],
            )
            for remote in [master, instance]
        ]
        update_state(self.root, lambda s: {**s, "events": events})

        def remote(method, url, request):
            if method == "GET":
                return 200, master
            self.assertIn("/events/series", url)
            self.assertEqual(request["json"], {"summary": "Renamed"})
            return 200, {**master, "summary": "Renamed"}

        oid = "series@20260528T090000Z"
        status, result = self.action(
            {
                "action": "update",
                "id": oid,
                "expected_revision": 1,
                "recurrence_scope": "series",
                "event": {"title": "Renamed"},
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        rows = self.action(
            {
                "action": "list",
                "start_after": "2026-05-28T00:00:00Z",
                "end_before": "2026-06-15T00:00:00Z",
            }
        )[1]["events"]
        self.assertEqual([e["title"] for e in rows], ["Renamed", "Special", "Renamed"])
        self.assertEqual(rows[1]["startTime"], "2026-06-05T11:00:00Z")

    def test_google_series_classification_is_local_and_preserves_provider_metadata(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from store import update_state

        master = {
            "id": "series",
            "summary": "Series",
            "etag": "master",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
            "attendees": [{"email": "guest@example.com", "responseStatus": "accepted"}],
        }
        event = normalize_event(
            google_event_payload(
                master,
                connection={"id": "cal_conn_work"},
                calendar={"timezone": "UTC", "provider_calendar_id": "primary"},
            ),
            event_id="series",
        )
        update_state(self.root, lambda state: {**state, "events": [event]})

        def remote(method, url, request):
            self.assertEqual(method, "GET", "Local classification must not write to Google")
            return 200, master

        status, result = self.action(
            {
                "action": "update",
                "id": "series@20260528T090000Z",
                "expected_revision": 1,
                "recurrence_scope": "series",
                "event": {"category": "Client work", "tags": ["client"]},
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["event"]["category"], "Client work")
        self.assertEqual(result["event"]["tags"], ["client"])
        self.assertEqual(result["event"]["attendee_details"][0]["responseStatus"], "accepted")

    def test_google_future_edit_mirrors_trim_then_successor(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from store import update_state

        master = {
            "id": "series",
            "summary": "Series",
            "etag": "master",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
        }
        local = normalize_event(
            google_event_payload(
                master,
                connection={"id": "cal_conn_work"},
                calendar={"timezone": "UTC", "provider_calendar_id": "primary"},
            ),
            event_id="series",
        )
        update_state(self.root, lambda s: {**s, "events": [local]})
        requests = []

        def remote(method, url, request):
            if method == "GET":
                return 200, master
            payload = request["json"]
            requests.append((method, payload))
            return 200, {
                **master,
                **payload,
                "id": "new-series" if method == "POST" else "series",
            }

        status, result = self.action(
            {
                "action": "update",
                "id": "series@20260604T090000Z",
                "expected_revision": 1,
                "recurrence_scope": "future",
                "event": {"title": "Future"},
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(requests[0][1]["recurrence"], ["RRULE:FREQ=WEEKLY;COUNT=1"])
        self.assertEqual(requests[1][1]["recurrence"], ["RRULE:FREQ=WEEKLY;COUNT=2"])
        rows = self.action(
            {
                "action": "list",
                "start_after": "2026-05-28T00:00:00Z",
                "end_before": "2026-06-15T00:00:00Z",
            }
        )[1]["events"]
        self.assertEqual([e["title"] for e in rows], ["Series", "Future", "Future"])

    def test_scheduling_applies_workdays_timezone_and_buffers(self):
        status, created = self.action(
            {
                "action": "create",
                "event": {
                    "title": "Busy",
                    "startTime": "2026-10-05T07:00:00Z",
                    "endTime": "2026-10-05T08:00:00Z",
                },
            }
        )
        status, result = self.action(
            {
                "action": "find_free_time",
                "start_after": "2026-10-03T00:00:00Z",
                "end_before": "2026-10-06T00:00:00Z",
                "timezone": "Europe/Rome",
                "work_start": "09:00",
                "work_end": "12:00",
                "work_days": [1, 2, 3, 4, 5],
                "buffer_minutes": 15,
                "duration_minutes": 60,
                "limit": 1,
            }
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["slots"][0]["startTime"], "2026-10-05T08:15:00Z")
        self.assertEqual(result["coverage"], "known_local_events")

    def test_google_series_transfer_uses_destination_for_following_patch(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from store import update_state

        master = {
            "id": "series",
            "summary": "Series",
            "etag": "master",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
        }
        local = normalize_event(
            google_event_payload(
                master,
                connection={"id": "cal_conn_work"},
                calendar={"timezone": "UTC", "provider_calendar_id": "primary"},
            ),
            event_id="series",
        )

        def prepare(state):
            state["events"] = [local]
            state["calendars"].append(
                {
                    "connection_id": "cal_conn_work",
                    "provider_calendar_id": "secondary",
                    "access_role": "writer",
                }
            )
            return state

        update_state(self.root, prepare)
        requests = []

        def remote(method, url, request):
            requests.append((method, url))
            return 200, {
                **master,
                "summary": "Moved" if method == "PATCH" else "Series",
            }

        status, result = self.action(
            {
                "action": "update",
                "id": "series@20260528T090000Z",
                "expected_revision": 1,
                "recurrence_scope": "series",
                "event": {
                    "title": "Moved",
                    "external_refs": {
                        "calendar_connection_id": "cal_conn_work",
                        "provider_calendar_id": "secondary",
                    },
                },
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        self.assertIn("/move?destination=secondary", requests[1][1])
        self.assertIn("/calendars/secondary/events/series", requests[2][1])
        self.assertEqual(
            result["event"]["external_refs"]["provider_calendar_id"], "secondary"
        )

    def test_buffers_include_events_just_outside_search_window(self):
        self.action(
            {
                "action": "create",
                "event": {
                    "title": "Previous",
                    "startTime": "2026-10-05T08:00:00Z",
                    "endTime": "2026-10-05T09:00:00Z",
                },
            }
        )
        status, result = self.action(
            {
                "action": "find_free_time",
                "start_after": "2026-10-05T09:05:00Z",
                "end_before": "2026-10-05T11:00:00Z",
                "duration_minutes": 30,
                "buffer_minutes": 15,
                "limit": 1,
            }
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["slots"][0]["startTime"], "2026-10-05T09:15:00Z")

    def test_shared_calendar_ids_only_update_the_selected_connection(self):
        from store import update_state, read_state

        def prepare(state):
            state["connections"].append(
                {**state["connections"][0], "id": "cal_conn_other"}
            )
            state["calendars"].append(
                {**state["calendars"][0], "connection_id": "cal_conn_other"}
            )
            return state

        update_state(self.root, prepare)
        self.action(
            {
                "action": "calendar_calendars.select",
                "connection_id": "cal_conn_work",
                "calendar_id": "primary",
                "selected": False,
                "availability_enabled": False,
            }
        )
        calendars = read_state(self.root)["calendars"]
        self.assertFalse(calendars[0]["selected"])
        self.assertTrue(calendars[1]["selected"])
        self.assertTrue(calendars[1]["availability_enabled"])

    def test_incremental_master_cancellation_removes_its_cached_instances(self):
        first = True
        master = {
            "id": "series",
            "summary": "Series",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
        }
        instance = {
            "id": "instance",
            "summary": "Exception",
            "recurringEventId": "series",
            "originalStartTime": {"dateTime": "2026-06-04T09:00:00Z"},
            "start": {"dateTime": "2026-06-04T11:00:00Z"},
            "end": {"dateTime": "2026-06-04T12:00:00Z"},
        }

        def remote(method, url, request):
            return 200, {
                "items": (
                    [master, instance]
                    if first
                    else [{"id": "series", "status": "cancelled"}]
                ),
                "nextSyncToken": "next",
            }

        body = {
            "action": "calendar_sync",
            "connection_id": "cal_conn_work",
            "sync_mode": "full_history",
        }
        self.assertEqual(self.action(body, self.transport(remote))[0], 200)
        first = False
        status, result = self.action(body, self.transport(remote))
        self.assertEqual(status, 200, result)
        self.assertEqual(self.action({"action": "list"})[1]["events"], [])

    def test_failed_google_future_insert_restores_original_series(self):
        from event_records import normalize_event
        from google_event_mapping import google_event_payload
        from store import update_state

        master = {
            "id": "series",
            "summary": "Series",
            "etag": "master",
            "recurrence": ["RRULE:FREQ=WEEKLY;COUNT=3"],
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T10:00:00Z"},
        }
        local = normalize_event(
            google_event_payload(
                master,
                connection={"id": "cal_conn_work"},
                calendar={"timezone": "UTC", "provider_calendar_id": "primary"},
            ),
            event_id="series",
        )
        update_state(self.root, lambda s: {**s, "events": [local]})

        def remote(method, url, request):
            if method == "GET":
                return (
                    (200, master)
                    if url.endswith("/series")
                    else (404, {"error": {"message": "Not found"}})
                )
            if method == "POST":
                return 403, {"error": {"message": "Denied"}}
            return 200, {**master, **request["json"]}

        status, result = self.action(
            {
                "action": "update",
                "id": "series@20260604T090000Z",
                "expected_revision": 1,
                "recurrence_scope": "future",
                "event": {"title": "Future"},
            },
            self.transport(remote),
        )
        self.assertEqual(status, 502, result)
        self.assertEqual(result["error"], "google_series_split_failed")
        rows = self.action(
            {
                "action": "list",
                "start_after": "2026-05-28T00:00:00Z",
                "end_before": "2026-06-15T00:00:00Z",
            }
        )[1]["events"]
        self.assertEqual([e["title"] for e in rows], ["Series", "Series", "Series"])

    def test_hidden_google_event_edits_still_update_google(self):
        self.action(
            {
                "action": "calendar_calendars.select",
                "connection_id": "cal_conn_work",
                "calendar_id": "primary",
                "selected": False,
            }
        )
        methods = []

        def remote(method, url, request):
            methods.append(method)
            return 200, {
                "id": "google-event-old",
                "summary": "Hidden edit",
                "start": {"dateTime": "2026-05-27T09:00:00Z"},
                "end": {"dateTime": "2026-05-27T10:00:00Z"},
            }

        status, result = self.action(
            {
                "action": "update",
                "id": "evt_existing_google",
                "expected_revision": 1,
                "event": {"title": "Hidden edit"},
            },
            self.transport(remote),
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(methods, ["PATCH"])
        self.assertTrue(result["remote_mutation"])
        self.assertEqual(self.action({"action": "list"})[1]["events"], [])

    def test_mutation_warnings_match_hidden_calendar_availability(self):
        self.action(
            {
                "action": "calendar_calendars.select",
                "connection_id": "cal_conn_work",
                "calendar_id": "primary",
                "selected": False,
            }
        )
        payload = {
            "action": "create",
            "conflict_policy": "warn",
            "event": {
                "title": "Overlap",
                "startTime": "2026-05-27T09:00:00Z",
                "endTime": "2026-05-27T10:00:00Z",
            },
        }
        status, result = self.action(payload)
        self.assertEqual(status, 201)
        self.assertEqual(result["availability"]["status"], "conflicting")
        self.assertEqual(result["conflicts"][0]["id"], "evt_existing_google")
        self.action(
            {
                "action": "calendar_calendars.select",
                "connection_id": "cal_conn_work",
                "calendar_id": "primary",
                "availability_enabled": False,
            }
        )
        self.action(
            {"action": "delete", "id": result["event"]["id"], "expected_revision": 1}
        )
        status, result = self.action(payload)
        self.assertEqual(result["availability"]["status"], "free")
