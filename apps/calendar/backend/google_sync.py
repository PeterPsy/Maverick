"""Google Calendar to Maverick Calendar synchronization."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any

from constants import (
    GOOGLE_PROVIDER,
    MAX_DESCRIPTION_LENGTH,
    MAX_EVENTS,
    MAX_LOCATION_LENGTH,
    MAX_ORGANIZER_LENGTH,
    MAX_PROVIDER_ID_LENGTH,
    MAX_TITLE_LENGTH,
    SCHEMA_VERSION,
)
from connection_records import normalize_connection
from event_records import event_revision, normalize_event
from google_oauth import CalendarOAuthError, HttpTransport
from google_provider import GoogleSyncTokenGone, list_calendar_list, list_events, refresh_access_token
from google_records import normalize_calendar, normalize_sync_cursor
from scalars import clean_string, optional_bool, optional_int
from store import read_state, update_state
from time_values import format_time, iso_time


DEFAULT_CALENDAR_LIMIT = 10
MAX_CALENDAR_LIMIT = 50
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_SIZE = 250
MAX_PAGE_SIZE = 250
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


def sync_google_calendar(
    data_root: Path,
    body: dict[str, Any],
    *,
    app_secrets: dict[str, str] | None = None,
    app_secret_errors: list[dict[str, Any]] | None = None,
    transport: HttpTransport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Synchronize Google Calendar calendars and events into local Calendar state."""
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    connection_id = _required_string(body, "connection_id")
    state = read_state(data_root)
    connection = _connected_google_connection(state, connection_id)
    access_token = refresh_access_token(app_secrets=app_secrets, app_secret_errors=app_secret_errors, transport=transport)
    calendars_payload = _fetch_calendar_list(access_token, body, transport=transport)
    target_calendars = _target_calendars(
        calendars_payload,
        connection_id=connection_id,
        requested_calendar_id=_optional_string(body, "calendar_id"),
        existing_calendars=state.get("calendars", []),
    )
    if not target_calendars:
        raise CalendarOAuthError("calendar_sync_no_calendars", "No Google calendars matched the Calendar sync request.")

    requested_full_sync = optional_bool(body.get("full_sync") if "full_sync" in body else body.get("fullSync"), default=False)
    requested_sync_token = _optional_string(body, "sync_token")
    page_limit = optional_int(body.get("page_limit") or body.get("pageLimit"), field="page_limit", minimum=1, maximum=MAX_PAGE_LIMIT) or DEFAULT_PAGE_LIMIT
    page_size = optional_int(body.get("page_size") or body.get("pageSize"), field="page_size", minimum=1, maximum=MAX_PAGE_SIZE) or DEFAULT_PAGE_SIZE

    calendar_results: list[dict[str, Any]] = []
    full_resyncs = 0
    total_created = 0
    total_updated = 0
    total_deleted = 0
    total_unchanged = 0
    next_events = [normalize_event(item) for item in state.get("events", [])]
    sync_cursors = [normalize_sync_cursor(item) for item in state.get("sync_state", [])]

    for calendar in target_calendars:
        cursor = _sync_cursor_for(sync_cursors, connection_id=connection_id, provider_calendar_id=calendar["provider_calendar_id"])
        sync_token = "" if requested_full_sync else requested_sync_token or str(cursor.get("sync_token") or "")
        full_sync = not bool(sync_token)
        try:
            event_items, next_sync_token, page_count, truncated = _fetch_events(
                access_token,
                calendar["provider_calendar_id"],
                sync_token=sync_token,
                page_limit=page_limit,
                page_size=page_size,
                transport=transport,
            )
        except GoogleSyncTokenGone:
            full_resyncs += 1
            full_sync = True
            event_items, next_sync_token, page_count, truncated = _fetch_events(
                access_token,
                calendar["provider_calendar_id"],
                sync_token="",
                page_limit=page_limit,
                page_size=page_size,
                transport=transport,
            )

        merge = _merge_remote_events(
            next_events,
            connection=connection,
            calendar=calendar,
            remote_events=event_items,
            full_sync=full_sync,
            now=current_time,
        )
        next_events = merge["events"]
        total_created += merge["created"]
        total_updated += merge["updated"]
        total_deleted += merge["deleted"]
        total_unchanged += merge["unchanged"]
        sync_cursors = _upsert_cursor(
            sync_cursors,
            {
                "id": _cursor_id(connection_id, calendar["provider_calendar_id"]),
                "connection_id": connection_id,
                "calendar_id": calendar["id"],
                "provider_calendar_id": calendar["provider_calendar_id"],
                "status": "error" if truncated else "ok",
                "sync_token": "" if truncated else next_sync_token,
                "last_sync_at": format_time(current_time),
                "last_full_sync_at": format_time(current_time) if full_sync else cursor.get("last_full_sync_at", ""),
                "updated_at": format_time(current_time),
                "error": "Google Calendar sync page limit reached before a sync token was returned." if truncated else "",
            },
        )
        calendar_results.append(
            {
                "calendar_id": calendar["id"],
                "provider_calendar_id": calendar["provider_calendar_id"],
                "full_sync": full_sync,
                "pages": page_count,
                "truncated": truncated,
                "created": merge["created"],
                "updated": merge["updated"],
                "deleted": merge["deleted"],
                "unchanged": merge["unchanged"],
                "sync_token_updated": bool(next_sync_token and not truncated),
            }
        )

    if len(next_events) > MAX_EVENTS:
        raise CalendarOAuthError("calendar_sync_event_limit", f"Calendar can store at most {MAX_EVENTS} events.", status_code=400)

    def updater(next_state: dict[str, Any]) -> dict[str, Any]:
        next_state["schema_version"] = SCHEMA_VERSION
        next_state["events"] = next_events
        next_state["connections"] = _mark_connection_synced(next_state.get("connections", []), connection_id, synced_at=format_time(current_time))
        next_state["calendars"] = _replace_connection_calendars(next_state.get("calendars", []), connection_id, calendars_payload)
        next_state["sync_state"] = sync_cursors
        return next_state

    update_state(data_root, updater)
    return {
        "action": "calendar_sync",
        "provider": GOOGLE_PROVIDER,
        "connection_id": connection_id,
        "synced": True,
        "calendar_count": len(target_calendars),
        "events_changed": total_created + total_updated + total_deleted,
        "created": total_created,
        "updated": total_updated,
        "deleted": total_deleted,
        "unchanged": total_unchanged,
        "full_resyncs": full_resyncs,
        "calendars": calendar_results,
    }


