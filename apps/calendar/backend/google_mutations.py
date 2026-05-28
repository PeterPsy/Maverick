"""Remote Google Calendar mutations coordinated with local Calendar state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from availability import raise_if_rejected_conflicts
from calendar_visibility import filter_visible_events
from connection_records import normalize_connection
from constants import GOOGLE_PROVIDER, MAX_EVENTS
from event_records import normalize_event, normalize_external_refs
from google_oauth import CalendarOAuthError, HttpTransport
from google_provider import delete_event as delete_google_event
from google_provider import insert_event, patch_event, refresh_access_token
from google_records import normalize_calendar
from google_sync import google_event_payload
from operations import (
    create_event,
    delete_event,
    get_event,
    move_event_payload,
    preview_delete_event,
    preview_update_event,
    update_event,
)
from request_inputs import idempotency_key_from_payload
from store import read_state
from time_values import iso_time, now_string


REMOTE_MUTATION_FLAG = "remote_mutation"
DEFAULT_GOOGLE_CALENDAR_ID = "primary"
WRITABLE_GOOGLE_ACCESS_ROLES = {"owner", "writer"}


def is_google_create_request(event_payload: dict[str, Any]) -> bool:
    refs = normalize_external_refs(event_payload.get("external_refs") or event_payload.get("externalRefs"))
    source = str(event_payload.get("source") or "").strip().lower()
    provider = str(refs.get("provider") or "").strip().lower()
    return bool(
        _ref_value(refs, "calendar_connection_id")
        and (source == "google_calendar" or provider == GOOGLE_PROVIDER)
    )


def is_google_event(event: dict[str, Any]) -> bool:
    return _remote_ref(event) is not None


def secret_lookup_for_remote_mutation(data_root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "create":
        payload = arguments.get("event") or arguments.get("payload") or arguments
        if not isinstance(payload, dict) or not is_google_create_request(payload):
            return {"requires_secrets": False}
        ref = _create_ref(payload)
        return _secret_lookup_result(ref["calendar_connection_id"])
    if action in {"update", "delete", "move"}:
        event_id = str(arguments.get("id") or "").strip()
        if not event_id:
            return {"requires_secrets": False}
        event = get_event(data_root, event_id)
        ref = _remote_ref(event or {})
        if ref is None and action == "update":
            payload = arguments.get("event") or arguments.get("payload") or {}
            if isinstance(payload, dict) and is_google_create_request(payload):
                ref = _create_ref(payload)
        if ref is None:
            return {"requires_secrets": False}
        return _secret_lookup_result(ref["calendar_connection_id"])
    return {"requires_secrets": False}


def create_google_event(
    data_root: Path,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    transport: HttpTransport | None,
) -> tuple[dict[str, Any], bool]:
    """Insert a Google event first, then persist the mirrored local event."""
    preview, idempotent_replay = _preview_create_event(data_root, event_payload, conflict_policy=conflict_policy)
    if idempotent_replay:
        return preview, True

    ref = _create_ref(event_payload)
    connection, calendar = _connection_and_calendar(data_root, ref, fallback_event=preview)
    _ensure_writable_calendar(calendar, operation="create")
    access_token = refresh_access_token(app_secrets=app_secrets, app_secret_errors=app_secret_errors, transport=transport)
    remote = insert_event(
        access_token=access_token,
        calendar_id=ref["provider_calendar_id"],
        event=_google_event_body(preview),
        transport=transport,
    )
    local_payload = _local_payload_from_remote(remote, fallback=preview, connection=connection, calendar=calendar, for_update=False)
    return create_event(data_root, local_payload, conflict_policy=conflict_policy)


def attach_google_event(
    data_root: Path,
    event_id: str,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str,
    expected_revision: int | None,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    transport: HttpTransport | None,
) -> dict[str, Any]:
    """Insert a remote Google event for an existing local event, then attach remote refs locally."""
    preview = preview_update_event(
        data_root,
        event_id,
        event_payload,
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
    )
    ref = _create_ref(preview)
    connection, calendar = _connection_and_calendar(data_root, ref, fallback_event=preview)
    _ensure_writable_calendar(calendar, operation="create")
    access_token = refresh_access_token(app_secrets=app_secrets, app_secret_errors=app_secret_errors, transport=transport)
    remote = insert_event(
        access_token=access_token,
        calendar_id=ref["provider_calendar_id"],
        event=_google_event_body(preview),
        transport=transport,
    )
    local_payload = _local_payload_from_remote(remote, fallback=preview, connection=connection, calendar=calendar, for_update=True)
    return update_event(
        data_root,
        event_id,
        local_payload,
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
    )


def update_google_event(
    data_root: Path,
    event_id: str,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str,
    expected_revision: int | None,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    transport: HttpTransport | None,
) -> dict[str, Any]:
    current = get_event(data_root, event_id)
    ref = _remote_ref(current or {})
    preview = preview_update_event(
        data_root,
        event_id,
        event_payload,
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
    )
    if ref is None:
        return update_event(
            data_root,
            event_id,
            event_payload,
            conflict_policy=conflict_policy,
            expected_revision=expected_revision,
        )
    connection, calendar = _connection_and_calendar(data_root, ref, fallback_event=preview)
    _ensure_writable_calendar(calendar, operation="update")
    access_token = refresh_access_token(app_secrets=app_secrets, app_secret_errors=app_secret_errors, transport=transport)
    remote = patch_event(
        access_token=access_token,
        calendar_id=ref["provider_calendar_id"],
        event_id=ref["provider_event_id"],
        event=_google_event_body(preview),
        etag=ref.get("etag", ""),
        transport=transport,
    )
    local_payload = _local_payload_from_remote(remote, fallback=preview, connection=connection, calendar=calendar, for_update=True)
    return update_event(
        data_root,
        event_id,
        local_payload,
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
    )


def delete_google_event_local_first_validated(
    data_root: Path,
    event_id: str,
    *,
    expected_revision: int | None,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    transport: HttpTransport | None,
) -> bool:
    event = preview_delete_event(data_root, event_id, expected_revision=expected_revision)
    ref = _remote_ref(event)
    if ref is None:
        delete_event(data_root, event_id, expected_revision=expected_revision)
        return False

    _connection, calendar = _connection_and_calendar(data_root, ref, fallback_event=event)
    _ensure_writable_calendar(calendar, operation="delete")
    access_token = refresh_access_token(app_secrets=app_secrets, app_secret_errors=app_secret_errors, transport=transport)
    delete_google_event(
        access_token=access_token,
        calendar_id=ref["provider_calendar_id"],
        event_id=ref["provider_event_id"],
        etag=ref.get("etag", ""),
        transport=transport,
    )
    delete_event(data_root, event_id, expected_revision=expected_revision)
    return True


def move_google_event(
    data_root: Path,
    event_id: str,
    body: dict[str, Any],
    *,
    conflict_policy: str,
    expected_revision: int | None,
    app_secrets: dict[str, str] | None,
    app_secret_errors: list[dict[str, Any]] | None,
    transport: HttpTransport | None,
) -> dict[str, Any]:
    payload = move_event_payload(data_root, event_id, body)
    return update_google_event(
        data_root,
        event_id,
        payload,
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
        app_secrets=app_secrets,
        app_secret_errors=app_secret_errors,
        transport=transport,
    )


def _preview_create_event(
    data_root: Path,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str,
) -> tuple[dict[str, Any], bool]:
    state = read_state(data_root)
    events = [normalize_event(item) for item in state.get("events", [])]
    idempotency_key = idempotency_key_from_payload(event_payload)
    if idempotency_key:
        for event in events:
            if str(event.get("idempotency_key") or "") == idempotency_key:
                return event, True
    if len(events) >= MAX_EVENTS:
        raise ValueError(f"Calendar can store at most {MAX_EVENTS} events.")
    current_time = now_string()
    candidate = normalize_event(
        event_payload,
        event_id="evt_google_preview",
        created_at=current_time,
        updated_at=current_time,
        revision=1,
    )
    conflict_events = filter_visible_events(events, state.get("calendars", []))
    raise_if_rejected_conflicts("create", conflict_policy, candidate, conflict_events)
    return candidate, False


def _create_ref(event_payload: dict[str, Any]) -> dict[str, str]:
    refs = normalize_external_refs(event_payload.get("external_refs") or event_payload.get("externalRefs"))
    connection_id = _ref_value(refs, "calendar_connection_id")
    if not connection_id:
        raise ValueError("Google Calendar create requires external_refs.calendar_connection_id.")
    return {
        "calendar_connection_id": connection_id,
        "provider_calendar_id": _ref_value(refs, "provider_calendar_id") or DEFAULT_GOOGLE_CALENDAR_ID,
        "provider_event_id": _ref_value(refs, "provider_event_id"),
        "etag": _ref_value(refs, "etag"),
    }


def _remote_ref(event: dict[str, Any]) -> dict[str, str] | None:
    refs = normalize_external_refs(event.get("external_refs") or event.get("externalRefs"))
    connection_id = _ref_value(refs, "calendar_connection_id")
    provider_calendar_id = _ref_value(refs, "provider_calendar_id")
    provider_event_id = _ref_value(refs, "provider_event_id")
    if not connection_id or not provider_calendar_id or not provider_event_id:
        return None
    source = str(event.get("source") or "").strip().lower()
    provider = str(refs.get("provider") or "").strip().lower()
    if source != "google_calendar" and provider != GOOGLE_PROVIDER:
        return None
    return {
        "calendar_connection_id": connection_id,
        "provider_calendar_id": provider_calendar_id,
        "provider_event_id": provider_event_id,
        "etag": _ref_value(refs, "etag"),
    }


def _connection_and_calendar(
    data_root: Path,
    ref: dict[str, str],
    *,
    fallback_event: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = read_state(data_root)
    connection = _connected_google_connection(state, ref["calendar_connection_id"])
    calendar = _calendar_for_ref(state, ref, fallback_event=fallback_event)
    return connection, calendar


def _ensure_writable_calendar(calendar: dict[str, Any], *, operation: str) -> None:
    access_role = str(calendar.get("access_role") or "").strip().lower()
    if not access_role or access_role in WRITABLE_GOOGLE_ACCESS_ROLES:
        return
    calendar_name = str(calendar.get("summary") or calendar.get("provider_calendar_id") or "Google Calendar").strip()
    raise CalendarOAuthError(
        "google_calendar_read_only",
        f"Google Calendar `{calendar_name}` is read-only for this account and cannot be used for {operation}.",
        status_code=403,
    )


def _connected_google_connection(state: dict[str, Any], connection_id: str) -> dict[str, Any]:
    for item in state.get("connections", []):
        if not isinstance(item, dict):
            continue
        connection = normalize_connection(item)
        if connection["id"] != connection_id:
            continue
        if connection["provider"] != GOOGLE_PROVIDER:
            raise CalendarOAuthError("calendar_mutation_unsupported_provider", "Calendar remote mutations support Google connections only.")
        if connection["status"] != "connected":
            raise CalendarOAuthError("calendar_mutation_connection_unavailable", "Calendar connection is not connected.", status_code=400)
        return connection
    raise CalendarOAuthError("calendar_mutation_connection_not_found", f"Calendar connection `{connection_id}` was not found.", status_code=404)


def _calendar_for_ref(
    state: dict[str, Any],
    ref: dict[str, str],
    *,
    fallback_event: dict[str, Any],
) -> dict[str, Any]:
    for item in state.get("calendars", []):
        if not isinstance(item, dict):
            continue
        calendar = normalize_calendar(item)
        if calendar["connection_id"] == ref["calendar_connection_id"] and calendar["provider_calendar_id"] == ref["provider_calendar_id"]:
            return calendar
    refs = normalize_external_refs(fallback_event.get("external_refs") or {})
    return normalize_calendar(
        {
            "connection_id": ref["calendar_connection_id"],
            "provider_calendar_id": ref["provider_calendar_id"],
            "summary": refs.get("provider_calendar_summary") or ref["provider_calendar_id"],
            "timeZone": fallback_event.get("timezone") or "UTC",
            "selected": True,
            "sync_enabled": True,
        }
    )


def _google_event_body(event: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": event["title"],
        "description": event.get("description") or "",
        "location": event.get("location") or "",
        "status": event.get("status") or "confirmed",
        "start": _google_time(event["startTime"], event, "start"),
        "end": _google_time(event["endTime"], event, "end"),
    }
    attendees = [{"email": item} for item in event.get("attendees") or [] if isinstance(item, str) and item.strip()]
    if attendees:
        body["attendees"] = attendees
    recurrence = event.get("recurrence")
    if isinstance(recurrence, dict) and isinstance(recurrence.get("rules"), list):
        body["recurrence"] = recurrence["rules"]
    elif isinstance(recurrence, list):
        body["recurrence"] = recurrence
    reminders = _google_reminders(event.get("reminders"))
    if reminders:
        body["reminders"] = {"useDefault": False, "overrides": reminders}
    color_id = _google_color_id(str(event.get("color") or ""))
    if color_id:
        body["colorId"] = color_id
    return body


def _google_time(value: Any, event: dict[str, Any], _field: str) -> dict[str, str]:
    timezone_name = str(event.get("timezone") or "UTC")
    if event.get("all_day"):
        return {"date": iso_time(value, "event_time").date().isoformat()}
    return {"dateTime": str(value), "timeZone": timezone_name}


def _google_reminders(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reminders: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip()
        minutes = item.get("minutes_before") if "minutes_before" in item else item.get("minutesBefore")
        if method and isinstance(minutes, int):
            reminders.append({"method": method, "minutes": minutes})
    return reminders


def _google_color_id(color: str) -> str:
    return {
        "blue": "1",
        "green": "2",
        "purple": "3",
        "red": "4",
        "orange": "5",
        "pink": "4",
    }.get(color, "")


def _local_payload_from_remote(
    remote_event: dict[str, Any],
    *,
    fallback: dict[str, Any],
    connection: dict[str, Any],
    calendar: dict[str, Any],
    for_update: bool,
) -> dict[str, Any]:
    remote_payload = google_event_payload(remote_event, connection=connection, calendar=calendar) or {}
    local_payload = {**fallback, **remote_payload, "source": "google_calendar"}
    fallback_refs = normalize_external_refs(fallback.get("external_refs") or {})
    remote_refs = normalize_external_refs(remote_payload.get("external_refs") or {})
    local_payload["external_refs"] = {**fallback_refs, **remote_refs, "provider": GOOGLE_PROVIDER}
    if fallback.get("idempotency_key"):
        local_payload["idempotency_key"] = fallback["idempotency_key"]
    if for_update:
        local_payload.pop("idempotency_key", None)
    return local_payload


def _ref_value(refs: dict[str, Any], field: str) -> str:
    return str(refs.get(field) or "").strip()


def _secret_lookup_result(connection_id: str) -> dict[str, Any]:
    return {
        "requires_secrets": True,
        "resource_type": "calendar_connection",
        "resource_id": connection_id,
    }
