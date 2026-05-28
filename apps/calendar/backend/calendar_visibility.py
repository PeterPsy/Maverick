"""Calendar event visibility derived from remote calendar selections."""

from __future__ import annotations

from typing import Any

from constants import GOOGLE_PROVIDER
from event_records import normalize_external_refs


def filter_visible_events(events: list[dict[str, Any]], calendars: Any) -> list[dict[str, Any]]:
    """Return events that should be visible through Calendar read surfaces."""
    disabled_keys = _disabled_google_calendar_keys(calendars)
    if not disabled_keys:
        return list(events)
    return [event for event in events if not _matches_disabled_google_calendar(event, disabled_keys)]


def _disabled_google_calendar_keys(calendars: Any) -> set[tuple[str, str]]:
    if not isinstance(calendars, list):
        return set()
    disabled: set[tuple[str, str]] = set()
    for item in calendars:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or GOOGLE_PROVIDER).strip().lower()
        if provider != GOOGLE_PROVIDER:
            continue
        connection_id = str(item.get("connection_id") or item.get("connectionId") or "").strip()
        provider_calendar_id = str(
            item.get("provider_calendar_id")
            or item.get("providerCalendarId")
            or item.get("google_calendar_id")
            or item.get("googleCalendarId")
            or item.get("calendar_id")
            or item.get("calendarId")
            or ""
        ).strip()
        if not connection_id or not provider_calendar_id:
            continue
        sync_enabled = item.get("sync_enabled") if "sync_enabled" in item else item.get("syncEnabled")
        if item.get("selected") is False or sync_enabled is False:
            disabled.add((connection_id, provider_calendar_id))
    return disabled


def _matches_disabled_google_calendar(event: dict[str, Any], disabled_keys: set[tuple[str, str]]) -> bool:
    source = str(event.get("source") or "").strip().lower()
    refs = normalize_external_refs(event.get("external_refs") or event.get("externalRefs"))
    provider = str(refs.get("provider") or "").strip().lower()
    if source != "google_calendar" and provider != GOOGLE_PROVIDER:
        return False
    connection_id = str(refs.get("calendar_connection_id") or "").strip()
    provider_calendar_id = str(refs.get("provider_calendar_id") or "").strip()
    if not connection_id or not provider_calendar_id:
        return False
    return (connection_id, provider_calendar_id) in disabled_keys
