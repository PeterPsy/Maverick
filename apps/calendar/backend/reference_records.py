"""Calendar reference record serialization."""

from __future__ import annotations

from typing import Any

from scalars import string_list


def reference_record(event: dict[str, Any], *, app_id: str = "calendar") -> dict[str, Any]:
    subtitle = f"{event['startTime']} to {event['endTime']}"
    return {
        "app_id": app_id,
        "entity_type": "event",
        "entity_id": event["id"],
        "title": event["title"],
        "subtitle": subtitle,
        "summary": _event_summary(event),
        "app_page": f"events/{event['id']}",
        "deep_link": event_deep_link(app_id, event["id"]),
        "safe_fields": {
            "id": event["id"],
            "title": event["title"],
            "startTime": event["startTime"],
            "endTime": event["endTime"],
            "status": event.get("status", "confirmed"),
            "timezone": event.get("timezone", "UTC"),
            "location": event.get("location", ""),
            "organizer": event.get("organizer", ""),
            "all_day": event.get("all_day", False),
            "category": event.get("category"),
            "attendees": event.get("attendees", []),
            "tags": event.get("tags", []),
            "revision": event.get("revision", 1),
            "source": event.get("source", "calendar"),
        },
    }


def event_deep_link(app_id: str, event_id: str) -> str:
    return f"/app/{app_id}/events/{event_id}"


def _event_summary(event: dict[str, Any]) -> str:
    category = str(event.get("category") or "Event")
    status = str(event.get("status") or "confirmed")
    attendees = string_list(event.get("attendees"))
    attendee_text = f" with {', '.join(attendees[:3])}" if attendees else ""
    location = str(event.get("location") or "").strip()
    location_text = f" at {location}" if location else ""
    status_text = "" if status == "confirmed" else f" ({status})"
    all_day_text = " all day" if event.get("all_day") else f" from {event['startTime']} to {event['endTime']}"
    return f"{category}: {event['title']}{status_text}{all_day_text}{location_text}{attendee_text}."
