"""Provider write projections: updates send only changed domain fields."""

from zoneinfo import ZoneInfo
from google_event_mapping import GOOGLE_COLOR_MAP
from recurrence import recurrence_rules
from time_values import iso_time


def google_event_body(event):
    body = {
        "summary": event["title"],
        "description": event.get("description") or "",
        "location": event.get("location") or "",
        "status": event.get("status") or "confirmed",
        "transparency": event.get("transparency") or "opaque",
        "start": google_time(event["startTime"], event),
        "end": google_time(event["endTime"], event),
        "attendees": google_attendees(event),
        "reminders": google_reminders(event),
    }
    if not (event.get("external_refs") or {}).get("recurring_event_id"):
        body["recurrence"] = recurrence_rules(event.get("recurrence"))
    color = google_color_id(event)
    if color:
        body["colorId"] = color
    return body


def google_event_patch(before, after):
    full = google_event_body(after)
    fields = {
        "title": "summary",
        "description": "description",
        "location": "location",
        "status": "status",
        "transparency": "transparency",
        "color": "colorId",
        "recurrence": "recurrence",
    }
    body = {
        remote: full[remote]
        for local, remote in fields.items()
        if before.get(local) != after.get(local) and remote in full
    }
    timing = any(before.get(key) != after.get(key) for key in ("timezone", "all_day"))
    for local, remote in (("startTime", "start"), ("endTime", "end")):
        if timing or before.get(local) != after.get(local):
            body[remote] = full[remote]
    if any(
        before.get(key) != after.get(key) for key in ("attendees", "attendee_details")
    ):
        body["attendees"] = full["attendees"]
    if any(
        before.get(key) != after.get(key)
        for key in ("reminders", "reminders_use_default")
    ):
        body["reminders"] = full["reminders"]
    return body


def google_attendees(event):
    details = {
        str(p.get("email", "")).casefold(): p
        for p in event.get("attendee_details") or []
    }
    writable = {
        "email",
        "displayName",
        "optional",
        "responseStatus",
        "additionalGuests",
        "comment",
        "resource",
    }
    return [
        {
            **{
                k: v
                for k, v in details.get(email.casefold(), {}).items()
                if k in writable
            },
            "email": email,
        }
        for email in event.get("attendees") or []
        if isinstance(email, str) and email.strip()
    ]


def merge_google_people(before, after, remote):
    """Keep provider metadata when editing invitees on an older local mirror."""
    previous = {p["email"].casefold(): p for p in before.get("attendee_details") or []}
    wanted = {p["email"].casefold(): p for p in after.get("attendee_details") or []}
    fresh = {
        p["email"].casefold(): p
        for p in remote.get("attendees") or []
        if isinstance(p, dict) and p.get("email")
    }
    details = []
    for email in after.get("attendees") or []:
        key = email.casefold()
        edits = {
            k: v
            for k, v in wanted.get(key, {}).items()
            if previous.get(key, {}).get(k) != v
        }
        details.append(
            {**fresh.get(key, previous.get(key, {})), **edits, "email": email}
        )
    return {**after, "attendee_details": details}


def google_time(value, event):
    zone = str(event.get("timezone") or "UTC")
    if event.get("all_day"):
        return {
            "date": iso_time(value, "event_time")
            .astimezone(ZoneInfo(zone))
            .date()
            .isoformat()
        }
    return {"dateTime": str(value), "timeZone": zone}


def google_reminders(event):
    if event.get("reminders_use_default"):
        return {"useDefault": True}
    overrides = []
    for item in event.get("reminders") or []:
        if not isinstance(item, dict):
            continue
        minutes = item.get("minutes_before", item.get("minutesBefore"))
        if item.get("method") and isinstance(minutes, int):
            overrides.append({"method": item["method"], "minutes": minutes})
    return {"useDefault": False, "overrides": overrides}


def google_color_id(event):
    color = str(event.get("color") or "")
    original = str((event.get("external_refs") or {}).get("provider_color_id") or "")
    if original and GOOGLE_COLOR_MAP.get(original) == color:
        return original
    return {
        "blue": "1",
        "green": "2",
        "purple": "3",
        "red": "4",
        "orange": "5",
        "pink": "4",
    }.get(color, "")
