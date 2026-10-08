"""Google Calendar source listing and local sync selection."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from constants import GOOGLE_PROVIDER, MAX_PROVIDER_ID_LENGTH
from google_oauth import CalendarOAuthError
from google_records import normalize_calendar
from scalars import clean_string, optional_bool
from store import read_state, update_state
from time_values import format_time


def list_calendars(data_root: Path, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return redaction-safe Google calendar sources known to Calendar."""
    connection_id = _optional_string(body or {}, "connection_id")
    state = read_state(data_root)
    cursors = {(c["connection_id"], c["provider_calendar_id"]): c for c in state["sync_state"]}
    calendars = [_public_calendar(item) for item in state["calendars"]]
    for calendar in calendars:
        cursor = cursors.get((calendar["connection_id"], calendar["provider_calendar_id"]), {})
        calendar["sync_status"] = {key: cursor.get(key, "") for key in
            ("status", "last_sync_at", "time_min", "time_max", "error", "error_code")}
        calendar["sync_status"]["has_more"] = bool(cursor.get("page_token"))
    if connection_id:
        calendars = [item for item in calendars if item.get("connection_id") == connection_id]
    calendars.sort(key=lambda item: (str(item.get("connection_id") or ""), 0 if item.get("primary") else 1, str(item.get("summary") or "")))
    return {"action": "calendar_calendars.list", "calendars": calendars}


def select_calendar(
    data_root: Path,
    body: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Enable or disable local sync selection for one known remote calendar."""
    connection_id = _required_string(body, "connection_id")
    calendar_id = _required_string(body, "calendar_id")
    flags = {key: optional_bool(body[key], default=True) for key in
             ("selected", "sync_enabled", "availability_enabled") if key in body}
    if "syncEnabled" in body:
        flags["sync_enabled"] = optional_bool(body["syncEnabled"], default=True)
    if not flags:
        raise ValueError("A visibility, sync or availability setting is required.")
    updated_at = format_time((now or datetime.now(UTC)).astimezone(UTC))
    updated_calendar: dict[str, Any] | None = None

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal updated_calendar
        calendars: list[dict[str, Any]] = []
        for item in state.get("calendars", []):
            if not isinstance(item, dict):
                continue
            calendar = normalize_calendar(item)
            if _matches_calendar(calendar, connection_id=connection_id, calendar_id=calendar_id):
                calendar = normalize_calendar(
                    {
                        **calendar,
                        **flags,
                        "updated_at": updated_at,
                    }
                )
                updated_calendar = calendar
            calendars.append(calendar)
        if updated_calendar is None:
            raise CalendarOAuthError(
                "calendar_not_found",
                f"Calendar `{calendar_id}` was not found for connection `{connection_id}`.",
                status_code=404,
            )
        state["calendars"] = calendars
        return state

    update_state(data_root, updater)
    return {
        "action": "calendar_calendars.select",
        "connection_id": connection_id,
        "calendar": _public_calendar(updated_calendar or {}),
    }


def _public_calendar(calendar: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_calendar(calendar)
    return {
        "id": normalized["id"],
        "connection_id": normalized["connection_id"],
        "provider": normalized["provider"] or GOOGLE_PROVIDER,
        "provider_calendar_id": normalized["provider_calendar_id"],
        "summary": normalized.get("summary", ""),
        "description": normalized.get("description", ""),
        "timezone": normalized.get("timezone", "UTC"),
        "access_role": normalized.get("access_role", ""),
        "primary": bool(normalized.get("primary")),
        "selected": bool(normalized.get("selected")),
        "sync_enabled": bool(normalized.get("sync_enabled")),
        "availability_enabled": normalized["availability_enabled"],
        "color": normalized.get("color", ""),
        "updated_at": normalized.get("updated_at", ""),
    }


def _matches_calendar(calendar: dict[str, Any], *, connection_id: str, calendar_id: str) -> bool:
    return (
        calendar.get("connection_id") == connection_id
        and (calendar.get("id") == calendar_id or calendar.get("provider_calendar_id") == calendar_id)
    )


def _required_string(body: dict[str, Any], field: str) -> str:
    value = _optional_string(body, field)
    if not value:
        raise ValueError(f"`{field}` is required.")
    return value


def _optional_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field) or body.get(_camel(field))
    return clean_string(value, field, max_length=MAX_PROVIDER_ID_LENGTH)


def _camel(field: str) -> str:
    parts = field.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])
