"""Background reminders survive closed frontends, retries and restarts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.shared.entrypoints import run_json_entrypoint
from apps.calendar.tests.calendar_google_sync_tests import (
    _import_calendar_actions,
    _cleanup_calendar_backend_modules,
)


class CalendarReminderTest(unittest.TestCase):
    def setUp(self):
        self.actions = _import_calendar_actions()
        self.addCleanup(_cleanup_calendar_backend_modules)
        from reminders import reminder_tick, list_notifications, dismiss_notification

        self.tick, self.list, self.dismiss = (
            reminder_tick,
            list_notifications,
            dismiss_notification,
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "calendar"
        self.now = datetime(2026, 10, 9, 9, 45, tzinfo=UTC)

    def create(self, **fields):
        status, result = self.actions.handle_action(
            self.root,
            {
                "action": "create",
                "event": {
                    "title": "Reminder test",
                    "startTime": "2026-10-09T10:00:00Z",
                    "endTime": "2026-10-09T11:00:00Z",
                    "reminders": [{"minutes_before": 15, "method": "popup"}],
                    **fields,
                },
            },
        )
        self.assertEqual(status, 201, result)
        return result["event"]

    def test_closed_app_restart_and_concurrent_ticks_deliver_once(self):
        self.create()
        self.tick(self.root, now=self.now - timedelta(minutes=1))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: self.tick(self.root, now=self.now), range(2))
            )
        self.assertEqual(sum(r["delivered"] for r in results), 1)
        self.assertEqual(
            len(self.list(self.root, {}, now=self.now)["notifications"]), 1
        )
        # No module-local timer or fired set is necessary after process restart.
        self.assertEqual(
            self.tick(self.root, now=self.now + timedelta(hours=2))["delivered"], 0
        )
        self.assertEqual(
            len(
                self.list(self.root, {}, now=self.now + timedelta(hours=2))[
                    "notifications"
                ]
            ),
            1,
        )

    def test_backend_downtime_catches_up_and_dismissal_is_per_user(self):
        self.create()
        self.tick(self.root, now=self.now - timedelta(minutes=1))
        self.assertEqual(
            self.tick(self.root, now=self.now + timedelta(hours=2))["delivered"], 1
        )
        notice = self.list(self.root, {}, now=self.now + timedelta(hours=2))[
            "notifications"
        ][0]
        self.dismiss(self.root, notice["id"], user_id="alice", now=self.now)
        self.dismiss(self.root, notice["id"], user_id="alice", now=self.now)
        self.assertEqual(
            self.list(self.root, {}, user_id="alice", now=self.now)["total"], 0
        )
        bob = self.list(self.root, {}, user_id="bob", now=self.now)["notifications"]
        self.assertEqual(len(bob), 1)
        self.assertNotIn("dismissed_by", bob[0])
        self.assertEqual(
            self.tick(self.root, now=self.now + timedelta(hours=3))["delivered"], 0
        )
        self.assertEqual(
            self.list(self.root, {}, user_id="alice", now=self.now)["total"], 0
        )

    def test_edit_move_and_delete_retract_stale_alerts_before_next_tick(self):
        event = self.create()
        self.tick(self.root, now=self.now)
        status, updated = self.actions.handle_action(
            self.root,
            {
                "action": "update",
                "id": event["id"],
                "expected_revision": 1,
                "event": {"title": "Renamed"},
            },
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(
            self.list(self.root, {}, now=self.now)["notifications"][0]["title"],
            "Renamed",
        )
        self.actions.handle_action(
            self.root,
            {
                "action": "move",
                "id": event["id"],
                "expected_revision": 2,
                "startTime": "2026-10-09T12:00:00Z",
                "endTime": "2026-10-09T13:00:00Z",
            },
        )
        self.assertEqual(self.list(self.root, {}, now=self.now)["total"], 0)
        self.tick(self.root, now=self.now + timedelta(hours=2))
        self.assertEqual(
            self.list(self.root, {}, now=self.now + timedelta(hours=2))["total"], 1
        )
        self.actions.handle_action(
            self.root, {"action": "delete", "id": event["id"], "expected_revision": 3}
        )
        self.assertEqual(
            self.list(self.root, {}, now=self.now + timedelta(hours=2))["total"], 0
        )

    def test_recurrence_dst_and_cancelled_exception(self):
        self.create(
            startTime="2026-10-18T10:00:00+02:00",
            endTime="2026-10-18T11:00:00+02:00",
            timezone="Europe/Rome",
            recurrence={"frequency": "weekly", "count": 3},
        )
        first = datetime(2026, 10, 18, 7, 45, tzinfo=UTC)
        second = datetime(2026, 10, 25, 8, 45, tzinfo=UTC)
        self.assertEqual(self.tick(self.root, now=first)["delivered"], 1)
        self.assertEqual(self.tick(self.root, now=second)["delivered"], 1)
        notices = self.list(self.root, {}, now=second)["notifications"]
        self.assertEqual(len(notices), 2)
        event_id = notices[0]["event_id"]
        status, result = self.actions.handle_action(
            self.root,
            {
                "action": "delete",
                "id": event_id,
                "expected_revision": 1,
                "recurrence_scope": "occurrence",
            },
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(self.list(self.root, {}, now=second)["total"], 1)

    def test_google_cancelled_and_email_reminders_are_not_local_popups(self):
        self.create(source="google_calendar")
        self.create(status="cancelled")
        self.create(reminders=[{"minutes_before": 15, "method": "email"}])
        self.assertEqual(self.tick(self.root, now=self.now)["delivered"], 0)

    def test_hook_and_backend_use_trusted_actor_without_any_frontend(self):
        now = datetime.now(UTC)
        self.create(
            startTime=(now + timedelta(minutes=15)).isoformat(),
            endTime=(now + timedelta(minutes=45)).isoformat(),
        )
        app_root = Path(__file__).resolve().parents[1]
        payload = {
            "app_id": "calendar",
            "workspace_id": "default",
            "data_root": str(self.root),
            "body": {},
        }
        tick = run_json_entrypoint(
            app_root / "hooks/background_tick.py", payload=payload, cwd=app_root
        )
        self.assertEqual(tick["delivered"], 1)
        self.assertEqual(tick["app_events"][0]["resource"], "notifications")
        listed = run_json_entrypoint(
            app_root / "backend/app_backend.py",
            payload={
                **payload,
                "user_id": "alice",
                "body": {"action": "notifications.list"},
            },
            cwd=app_root,
        )
        notification_id = listed["json"]["notifications"][0]["id"]
        dismissed = run_json_entrypoint(
            app_root / "backend/app_backend.py",
            payload={
                **payload,
                "user_id": "alice",
                "body": {
                    "action": "notifications.dismiss",
                    "id": notification_id,
                    "user_id": "bob",
                },
            },
            cwd=app_root,
        )
        self.assertEqual(dismissed["status_code"], 200)
        self.assertEqual(dismissed["app_events"][0]["resource"], "notifications")
        self.assertEqual(self.list(self.root, {}, user_id="alice", now=now)["total"], 0)
        self.assertEqual(self.list(self.root, {}, user_id="bob", now=now)["total"], 1)

    def test_limits_retention_and_workspace_isolation(self):
        self.create()
        self.tick(self.root, now=self.now)
        self.assertEqual(
            self.list(Path(self.temp.name) / "other", {}, now=self.now)["total"], 0
        )
        with self.assertRaises(ValueError):
            self.list(self.root, {"limit": 101}, now=self.now)
        with self.assertRaises(ValueError):
            self.dismiss(self.root, "a" * 64)
        self.assertEqual(
            self.list(self.root, {}, now=self.now + timedelta(days=31))["total"], 0
        )

    def test_backlog_drains_without_skipping_equal_due_times(self):
        for _ in range(5):
            self.create()
        with patch("reminders.MAX_DELIVERIES", 2):
            first = self.tick(self.root, now=self.now)
            second = self.tick(self.root, now=self.now)
            third = self.tick(self.root, now=self.now)
        self.assertEqual(
            [first["delivered"], second["delivered"], third["delivered"]], [2, 2, 1]
        )
        self.assertEqual(first["next_due_in_seconds"], 1)
        self.assertEqual(self.list(self.root, {}, now=self.now)["total"], 5)
        self.assertEqual(self.tick(self.root, now=self.now)["delivered"], 0)

    def test_first_activation_and_outage_have_bounded_catchup(self):
        self.create(startTime="2026-10-01T10:00:00Z", endTime="2026-10-01T11:00:00Z")
        self.create()
        self.assertEqual(self.tick(self.root, now=self.now)["delivered"], 1)
        self.create(startTime="2026-10-10T10:00:00Z", endTime="2026-10-10T11:00:00Z")
        self.create(startTime="2026-10-20T10:00:00Z", endTime="2026-10-20T11:00:00Z")
        resumed = self.now + timedelta(days=14)
        self.assertEqual(self.tick(self.root, now=resumed)["delivered"], 1)
        self.assertEqual(self.list(self.root, {}, now=resumed)["total"], 2)
