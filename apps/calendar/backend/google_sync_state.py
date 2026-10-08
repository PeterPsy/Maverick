"""Google synchronization identity, cursor records and account diagnostics."""

from typing import Any
from constants import GOOGLE_PROVIDER, MAX_PROVIDER_ID_LENGTH
from connection_records import normalize_connection
from google_oauth import CalendarOAuthError
from google_records import normalize_sync_cursor
from scalars import clean_string


def _mark_capacity_error(
    sync_cursors: list[dict[str, Any]],
    target_calendars: list[dict[str, Any]],
    *,
    connection_id: str,
    updated_at: str,
    current_event_count: int,
    remote_candidate_count: int,
    candidate_event_count: int,
    max_events: int,
) -> list[dict[str, Any]]:
    result = sync_cursors
    for calendar in target_calendars:
        cursor = _sync_cursor_for(
            result,
            connection_id=connection_id,
            provider_calendar_id=calendar["provider_calendar_id"],
        )
        result = _upsert_cursor(
            result,
            {
                **cursor,
                "calendar_id": calendar["id"],
                "provider_calendar_id": calendar["provider_calendar_id"],
                "status": "error",
                "sync_token": "",
                "updated_at": updated_at,
                "error_code": "calendar_sync_event_limit",
                "error": f"Calendar sync would store {candidate_event_count} events, but Calendar can store at most {max_events} events.",
                "current_event_count": current_event_count,
                "remote_candidate_count": remote_candidate_count,
                "candidate_event_count": candidate_event_count,
                "max_events": max_events,
            },
        )
    return result


def _connected_google_connection(
    state: dict[str, Any], connection_id: str
) -> dict[str, Any]:
    for item in state.get("connections", []):
        if not isinstance(item, dict):
            continue
        connection = normalize_connection(item)
        if connection["id"] != connection_id:
            continue
        if connection["provider"] != GOOGLE_PROVIDER:
            raise CalendarOAuthError(
                "calendar_sync_unsupported_provider",
                "Calendar sync currently supports Google connections only.",
            )
        if connection["status"] != "connected":
            raise CalendarOAuthError(
                "calendar_sync_connection_unavailable",
                "Calendar connection is not connected.",
                status_code=400,
            )
        return connection
    raise CalendarOAuthError(
        "calendar_sync_connection_not_found",
        f"Calendar connection `{connection_id}` was not found.",
        status_code=404,
    )


def _mark_connection_synced(
    connections: Any, connection_id: str, *, synced_at: str
) -> list[dict[str, Any]]:
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


def _sync_cursor_for(
    cursors: list[dict[str, Any]], *, connection_id: str, provider_calendar_id: str
) -> dict[str, Any]:
    cursor_id = _cursor_id(connection_id, provider_calendar_id)
    for cursor in cursors:
        if cursor["id"] == cursor_id:
            return cursor
        if (
            cursor["connection_id"] == connection_id
            and cursor.get("provider_calendar_id") == provider_calendar_id
        ):
            return cursor
    return normalize_sync_cursor(
        {
            "id": cursor_id,
            "connection_id": connection_id,
            "provider_calendar_id": provider_calendar_id,
            "status": "idle",
        }
    )


def _upsert_cursor(
    cursors: list[dict[str, Any]], cursor: dict[str, Any]
) -> list[dict[str, Any]]:
    normalized = normalize_sync_cursor(cursor)
    return [item for item in cursors if item["id"] != normalized["id"]] + [normalized]


def _cursor_id(connection_id: str, provider_calendar_id: str) -> str:
    return clean_string(
        f"{connection_id}:{provider_calendar_id}",
        "sync_cursor_id",
        required=True,
        max_length=MAX_PROVIDER_ID_LENGTH,
    )


def _remote_calendar_event(event, connection_id, calendar_id):
    refs = event.get("external_refs") or {}
    return (
        refs.get("calendar_connection_id") == connection_id
        and refs.get("provider_calendar_id") == calendar_id
        and bool(refs.get("provider_event_id"))
    )