def _fetch_calendar_list(access_token: str, body: dict[str, Any], *, transport: HttpTransport | None) -> list[dict[str, Any]]:
    calendar_limit = optional_int(
        body.get("calendar_limit") or body.get("calendarLimit"),
        field="calendar_limit",
        minimum=1,
        maximum=MAX_CALENDAR_LIMIT,
    ) or DEFAULT_CALENDAR_LIMIT
    page_limit = optional_int(
        body.get("calendar_list_page_limit") or body.get("calendarListPageLimit"),
        field="calendar_list_page_limit",
        minimum=1,
        maximum=MAX_PAGE_LIMIT,
    ) or DEFAULT_PAGE_LIMIT
    page_size = optional_int(
        body.get("calendar_list_page_size") or body.get("calendarListPageSize"),
        field="calendar_list_page_size",
        minimum=1,
        maximum=MAX_PAGE_SIZE,
    ) or DEFAULT_PAGE_SIZE
    page_token = ""
    calendars: list[dict[str, Any]] = []
    for _page_index in range(page_limit):
        payload = list_calendar_list(access_token=access_token, page_token=page_token, max_results=page_size, transport=transport)
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
    page_limit: int,
    page_size: int,
    transport: HttpTransport | None,
) -> tuple[list[dict[str, Any]], str, int, bool]:
    page_token = ""
    items: list[dict[str, Any]] = []
    next_sync_token = ""
    for page_index in range(page_limit):
        payload = list_events(
            access_token=access_token,
            calendar_id=calendar_id,
            page_token=page_token,
            sync_token=sync_token,
            max_results=page_size,
            transport=transport,
        )
        items.extend(item for item in payload.get("items") or [] if isinstance(item, dict))
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            next_sync_token = str(payload.get("nextSyncToken") or "").strip()
            return items, next_sync_token, page_index + 1, False
    return items, "", page_limit, True


