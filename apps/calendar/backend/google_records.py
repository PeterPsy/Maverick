"""Google Calendar source and sync cursor normalization."""

from __future__ import annotations

from typing import Any

from constants import (
    ALLOWED_SYNC_STATUSES,
    GOOGLE_PROVIDER,
    MAX_DESCRIPTION_LENGTH,
    MAX_EXTERNAL_LINK_LENGTH,
    MAX_LIST_ITEM_LENGTH,
    MAX_PROVIDER_ID_LENGTH,
    MAX_REMOTE_CALENDARS,
    MAX_SYNC_CURSORS,
    MAX_TIMEZONE_LENGTH,
    MAX_TITLE_LENGTH,
)
from scalars import clean_string, optional_bool, optional_int
from time_values import optional_time_string


def normalize_calendars(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [normalize_calendar(item) for item in value[:MAX_REMOTE_CALENDARS] if isinstance(item, dict)]


def normalize_calendar(payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = _connection_id(payload)
    provider_calendar_id = clean_string(
        payload.get("provider_calendar_id")
        or payload.get("providerCalendarId")
        or payload.get("google_calendar_id")
        or payload.get("googleCalendarId")
        or payload.get("calendar_id")
        or payload.get("calendarId")
        or payload.get("id"),
        "provider_calendar_id",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    calendar_id = clean_string(
        payload.get("id") or payload.get("calendar_id") or payload.get("calendarId") or f"{connection_id}:{provider_calendar_id}",
        "calendar_id",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    return {
        "id": calendar_id,
        "connection_id": connection_id,
        "provider": GOOGLE_PROVIDER,
        "provider_calendar_id": provider_calendar_id,
        "summary": clean_string(payload.get("summary") or payload.get("name"), "summary", max_length=MAX_TITLE_LENGTH),
        "description": clean_string(payload.get("description"), "description", max_length=MAX_DESCRIPTION_LENGTH),
        "timezone": clean_string(payload.get("timezone") or payload.get("timeZone") or "UTC", "timezone", max_length=MAX_TIMEZONE_LENGTH),
        "access_role": clean_string(payload.get("access_role") or payload.get("accessRole"), "access_role", max_length=MAX_LIST_ITEM_LENGTH),
        "primary": optional_bool(payload.get("primary"), default=False),
        "selected": optional_bool(payload.get("selected"), default=True),
        "sync_enabled": optional_bool(payload.get("sync_enabled") if "sync_enabled" in payload else payload.get("syncEnabled"), default=True),
        "color": clean_string(payload.get("color") or payload.get("backgroundColor"), "color", max_length=MAX_LIST_ITEM_LENGTH),
        "etag": clean_string(payload.get("etag"), "etag", max_length=MAX_PROVIDER_ID_LENGTH),
        "updated_at": optional_time_string(payload.get("updated_at") or payload.get("updatedAt"), "updated_at"),
    }


def normalize_sync_state(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [normalize_sync_cursor(item) for item in value[:MAX_SYNC_CURSORS] if isinstance(item, dict)]


def normalize_sync_cursor(payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = _connection_id(payload)
    provider_calendar_id = clean_string(
        payload.get("provider_calendar_id")
        or payload.get("providerCalendarId")
        or payload.get("calendar_id")
        or payload.get("calendarId"),
        "provider_calendar_id",
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    cursor_id = clean_string(
        payload.get("id") or f"{connection_id}:{provider_calendar_id or 'connection'}",
        "sync_cursor_id",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )
    return {
        "id": cursor_id,
        "connection_id": connection_id,
        "calendar_id": clean_string(payload.get("calendar_id") or payload.get("calendarId"), "calendar_id", max_length=MAX_PROVIDER_ID_LENGTH),
        "provider": GOOGLE_PROVIDER,
        "provider_calendar_id": provider_calendar_id,
        "status": _sync_status(payload.get("status")),
        "sync_mode": clean_string(payload.get("sync_mode") or payload.get("syncMode"), "sync_mode", max_length=MAX_LIST_ITEM_LENGTH),
        "sync_token": clean_string(payload.get("sync_token") or payload.get("syncToken"), "sync_token", max_length=MAX_EXTERNAL_LINK_LENGTH),
        "page_token": clean_string(payload.get("page_token") or payload.get("pageToken"), "page_token", max_length=MAX_EXTERNAL_LINK_LENGTH),
        "time_min": optional_time_string(payload.get("time_min") or payload.get("timeMin"), "time_min"),
        "time_max": optional_time_string(payload.get("time_max") or payload.get("timeMax"), "time_max"),
        "last_sync_at": optional_time_string(payload.get("last_sync_at") or payload.get("lastSyncAt"), "last_sync_at"),
        "last_full_sync_at": optional_time_string(payload.get("last_full_sync_at") or payload.get("lastFullSyncAt"), "last_full_sync_at"),
        "updated_at": optional_time_string(payload.get("updated_at") or payload.get("updatedAt"), "updated_at"),
        "error_code": clean_string(payload.get("error_code") or payload.get("errorCode"), "error_code", max_length=MAX_LIST_ITEM_LENGTH),
        "error": clean_string(payload.get("error"), "error", max_length=MAX_DESCRIPTION_LENGTH),
        "current_event_count": optional_int(
            payload.get("current_event_count") or payload.get("currentEventCount"),
            field="current_event_count",
            minimum=0,
            maximum=1_000_000,
        )
        or 0,
        "remote_candidate_count": optional_int(
            payload.get("remote_candidate_count") or payload.get("remoteCandidateCount"),
            field="remote_candidate_count",
            minimum=0,
            maximum=1_000_000,
        )
        or 0,
        "candidate_event_count": optional_int(
            payload.get("candidate_event_count") or payload.get("candidateEventCount"),
            field="candidate_event_count",
            minimum=0,
            maximum=1_000_000,
        )
        or 0,
        "max_events": optional_int(payload.get("max_events") or payload.get("maxEvents"), field="max_events", minimum=0, maximum=1_000_000) or 0,
    }


def _connection_id(payload: dict[str, Any]) -> str:
    return clean_string(
        payload.get("connection_id") or payload.get("connectionId") or payload.get("calendar_connection_id") or payload.get("calendarConnectionId"),
        "connection_id",
        required=True,
        max_length=MAX_LIST_ITEM_LENGTH,
    )


def _sync_status(value: Any) -> str:
    status = str(value or "idle").strip().lower()
    if status not in ALLOWED_SYNC_STATUSES:
        raise ValueError("Calendar sync status must be one of: disabled, error, idle, ok, syncing.")
    return status
