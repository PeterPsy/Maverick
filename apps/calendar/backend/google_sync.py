"""Google Calendar to Maverick Calendar synchronization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from constants import (
    GOOGLE_PROVIDER,
)
from google_oauth import CalendarOAuthError, HttpTransport
from google_provider import GoogleSyncTokenGone, refresh_access_token
from google_records import normalize_sync_cursor
from google_sync_state import _connected_google_connection, _sync_cursor_for
from google_sync_persistence import persist_sync
from google_sync_fetch import (
    _fetch_calendar_list,
    _fetch_events,
    _target_calendars,
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
)
from scalars import optional_int
from store import read_state, update_state
from time_values import format_time, iso_time

SYNC_MODE_BOUNDED = "bounded"
SYNC_MODE_FULL_HISTORY = "full_history"
DEFAULT_BOUNDED_SYNC_PAST_DAYS = 365
DEFAULT_BOUNDED_SYNC_FUTURE_DAYS = 730


def sync_google_calendar(
    data_root: Path,
    body: dict[str, Any],
    *,
    app_secrets=None,
    app_secret_errors=None,
    transport: HttpTransport | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch outside the lock, then reconcile against current records under the lock."""
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    connection_id = _required_string(body, "connection_id")
    state = read_state(data_root)
    connection = _connected_google_connection(state, connection_id)
    try:
        return _sync_connection(
            data_root,
            body,
            state,
            connection,
            current_time,
            app_secrets,
            app_secret_errors,
            transport,
        )
    except CalendarOAuthError as error:

        def failed(latest):
            # Do not erase completed cursors or concurrent account changes.
            for cursor in latest.get("sync_state", []):
                if cursor[
                    "connection_id"
                ] == connection_id and cursor == _sync_cursor_for(
                    state["sync_state"],
                    connection_id=connection_id,
                    provider_calendar_id=cursor["provider_calendar_id"],
                ):
                    cursor.update(
                        status="error",
                        error_code=error.code,
                        error=error.detail,
                        updated_at=format_time(current_time),
                    )
            if not any(
                c["connection_id"] == connection_id
                for c in latest.get("sync_state", [])
            ):
                latest["sync_state"].append(
                    normalize_sync_cursor(
                        {
                            "connection_id": connection_id,
                            "status": "error",
                            "error_code": error.code,
                            "error": error.detail,
                            "updated_at": format_time(current_time),
                        }
                    )
                )
            return latest

        update_state(data_root, failed)
        raise