def _target_calendars(
    items: list[dict[str, Any]],
    *,
    connection_id: str,
    requested_calendar_id: str,
    existing_calendars: Any,
) -> list[dict[str, Any]]:
    calendars = _merge_calendar_preferences(
        [normalize_calendar({**item, "connection_id": connection_id}) for item in items],
        connection_id=connection_id,
        existing_calendars=existing_calendars,
    )
    if requested_calendar_id:
        return [
            item
            for item in calendars
            if item["id"] == requested_calendar_id or item["provider_calendar_id"] == requested_calendar_id
        ]
    return [item for item in calendars if item.get("selected", True) and item.get("sync_enabled", True)]


def _connected_google_connection(state: dict[str, Any], connection_id: str) -> dict[str, Any]:
    for item in state.get("connections", []):
        if not isinstance(item, dict):
            continue
        connection = normalize_connection(item)
        if connection["id"] != connection_id:
            continue
        if connection["provider"] != GOOGLE_PROVIDER:
            raise CalendarOAuthError("calendar_sync_unsupported_provider", "Calendar sync currently supports Google connections only.")
        if connection["status"] != "connected":
            raise CalendarOAuthError("calendar_sync_connection_unavailable", "Calendar connection is not connected.", status_code=400)
        return connection
    raise CalendarOAuthError("calendar_sync_connection_not_found", f"Calendar connection `{connection_id}` was not found.", status_code=404)


def _merge_remote_events(
    events: list[dict[str, Any]],
    *,
    connection: dict[str, Any],
    calendar: dict[str, Any],
    remote_events: list[dict[str, Any]],
    full_sync: bool,
    now: datetime,
) -> dict[str, Any]:
    next_events = list(events)
    existing_by_remote_id = _events_by_remote_id(next_events, connection_id=connection["id"], provider_calendar_id=calendar["provider_calendar_id"])
    active_remote_ids: set[str] = set()
    created = updated = deleted = unchanged = 0

    for remote_event in remote_events:
        provider_event_id = str(remote_event.get("id") or "").strip()
        if not provider_event_id:
            continue
        existing = existing_by_remote_id.get(provider_event_id)
        if str(remote_event.get("status") or "").strip().lower() == "cancelled" or remote_event.get("deleted") is True:
            if existing is not None:
                next_events = [item for item in next_events if item["id"] != existing["id"]]
                deleted += 1
            continue
        active_remote_ids.add(provider_event_id)
        payload = _google_event_payload(remote_event, connection=connection, calendar=calendar)
        if payload is None:
            continue
        if existing is None:
            event = normalize_event(
                payload,
                event_id=_local_event_id(connection["id"], calendar["provider_calendar_id"], provider_event_id),
                created_at=payload.get("created_at") or format_time(now),
                updated_at=payload.get("updated_at") or format_time(now),
                revision=1,
            )
            next_events.append(event)
            existing_by_remote_id[provider_event_id] = event
            created += 1
            continue
        event = normalize_event(
            {**existing, **payload, "id": existing["id"]},
            created_at=existing.get("created_at"),
            updated_at=payload.get("updated_at") or format_time(now),
            revision=event_revision(existing.get("revision")) + 1,
        )
        if _event_comparison(existing) == _event_comparison(event):
            unchanged += 1
            continue
        next_events = [event if item["id"] == existing["id"] else item for item in next_events]
        existing_by_remote_id[provider_event_id] = event
        updated += 1

    if full_sync:
        stale_ids = {
            item["id"]
            for item in next_events
            if _matches_remote_calendar(item, connection_id=connection["id"], provider_calendar_id=calendar["provider_calendar_id"])
            and str((item.get("external_refs") or {}).get("provider_event_id") or "") not in active_remote_ids
        }
        if stale_ids:
            next_events = [item for item in next_events if item["id"] not in stale_ids]
            deleted += len(stale_ids)

    return {
        "events": next_events,
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged,
    }


