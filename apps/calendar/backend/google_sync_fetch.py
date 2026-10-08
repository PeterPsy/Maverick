"""Bounded Google pagination and calendar discovery with independent local settings."""

from typing import Any
from google_oauth import HttpTransport
from google_provider import list_calendar_list, list_events
from google_records import normalize_calendar
from scalars import optional_int

DEFAULT_CALENDAR_LIMIT = MAX_CALENDAR_LIMIT = 50
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_SIZE = MAX_PAGE_SIZE = 250


def _fetch_calendar_list(
    access_token: str, body: dict[str, Any], *, transport: HttpTransport | None
) -> list[dict[str, Any]]:
    calendar_limit = (
        optional_int(
            body.get("calendar_limit") or body.get("calendarLimit"),
            field="calendar_limit",
            minimum=1,
            maximum=MAX_CALENDAR_LIMIT,
        )
        or DEFAULT_CALENDAR_LIMIT
    )
    page_limit = (
        optional_int(
            body.get("calendar_list_page_limit") or body.get("calendarListPageLimit"),
            field="calendar_list_page_limit",
            minimum=1,
            maximum=MAX_PAGE_LIMIT,
        )
        or DEFAULT_PAGE_LIMIT
    )
    page_size = (
        optional_int(
            body.get("calendar_list_page_size") or body.get("calendarListPageSize"),
            field="calendar_list_page_size",
            minimum=1,
            maximum=MAX_PAGE_SIZE,
        )
        or DEFAULT_PAGE_SIZE
    )
    page_token = ""
    calendars: list[dict[str, Any]] = []
    for _page_index in range(page_limit):
        payload = list_calendar_list(
            access_token=access_token,
            page_token=page_token,
            max_results=page_size,
            transport=transport,
        )
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                calendars.append(item)
                if len(calendars) >= calendar_limit:
                    return calendars
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            break
    return calendars


def _fetch_events(
    access_token: str,
    calendar_id: str,
    *,
    sync_token: str,
    time_min: str,
    time_max: str,
    page_limit: int,
    page_size: int,
    transport: HttpTransport | None,
    page_token: str = "",
) -> tuple[list[dict[str, Any]], str, int, str]:
    items: list[dict[str, Any]] = []
    next_sync_token = ""
    for page_index in range(page_limit):
        payload = list_events(
            access_token=access_token,
            calendar_id=calendar_id,
            page_token=page_token,
            sync_token=sync_token,
            time_min=time_min,
            time_max=time_max,
            single_events=bool(time_min or time_max),
            order_by="startTime" if time_min or time_max else "",
            max_results=page_size,
            transport=transport,
        )
        items.extend(
            item for item in payload.get("items") or [] if isinstance(item, dict)
        )
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            next_sync_token = str(payload.get("nextSyncToken") or "").strip()
            return items, next_sync_token, page_index + 1, ""
    return items, "", page_limit, page_token


def _target_calendars(
    items: list[dict[str, Any]],
    *,
    connection_id: str,
    requested_calendar_id: str,
    existing_calendars: Any,
) -> list[dict[str, Any]]:
    calendars = _merge_calendar_preferences(
        [
            normalize_calendar({**item, "connection_id": connection_id})
            for item in items
        ],
        connection_id=connection_id,
        existing_calendars=existing_calendars,
    )
    if requested_calendar_id:
        return [
            item
            for item in calendars
            if (
                item["id"] == requested_calendar_id
                or item["provider_calendar_id"] == requested_calendar_id
            )
            and item.get("sync_enabled", True)
        ]
    return [item for item in calendars if item.get("sync_enabled", True)]


def _replace_connection_calendars(
    existing: Any, connection_id: str, calendars: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    if isinstance(existing, list):
        retained = [
            item
            for item in existing
            if isinstance(item, dict)
            and str(item.get("connection_id") or item.get("connectionId") or "").strip()
            != connection_id
        ]
    normalized = _merge_calendar_preferences(
        [
            normalize_calendar({**item, "connection_id": connection_id})
            for item in calendars
        ],
        connection_id=connection_id,
        existing_calendars=existing,
    )
    known = {item["provider_calendar_id"] for item in normalized}
    retained += [
        item
        for item in existing
        if item.get("connection_id") == connection_id
        and item.get("provider_calendar_id") not in known
    ]
    return [*retained, *normalized]


def _merge_calendar_preferences(
    calendars: list[dict[str, Any]],
    *,
    connection_id: str,
    existing_calendars: Any,
) -> list[dict[str, Any]]:
    preferences = _calendar_preferences(existing_calendars, connection_id=connection_id)
    merged: list[dict[str, Any]] = []
    for calendar in calendars:
        preference = (
            preferences.get(calendar["provider_calendar_id"])
            or preferences.get(calendar["id"])
            or {}
        )
        merged.append(normalize_calendar({**calendar, **preference}))
    return merged


def _calendar_preferences(
    existing: Any, *, connection_id: str
) -> dict[str, dict[str, bool]]:
    if not isinstance(existing, list):
        return {}
    preferences: dict[str, dict[str, bool]] = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        try:
            calendar = normalize_calendar(item)
        except ValueError:
            continue
        if calendar["connection_id"] != connection_id:
            continue
        preference = {
            "selected": bool(calendar.get("selected")),
            "sync_enabled": bool(calendar.get("sync_enabled")),
            "availability_enabled": bool(calendar.get("availability_enabled", True)),
        }
        preferences[calendar["provider_calendar_id"]] = preference
        preferences[calendar["id"]] = preference
    return preferences