def _sync_connection(
    data_root,
    body,
    state,
    connection,
    current_time,
    app_secrets,
    app_secret_errors,
    transport,
):

    connection_id = connection["id"]
    access_token = refresh_access_token(
        app_secrets=app_secrets,
        app_secret_errors=app_secret_errors,
        transport=transport,
    )
    calendars_payload = _fetch_calendar_list(access_token, body, transport=transport)
    targets = _target_calendars(
        calendars_payload,
        connection_id=connection_id,
        requested_calendar_id=_optional_string(body, "calendar_id"),
        existing_calendars=state.get("calendars", []),
    )
    if not targets:
        raise CalendarOAuthError(
            "calendar_sync_no_calendars",
            "No enabled Google calendars matched the sync request.",
        )
    page_limit = (
        optional_int(
            body.get("page_limit") or body.get("pageLimit"),
            field="page_limit",
            minimum=1,
            maximum=MAX_PAGE_LIMIT,
        )
        or DEFAULT_PAGE_LIMIT
    )
    page_size = (
        optional_int(
            body.get("page_size") or body.get("pageSize"),
            field="page_size",
            minimum=1,
            maximum=MAX_PAGE_SIZE,
        )
        or DEFAULT_PAGE_SIZE
    )
    batches = []
    full_resyncs = 0
    for calendar in targets:
        cursor = _sync_cursor_for(
            state["sync_state"],
            connection_id=connection_id,
            provider_calendar_id=calendar["provider_calendar_id"],
        )
        mode = _sync_mode(body, cursor)
        resume = (
            bool(cursor.get("page_token"))
            and not body.get("full_sync")
            and not body.get("fullSync")
            and not _optional_string(body, "time_min")
            and not _optional_string(body, "time_max")
            and mode == cursor.get("sync_mode")
        )
        time_min, time_max = (
            (
                (cursor["time_min"], cursor["time_max"])
                if resume
                else _bounded_sync_window(body, now=current_time)
            )
            if mode == SYNC_MODE_BOUNDED
            else ("", "")
        )
        sync_token = (
            ""
            if mode == SYNC_MODE_BOUNDED
            or body.get("full_sync")
            or body.get("fullSync")
            else _optional_string(body, "sync_token") or cursor["sync_token"]
        )
        requested_page_size = cursor["page_size"] if resume else page_size
        try:
            items, token, pages, page_token = _fetch_events(
                access_token,
                calendar["provider_calendar_id"],
                sync_token=sync_token,
                time_min=time_min,
                time_max=time_max,
                page_limit=page_limit,
                page_size=requested_page_size,
                page_token=cursor["page_token"] if resume else "",
                transport=transport,
            )
        except GoogleSyncTokenGone:
            full_resyncs += 1
            sync_token = ""
            resume = False
            items, token, pages, page_token = _fetch_events(
                access_token,
                calendar["provider_calendar_id"],
                sync_token="",
                time_min=time_min,
                time_max=time_max,
                page_limit=page_limit,
                page_size=page_size,
                transport=transport,
            )
        batches.append(
            (
                calendar,
                cursor,
                mode,
                time_min,
                time_max,
                sync_token,
                items,
                token,
                pages,
                page_token,
                resume,
            )
        )
    results = persist_sync(
        data_root,
        state,
        connection,
        current_time,
        batches,
        targets,
        calendars_payload,
        page_size,
    )
    complete = all(r["status"] == "ok" for r in results)
    totals = {
        key: sum(r.get(key, 0) for r in results)
        for key in ("created", "updated", "deleted", "unchanged")
    }
    return {
        "action": "calendar_sync",
        "provider": GOOGLE_PROVIDER,
        "connection_id": connection_id,
        "synced": complete,
        "status": "complete" if complete else "partial",
        "calendar_count": len(targets),
        "events_changed": sum(totals[k] for k in ("created", "updated", "deleted")),
        **totals,
        "full_resyncs": full_resyncs,
        "calendars": results,
    }


def _sync_mode(body: dict[str, Any], cursor: dict[str, Any]) -> str:
    requested = str(body.get("sync_mode") or body.get("syncMode") or "").strip().lower()
    if requested in {SYNC_MODE_BOUNDED, SYNC_MODE_FULL_HISTORY}:
        return requested
    if requested:
        raise ValueError("`sync_mode` must be `bounded` or `full_history`.")
    if _optional_string(body, "sync_token"):
        return SYNC_MODE_FULL_HISTORY
    cursor_mode = str(cursor.get("sync_mode") or "").strip().lower()
    if cursor_mode in {SYNC_MODE_BOUNDED, SYNC_MODE_FULL_HISTORY}:
        return cursor_mode
    if cursor.get("sync_token"):
        return SYNC_MODE_FULL_HISTORY
    return SYNC_MODE_BOUNDED


def _bounded_sync_window(body: dict[str, Any], *, now: datetime) -> tuple[str, str]:
    time_min = _optional_time(body, "time_min")
    time_max = _optional_time(body, "time_max")
    if not time_min:
        time_min = format_time(now - timedelta(days=DEFAULT_BOUNDED_SYNC_PAST_DAYS))
    if not time_max:
        time_max = format_time(now + timedelta(days=DEFAULT_BOUNDED_SYNC_FUTURE_DAYS))
    if iso_time(time_max, "time_max") <= iso_time(time_min, "time_min"):
        raise ValueError("`time_max` must be after `time_min`.")
    return time_min, time_max


def _optional_time(body: dict[str, Any], field: str) -> str:
    value = body.get(field) or body.get(_camel(field))
    if not value:
        return ""
    return format_time(iso_time(value, field))


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