def _google_event_payload(
    remote_event: dict[str, Any],
    *,
    connection: dict[str, Any],
    calendar: dict[str, Any],
) -> dict[str, Any] | None:
    start_value, all_day, timezone_name = _google_event_time(remote_event.get("start"), calendar["timezone"])
    end_value, _end_all_day, end_timezone = _google_event_time(remote_event.get("end"), timezone_name)
    if not start_value or not end_value:
        return None
    timezone_name = timezone_name or end_timezone or calendar["timezone"] or "UTC"
    organizer = _person_label(remote_event.get("organizer"), max_length=MAX_ORGANIZER_LENGTH)
    attendees = [_person_label(item) for item in remote_event.get("attendees") or [] if isinstance(item, dict)]
    reminders = _reminders(remote_event.get("reminders"))
    recurrence = remote_event.get("recurrence")
    return {
        "title": _bounded_text(remote_event.get("summary"), max_length=MAX_TITLE_LENGTH, fallback="(Untitled Google event)"),
        "description": _bounded_text(remote_event.get("description"), max_length=MAX_DESCRIPTION_LENGTH),
        "startTime": start_value,
        "endTime": end_value,
        "timezone": timezone_name,
        "location": _bounded_text(remote_event.get("location"), max_length=MAX_LOCATION_LENGTH),
        "organizer": organizer,
        "all_day": all_day,
        "status": _event_status(remote_event.get("status")),
        "color": GOOGLE_COLOR_MAP.get(str(remote_event.get("colorId") or "").strip(), "blue"),
        "category": "Google Calendar",
        "attendees": [item for item in attendees if item],
        "tags": ["google"],
        "source": "google_calendar",
        "external_refs": _external_refs(remote_event, connection=connection, calendar=calendar),
        "recurrence": {"rules": recurrence} if isinstance(recurrence, list) else {},
        "reminders": reminders,
        "idempotency_key": _google_idempotency_key(connection["id"], calendar["provider_calendar_id"], str(remote_event.get("id") or "")),
        "created_at": _optional_google_time(remote_event.get("created")),
        "updated_at": _optional_google_time(remote_event.get("updated")),
    }


def google_event_payload(
    remote_event: dict[str, Any],
    *,
    connection: dict[str, Any],
    calendar: dict[str, Any],
) -> dict[str, Any] | None:
    """Map one Google event resource into the local Calendar event payload shape."""
    return _google_event_payload(remote_event, connection=connection, calendar=calendar)


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
    return _bounded_text(value.get("email") or value.get("displayName"), max_length=max_length)


def _bounded_text(value: Any, *, max_length: int, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return text[:max_length]


def _external_refs(remote_event: dict[str, Any], *, connection: dict[str, Any], calendar: dict[str, Any]) -> dict[str, Any]:
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
    }
    return {key: value for key, value in refs.items() if value not in (None, "")}


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


