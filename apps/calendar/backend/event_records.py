"""Calendar event record normalization and filtering."""

from __future__ import annotations

from typing import Any

from constants import (
    ALLOWED_COLORS,
    ALLOWED_EVENT_STATUSES,
    MAX_CATEGORY_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_LIST_ITEMS,
    MAX_LOCATION_LENGTH,
    MAX_ORGANIZER_LENGTH,
    MAX_SOURCE_LENGTH,
    MAX_TITLE_LENGTH,
)
from scalars import (
    casefold_set,
    casefold_text,
    clean_string,
    json_list,
    json_object,
    optional_bool,
    optional_int,
    string_list,
)
from time_values import event_time, event_timestamp, event_timezone, format_time, iso_time


def normalize_event(
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
    created_at: Any = None,
    updated_at: Any = None,
    revision: int | None = None,
) -> dict[str, Any]:
    event_identifier = clean_string(event_id or payload.get("id"), "id", required=True, max_length=80)
    title = clean_string(payload.get("title"), "title", required=True, max_length=MAX_TITLE_LENGTH)
    timezone_name = event_timezone(payload.get("timezone"))
    start_time = event_time(payload.get("startTime") or payload.get("start_time"), "startTime", timezone_name)
    end_time = event_time(payload.get("endTime") or payload.get("end_time"), "endTime", timezone_name)
    if end_time <= start_time:
        raise ValueError("Event endTime must be after startTime.")
    color = clean_string(payload.get("color") or "blue", "color", required=True, max_length=24)
    if color not in ALLOWED_COLORS:
        raise ValueError(f"Event color must be one of: {', '.join(sorted(ALLOWED_COLORS))}.")
    status = _event_status(payload.get("status"))
    created_value = event_timestamp(
        created_at or payload.get("created_at") or payload.get("createdAt"),
        "created_at",
        default=format_time(start_time),
    )
    updated_value = event_timestamp(
        updated_at or payload.get("updated_at") or payload.get("updatedAt"),
        "updated_at",
        default=created_value,
    )
    return {
        "id": event_identifier,
        "title": title,
        "description": clean_string(payload.get("description"), "description", max_length=MAX_DESCRIPTION_LENGTH),
        "startTime": format_time(start_time),
        "endTime": format_time(end_time),
        "status": status,
        "timezone": timezone_name,
        "location": clean_string(payload.get("location"), "location", max_length=MAX_LOCATION_LENGTH),
        "organizer": clean_string(payload.get("organizer"), "organizer", max_length=MAX_ORGANIZER_LENGTH),
        "all_day": optional_bool(payload.get("all_day") if "all_day" in payload else payload.get("allDay"), default=False),
        "color": color,
        "category": clean_string(payload.get("category") or "Meeting", "category", max_length=MAX_CATEGORY_LENGTH),
        "attendees": string_list(payload.get("attendees")),
        "tags": string_list(payload.get("tags")),
        "created_at": created_value,
        "updated_at": updated_value,
        "revision": revision if revision is not None else event_revision(payload.get("revision")),
        "source": clean_string(payload.get("source") or "calendar", "source", required=True, max_length=MAX_SOURCE_LENGTH),
        "external_refs": json_object(payload.get("external_refs") or payload.get("externalRefs"), "external_refs"),
        "recurrence": json_object(payload.get("recurrence"), "recurrence"),
        "reminders": json_list(payload.get("reminders"), "reminders"),
        "idempotency_key": clean_string(
            payload.get("idempotency_key") or payload.get("idempotencyKey"),
            "idempotency_key",
            max_length=160,
        ),
    }


def _event_status(value: Any) -> str:
    status = str(value or "confirmed").strip().lower()
    if status not in ALLOWED_EVENT_STATUSES:
        raise ValueError("Event status must be one of: cancelled, confirmed, tentative.")
    return status


def filter_events(
    events: list[dict[str, Any]],
    *,
    start_after: Any = None,
    end_before: Any = None,
    query: str = "",
    tags: Any = None,
    category: Any = None,
    attendee: Any = None,
) -> list[dict[str, Any]]:
    after = iso_time(start_after, "start_after") if start_after else None
    before = iso_time(end_before, "end_before") if end_before else None
    tag_filter = casefold_set(string_list(tags))
    category_filter = casefold_text(category)
    attendee_filter = casefold_text(attendee)
    query_filter = query.strip().casefold()
    filtered: list[dict[str, Any]] = []
    for event in events:
        start_time = iso_time(event["startTime"], "startTime")
        end_time = iso_time(event["endTime"], "endTime")
        if after and end_time <= after:
            continue
        if before and start_time >= before:
            continue
        if tag_filter and tag_filter.isdisjoint(casefold_set(string_list(event.get("tags")))):
            continue
        if category_filter and casefold_text(event.get("category")) != category_filter:
            continue
        if attendee_filter and attendee_filter not in casefold_set(string_list(event.get("attendees"))):
            continue
        if query_filter and query_filter not in _event_search_text(event):
            continue
        filtered.append(event)
    return filtered


def event_profile(event: dict[str, Any], *, profile: str, include_description: bool) -> dict[str, Any]:
    if profile == "full":
        item = dict(event)
    else:
        item = {
            "id": event["id"],
            "title": event["title"],
            "startTime": event["startTime"],
            "endTime": event["endTime"],
            "status": event.get("status", "confirmed"),
            "timezone": event.get("timezone", "UTC"),
            "all_day": event.get("all_day", False),
            "location": event.get("location", ""),
            "category": event.get("category"),
            "attendees": event.get("attendees", []),
            "tags": event.get("tags", []),
            "revision": event.get("revision", 1),
        }
    if not include_description:
        item.pop("description", None)
    return item


def event_revision(value: Any) -> int:
    revision = optional_int(value, field="revision", minimum=1)
    return revision or 1


def _event_search_text(event: dict[str, Any]) -> str:
    return " ".join(
        [
            str(event.get("title") or ""),
            str(event.get("description") or ""),
            str(event.get("category") or ""),
            str(event.get("location") or ""),
            str(event.get("organizer") or ""),
            " ".join(string_list(event.get("attendees"))),
            " ".join(string_list(event.get("tags"))),
        ]
    ).casefold()


def event_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value[:MAX_LIST_ITEMS]:
        text = str(item).strip()
        if text:
            ids.append(text[:80])
    return ids
