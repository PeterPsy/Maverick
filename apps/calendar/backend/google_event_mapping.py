"""Google event resources mapped to Calendar domain records."""

from __future__ import annotations
from typing import Any
from constants import (
    GOOGLE_PROVIDER,
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_ORGANIZER_LENGTH,
)
from time_values import format_time, iso_time
from google_reconciliation import google_idempotency_key

GOOGLE_COLOR_MAP = {
    "1": "blue",
    "2": "green",
    "3": "purple",
    "4": "red",
    "5": "orange",
    "6": "orange",
    "7": "blue",
    "8": "purple",
    "9": "blue",
    "10": "green",
    "11": "red",
}


def google_event_payload(
    remote_event: dict[str, Any],
    *,
    connection: dict[str, Any],
    calendar: dict[str, Any],
) -> dict[str, Any] | None:
    start_value, all_day, timezone_name = _google_event_time(
        remote_event.get("start"), calendar["timezone"]
    )
    end_value, _end_all_day, end_timezone = _google_event_time(
        remote_event.get("end"), timezone_name
    )
    if not start_value or not end_value:
        return None
    timezone_name = timezone_name or end_timezone or calendar["timezone"] or "UTC"
    organizer = _person_label(
        remote_event.get("organizer"), max_length=MAX_ORGANIZER_LENGTH
    )
    attendees = [
        _person_label(item)
        for item in remote_event.get("attendees") or []
        if isinstance(item, dict)
    ]
    reminders = _reminders(remote_event.get("reminders"))
    recurrence = remote_event.get("recurrence")
    return {
        "title": _bounded_text(
            remote_event.get("summary"),
            max_length=MAX_TITLE_LENGTH,
            fallback="(Untitled Google event)",
        ),
        "description": _bounded_text(
            remote_event.get("description"), max_length=MAX_DESCRIPTION_LENGTH
        ),
        "startTime": start_value,
        "endTime": end_value,
        "timezone": timezone_name,
        "location": _bounded_text(
            remote_event.get("location"), max_length=MAX_LOCATION_LENGTH
        ),
        "organizer": organizer,
        "all_day": all_day,
        "transparency": remote_event.get("transparency") or "opaque",
        "status": _event_status(remote_event.get("status")),
        "color": GOOGLE_COLOR_MAP.get(
            str(remote_event.get("colorId") or "").strip(), "blue"
        ),
        "category": "Google Calendar",
        "attendees": [item for item in attendees if item],
        "attendee_details": [
            item
            for item in remote_event.get("attendees") or []
            if isinstance(item, dict) and item.get("email")
        ][:50],
        "conference": _conference(remote_event),
        "tags": ["google"],
        "source": "google_calendar",
        "external_refs": _external_refs(
            remote_event, connection=connection, calendar=calendar
        ),
        "recurrence": {"rules": recurrence} if isinstance(recurrence, list) else {},
        "reminders": reminders,
        "reminders_use_default": bool(
            (remote_event.get("reminders") or {}).get("useDefault", not bool(reminders))
        ),
        "idempotency_key": google_idempotency_key(
            connection["id"],
            calendar["provider_calendar_id"],
            str(remote_event.get("id") or ""),
        ),
        "created_at": _optional_google_time(remote_event.get("created")),
        "updated_at": _optional_google_time(remote_event.get("updated")),
    }


def _google_event_time(value: Any, default_timezone: str) -> tuple[str, bool, str]:
    if not isinstance(value, dict):
        return "", False, default_timezone
    timezone_name = str(value.get("timeZone") or default_timezone or "UTC").strip()
    date_time = str(value.get("dateTime") or "").strip()
    if date_time:
        return date_time, False, timezone_name
    date_value = str(value.get("date") or "").strip()
    if date_value:
        return date_value, True, timezone_name
    return "", False, timezone_name


def _event_status(value: Any) -> str:
    status = str(value or "confirmed").strip().lower()
    return status if status in {"confirmed", "tentative"} else "confirmed"


def _person_label(value: Any, *, max_length: int = 120) -> str:
    if not isinstance(value, dict):
        return ""
    return _bounded_text(
        value.get("email") or value.get("displayName"), max_length=max_length
    )


def _bounded_text(value: Any, *, max_length: int, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text[:max_length]


def _external_refs(
    remote_event: dict[str, Any],
    *,
    connection: dict[str, Any],
    calendar: dict[str, Any],
) -> dict[str, Any]:
    refs = {
        "provider": GOOGLE_PROVIDER,
        "calendar_account_id": connection.get("account_id", ""),
        "calendar_account_label": connection.get("account_label", ""),
        "calendar_connection_id": connection["id"],
        "provider_calendar_id": calendar["provider_calendar_id"],
        "provider_calendar_summary": calendar.get("summary", ""),
        "provider_calendar_access_role": calendar.get("access_role", ""),
        "provider_event_id": remote_event.get("id"),
        "htmlLink": remote_event.get("htmlLink"),
        "etag": remote_event.get("etag"),
        "iCalUID": remote_event.get("iCalUID"),
        "recurring_event_id": remote_event.get("recurringEventId"),
        "original_start_time": remote_event.get("originalStartTime"),
        "event_type": remote_event.get("eventType") or "default",
        "provider_color_id": remote_event.get("colorId"),
    }
    return {key: value for key, value in refs.items() if value not in (None, "")}


def _conference(remote):
    data = remote.get("conferenceData") or {}
    points = [
        {
            "type": point.get("entryPointType", "video"),
            "uri": str(point.get("uri") or "")[:2048],
            "label": str(point.get("label") or "")[:160],
        }
        for point in data.get("entryPoints") or []
        if isinstance(point, dict) and point.get("uri")
    ][:2]
    if not points and remote.get("hangoutLink"):
        points = [
            {
                "type": "video",
                "uri": str(remote["hangoutLink"])[:2048],
                "label": "Google Meet",
            }
        ]
    return (
        {
            "provider": str(
                (data.get("conferenceSolution") or {}).get("name") or "Google Meet"
            )[:160],
            "entry_points": points,
        }
        if points
        else {}
    )


def _reminders(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    reminders: list[dict[str, Any]] = []
    for item in value.get("overrides") or []:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip()
        minutes = item.get("minutes")
        if method and isinstance(minutes, int):
            reminders.append({"method": method, "minutes_before": minutes})
    return reminders


def _optional_google_time(value: Any) -> str:
    if not value:
        return ""
    try:
        return format_time(iso_time(value, "google_time"))
    except ValueError:
        return ""