def _events_by_remote_id(events: list[dict[str, Any]], *, connection_id: str, provider_calendar_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if not _matches_remote_calendar(event, connection_id=connection_id, provider_calendar_id=provider_calendar_id):
            continue
        refs = event.get("external_refs") if isinstance(event.get("external_refs"), dict) else {}
        provider_event_id = str(refs.get("provider_event_id") or "").strip()
        if provider_event_id:
            result[provider_event_id] = event
    return result


def _matches_remote_calendar(event: dict[str, Any], *, connection_id: str, provider_calendar_id: str) -> bool:
    refs = event.get("external_refs") if isinstance(event.get("external_refs"), dict) else {}
    return (
        str(refs.get("calendar_connection_id") or "").strip() == connection_id
        and str(refs.get("provider_calendar_id") or "").strip() == provider_calendar_id
        and str(refs.get("provider_event_id") or "").strip()
    )


def _event_comparison(event: dict[str, Any]) -> dict[str, Any]:
    ignored = {"updated_at", "revision"}
    return {key: value for key, value in event.items() if key not in ignored}


def _replace_connection_calendars(existing: Any, connection_id: str, calendars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    if isinstance(existing, list):
        retained = [
            item
            for item in existing
            if isinstance(item, dict) and str(item.get("connection_id") or item.get("connectionId") or "").strip() != connection_id
        ]
    normalized = _merge_calendar_preferences(
        [normalize_calendar({**item, "connection_id": connection_id}) for item in calendars],
        connection_id=connection_id,
        existing_calendars=existing,
    )
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
        preference = preferences.get(calendar["provider_calendar_id"]) or preferences.get(calendar["id"]) or {}
        merged.append(normalize_calendar({**calendar, **preference}))
    return merged


def _calendar_preferences(existing: Any, *, connection_id: str) -> dict[str, dict[str, bool]]:
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
        preference = {"selected": bool(calendar.get("selected")), "sync_enabled": bool(calendar.get("sync_enabled"))}
        preferences[calendar["provider_calendar_id"]] = preference
        preferences[calendar["id"]] = preference
    return preferences


def _mark_connection_synced(connections: Any, connection_id: str, *, synced_at: str) -> list[dict[str, Any]]:
    if not isinstance(connections, list):
        return []
    result: list[dict[str, Any]] = []
    for item in connections:
        if not isinstance(item, dict):
            continue
        connection = normalize_connection(item)
        if connection["id"] == connection_id:
            connection["last_sync_at"] = synced_at
            connection["updated_at"] = synced_at
        result.append(connection)
    return result


def _sync_cursor_for(cursors: list[dict[str, Any]], *, connection_id: str, provider_calendar_id: str) -> dict[str, Any]:
    cursor_id = _cursor_id(connection_id, provider_calendar_id)
    for cursor in cursors:
        if cursor["id"] == cursor_id:
            return cursor
        if cursor["connection_id"] == connection_id and cursor.get("provider_calendar_id") == provider_calendar_id:
            return cursor
    return normalize_sync_cursor(
        {
            "id": cursor_id,
            "connection_id": connection_id,
            "provider_calendar_id": provider_calendar_id,
            "status": "idle",
        }
    )


def _upsert_cursor(cursors: list[dict[str, Any]], cursor: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = normalize_sync_cursor(cursor)
    return [item for item in cursors if item["id"] != normalized["id"]] + [normalized]


def _cursor_id(connection_id: str, provider_calendar_id: str) -> str:
    return clean_string(f"{connection_id}:{provider_calendar_id}", "sync_cursor_id", required=True, max_length=MAX_PROVIDER_ID_LENGTH)


def _local_event_id(connection_id: str, provider_calendar_id: str, provider_event_id: str) -> str:
    digest = hashlib.sha256(f"{connection_id}\n{provider_calendar_id}\n{provider_event_id}".encode("utf-8")).hexdigest()
    return f"evt_gcal_{digest[:24]}"


def _google_idempotency_key(connection_id: str, provider_calendar_id: str, provider_event_id: str) -> str:
    digest = hashlib.sha256(f"{connection_id}\n{provider_calendar_id}\n{provider_event_id}".encode("utf-8")).hexdigest()
    return f"google:{digest[:48]}"


def _required_string(body: dict[str, Any], field: str) -> str:
    value = str(body.get(field) or body.get(_camel(field)) or "").strip()
    if not value:
        raise ValueError(f"`{field}` is required.")
    return value


def _optional_string(body: dict[str, Any], field: str) -> str:
    return str(body.get(field) or body.get(_camel(field)) or "").strip()


def _camel(field: str) -> str:
    parts = field.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _optional_google_time(value: Any) -> str:
    if not value:
        return ""
    try:
        return format_time(iso_time(value, "google_time"))
    except ValueError:
        return ""
