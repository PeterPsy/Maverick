"""Calendar event record normalization and filtering."""

from __future__ import annotations

from typing import Any
from event_people import attendee_details
from zoneinfo import ZoneInfo

from constants import (
    ALLOWED_COLORS,
    ALLOWED_EVENT_STATUSES,
    MAX_CATEGORY_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_EXTERNAL_LINK_LENGTH,
    MAX_LIST_ITEMS,
    MAX_LOCATION_LENGTH,
    MAX_ORGANIZER_LENGTH,
    MAX_PROVIDER_ID_LENGTH,
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
from time_values import (
    event_time,
    event_timestamp,
    event_timezone,
    format_time,
    iso_time,
)


def normalize_event(
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
    created_at: Any = None,
    updated_at: Any = None,
    revision: int | None = None,
) -> dict[str, Any]:
    event_identifier = clean_string(
        event_id or payload.get("id"), "id", required=True, max_length=80
    )
    title = clean_string(
        payload.get("title"), "title", required=True, max_length=MAX_TITLE_LENGTH
    )
    timezone_name = event_timezone(payload.get("timezone"))
    start_time = event_time(
        payload.get("startTime") or payload.get("start_time"),
        "startTime",
        timezone_name,
    )
    end_time = event_time(
        payload.get("endTime") or payload.get("end_time"), "endTime", timezone_name
    )
    if end_time <= start_time:
        raise ValueError("Event endTime must be after startTime.")
    all_day = optional_bool(
        payload.get("all_day") if "all_day" in payload else payload.get("allDay"),
        default=False,
    )
    if all_day:
        zone = ZoneInfo(timezone_name)
        start_date, end_date = (
            start_time.astimezone(zone).date(),
            end_time.astimezone(zone).date(),
        )
        from datetime import datetime, time, timedelta

        if end_date <= start_date:
            # Old local all-day records could carry hourly timestamps on one date.
            end_date = start_date + timedelta(days=1)

        start_time = datetime.combine(start_date, time.min, zone)
        end_time = datetime.combine(end_date, time.min, zone)
    color = clean_string(
        payload.get("color") or "blue", "color", required=True, max_length=24
    )
    if color not in ALLOWED_COLORS:
        raise ValueError(
            f"Event color must be one of: {', '.join(sorted(ALLOWED_COLORS))}."
        )
    status = _event_status(payload.get("status"))
    transparency = str(payload.get("transparency") or "opaque").lower()
    if transparency not in {"opaque", "transparent"}:
        raise ValueError("Event transparency must be opaque or transparent.")
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
    from recurrence import validate_recurrence

    validate_recurrence(
        {**payload, "timezone": timezone_name, "startTime": format_time(start_time)}
    )
    return {
        "id": event_identifier,
        "title": title,
        "description": clean_string(
            payload.get("description"), "description", max_length=MAX_DESCRIPTION_LENGTH
        ),
        "startTime": format_time(start_time),
        "endTime": format_time(end_time),
        "status": status,
        "transparency": transparency,
        "timezone": timezone_name,
        "location": clean_string(
            payload.get("location"), "location", max_length=MAX_LOCATION_LENGTH
        ),
        "organizer": clean_string(
            payload.get("organizer"), "organizer", max_length=MAX_ORGANIZER_LENGTH
        ),
        "all_day_start": (
            start_time.astimezone(ZoneInfo(timezone_name)).date().isoformat()
            if all_day
            else ""
        ),
        "all_day_end": (
            end_time.astimezone(ZoneInfo(timezone_name)).date().isoformat()
            if all_day
            else ""
        ),
        "all_day": all_day,
        "color": color,
        "category": clean_string(
            payload.get("category") or "Meeting",
            "category",
            max_length=MAX_CATEGORY_LENGTH,
        ),
        "attendees": string_list(payload.get("attendees")),
        "attendee_details": attendee_details(payload.get("attendee_details"), string_list(payload.get("attendees"))),
        "conference": json_object(payload.get("conference"), "conference"),
        "tags": string_list(payload.get("tags")),
        "created_at": created_value,
        "updated_at": updated_value,
        "revision": (
            revision
            if revision is not None
            else event_revision(payload.get("revision"))
        ),
        "source": clean_string(
            payload.get("source") or "calendar",
            "source",
            required=True,
            max_length=MAX_SOURCE_LENGTH,
        ),
        "external_refs": normalize_external_refs(
            payload.get("external_refs") or payload.get("externalRefs")
        ),
        "recurrence": json_object(payload.get("recurrence"), "recurrence"),
        "reminders": json_list(payload.get("reminders"), "reminders"),
        "reminders_use_default": optional_bool(
            payload.get("reminders_use_default"),
            default=not bool(payload.get("reminders")),
        ),
        "idempotency_key": clean_string(
            payload.get("idempotency_key") or payload.get("idempotencyKey"),
            "idempotency_key",
            max_length=160,
        ),
    }


def _event_status(value: Any) -> str:
    status = str(value or "confirmed").strip().lower()
    if status not in ALLOWED_EVENT_STATUSES:
        raise ValueError(
            "Event status must be one of: cancelled, confirmed, tentative."
        )
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
        if tag_filter and tag_filter.isdisjoint(
            casefold_set(string_list(event.get("tags")))
        ):
            continue
        if category_filter and casefold_text(event.get("category")) != category_filter:
            continue
        if attendee_filter and attendee_filter not in casefold_set(
            string_list(event.get("attendees"))
        ):
            continue
        if query_filter and query_filter not in _event_search_text(event):
            continue
        filtered.append(event)
    return filtered


def event_profile(
    event: dict[str, Any], *, profile: str, include_description: bool
) -> dict[str, Any]:
    if profile == "full":
        item = dict(event)
    else:
        item = {
            "id": event["id"],
            "title": event["title"],
            "startTime": event["startTime"],
            "endTime": event["endTime"],
            "status": event.get("status", "confirmed"),
            "transparency": event.get("transparency", "opaque"),
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


def normalize_external_refs(value: Any) -> dict[str, Any]:
    refs = json_object(value, "external_refs")
    scalar_fields = {
        "calendar_account_id": (
            "calendarAccountId",
            "calendar_account",
            "account_id",
            "account",
        ),
        "calendar_account_label": (
            "calendarAccountLabel",
            "account_label",
            "accountLabel",
        ),
        "calendar_connection_id": (
            "calendarConnectionId",
            "connection_id",
            "connectionId",
        ),
        "provider_calendar_id": (
            "providerCalendarId",
            "google_calendar_id",
            "googleCalendarId",
        ),
        "provider_event_id": ("providerEventId", "google_event_id", "googleEventId"),
        "etag": ("eTag",),
        "ical_uid": ("icalUid", "iCalUID", "iCalUid", "icalUID"),
    }
    for canonical, aliases in scalar_fields.items():
        _copy_scalar_ref(refs, canonical, aliases, max_length=MAX_PROVIDER_ID_LENGTH)
    _copy_scalar_ref(
        refs, "html_link", ("htmlLink",), max_length=MAX_EXTERNAL_LINK_LENGTH
    )
    return refs


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


def _copy_scalar_ref(
    refs: dict[str, Any], canonical: str, aliases: tuple[str, ...], *, max_length: int
) -> None:
    for key in (canonical, *aliases):
        value = refs.get(key)
        if value not in (None, ""):
            refs[canonical] = clean_string(value, canonical, max_length=max_length)
            return


def event_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value[:MAX_LIST_ITEMS]:
        text = str(item).strip()
        if text:
            ids.append(text[:80])
    return ids
