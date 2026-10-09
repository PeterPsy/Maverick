"""Durable local popup reminders, driven by the platform background hook."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json

from core.app_sdk.storage import read_json_state, update_json_state
from recurrence import expand_events
from store import read_state
from time_values import format_time, iso_time

REMINDER_FILE = "reminders.json"
CATCHUP = timedelta(days=7)
RETENTION = timedelta(days=30)
MAX_MINUTES = 40320
MAX_DELIVERIES = 1000


def _default():
    return {"checked_at": None, "notifications": {}}


def _minutes(event):
    for reminder in event.get("reminders") or []:
        if not isinstance(reminder, dict) or reminder.get("method", "popup") != "popup":
            continue
        value = reminder.get("minutes_before", reminder.get("minutes"))
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= MAX_MINUTES
        ):
            yield value


def _key(event, due):
    return sha256(
        json.dumps([event["id"], event["startTime"], format_time(due)]).encode()
    ).hexdigest()


def _candidates(events, after, before):
    """Expand only each local event's own reminder window, including exceptions."""
    for event in events:
        if (
            event.get("source") == "google_calendar"
            or event.get("status") == "cancelled"
        ):
            continue
        # An exception may introduce a reminder which is absent on the master.
        minutes = list(_minutes(event))
        for patch in (event.get("recurrence") or {}).get("exceptions", {}).values():
            minutes.extend(_minutes(patch))
        if not minutes:
            continue
        end = before + timedelta(minutes=max(minutes), seconds=1)
        for occurrence in expand_events([event], format_time(after), format_time(end)):
            if occurrence.get("status") == "cancelled":
                continue
            for value in set(_minutes(occurrence)):
                due = iso_time(occurrence["startTime"], "startTime") - timedelta(
                    minutes=value
                )
                if after <= due <= before:
                    yield _key(occurrence, due), occurrence, due


def reminder_tick(data_root, *, now=None):
    now = now or datetime.now(UTC)
    result = {"delivered": 0, "next_due_in_seconds": 15}

    def update(state):
        checked = (
            iso_time(state["checked_at"], "checked_at")
            if state.get("checked_at")
            else now - timedelta(minutes=1)
        )
        current = max(now, checked)
        after = max(current - CATCHUP, checked)
        events = read_state(data_root)["events"]
        existing = state.get("notifications") or {}
        # Include delivered records in validation so moves/deletes retract alerts.
        validate_after = min(
            [after, *(iso_time(n["due_at"], "due_at") for n in existing.values())]
        )
        candidates = dict(
            (key, (event, due))
            for key, event, due in _candidates(events, validate_after, current)
        )
        notices = {}
        for key, notice in existing.items():
            if (
                key not in candidates
                or iso_time(notice["due_at"], "due_at") < current - RETENTION
            ):
                continue
            event, _due = candidates[key]
            notices[key] = {
                **notice,
                "title": event["title"],
                "timezone": event["timezone"],
            }
        deferred = []
        for key, (event, due) in sorted(
            candidates.items(), key=lambda item: item[1][1]
        ):
            if key in notices or due < after:
                continue
            if result["delivered"] >= MAX_DELIVERIES:
                deferred.append(due)
                continue
            notices[key] = {
                "id": key,
                "event_id": event["id"],
                "title": event["title"],
                "startTime": event["startTime"],
                "timezone": event["timezone"],
                "due_at": format_time(due),
                "created_at": format_time(current),
                "dismissed_by": {},
            }
            result["delivered"] += 1
        watermark = min(deferred) if deferred else current
        result["next_due_in_seconds"] = 1 if deferred else 15
        result["changed"] = notices != existing
        return {"checked_at": format_time(watermark), "notifications": notices}

    update_json_state(data_root, REMINDER_FILE, update, _default())
    if result.pop("changed", False):
        result["app_events"] = [
            {"type": "maverick.app.data-changed", "resource": "notifications"}
        ]
    return result


def list_notifications(data_root, body, *, user_id=None, now=None):
    now = now or datetime.now(UTC)
    state = read_json_state(data_root, REMINDER_FILE, _default())
    notices = [
        n
        for n in (state.get("notifications") or {}).values()
        if user_id not in (n.get("dismissed_by") or {})
        and iso_time(n["due_at"], "due_at") >= now - RETENTION
    ]
    # Reads always validate against current events, including a mutation racing a tick.
    if notices:
        after = min(iso_time(n["due_at"], "due_at") for n in notices)
        valid = {
            key: event
            for key, event, _ in _candidates(
                read_state(data_root)["events"], after, now
            )
        }
        notices = [
            {
                **{k: v for k, v in n.items() if k != "dismissed_by"},
                "title": valid[n["id"]]["title"],
            }
            for n in notices
            if n["id"] in valid
        ]
    notices.sort(key=lambda n: (n["due_at"], n["id"]), reverse=True)
    notices = [
        {
            **n,
            "scheduled_at": n["startTime"],
            "open_params": {"event_id": n["event_id"]},
        }
        for n in notices
    ]
    offset, limit = body.get("offset", 0), body.get("limit", 50)
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("`offset` must be a nonnegative integer.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("`limit` must be an integer from 1 to 100.")
    return {
        "notifications": notices[offset : offset + limit],
        "total": len(notices),
        "has_more": offset + limit < len(notices),
        "checked_at": state.get("checked_at"),
    }


def dismiss_notification(data_root, notification_id, *, user_id=None, now=None):
    if not user_id:
        raise ValueError("Notification dismissal requires an authenticated user.")
    if not isinstance(notification_id, str) or len(notification_id) != 64:
        raise ValueError("`id` must identify a reminder notification.")

    def update(state):
        notice = (state.get("notifications") or {}).get(notification_id)
        if notice:
            notice.setdefault("dismissed_by", {}).setdefault(
                user_id, format_time(now or datetime.now(UTC))
            )
        return state

    update_json_state(data_root, REMINDER_FILE, update, _default())
    return {"id": notification_id, "dismissed": True}
