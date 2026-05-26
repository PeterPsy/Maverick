"""Calendar availability, conflict, and free-time calculations."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from errors import CalendarConflictError
from request_inputs import participants_from_body
from scalars import casefold_set, optional_int, string_list
from store import read_state
from time_values import format_time, iso_time


def _events_for_availability(data_root: Path) -> list[dict[str, Any]]:
    return sorted(read_state(data_root).get("events", []), key=lambda item: item["startTime"])


def check_availability(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Check a specific event window and return compact conflict records."""
    start_value = body.get("startTime") or body.get("start_time") or body.get("start_after") or body.get("startAfter")
    end_value = body.get("endTime") or body.get("end_time") or body.get("end_before") or body.get("endBefore")
    start_time = iso_time(start_value, "startTime")
    end_time = iso_time(end_value, "endTime")
    if end_time <= start_time:
        raise ValueError("Availability endTime must be after startTime.")
    selected_participants = participants_from_body(body)
    ignore_event_id = str(body.get("ignore_event_id") or body.get("ignoreEventId") or "").strip()
    probe = {
        "id": ignore_event_id or "__availability_probe__",
        "title": "Availability check",
        "startTime": format_time(start_time),
        "endTime": format_time(end_time),
        "attendees": sorted(selected_participants),
        "category": "Availability",
        "tags": [],
        "timezone": "UTC",
        "all_day": False,
    }
    conflicts = conflicts_for_event(_events_for_availability(data_root), probe, ignore_event_id=ignore_event_id)
    return {
        "action": "check_availability",
        "available": not conflicts,
        "status": "free" if not conflicts else "conflicting",
        "window": {"startTime": format_time(start_time), "endTime": format_time(end_time)},
        "participants": sorted(selected_participants),
        "conflicts": conflicts,
    }


def find_free_time(data_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Find free slots inside a bounded time window."""
    start_after = iso_time(body.get("start_after") or body.get("startAfter"), "start_after")
    end_before = iso_time(body.get("end_before") or body.get("endBefore"), "end_before")
    if end_before <= start_after:
        raise ValueError("`end_before` must be after `start_after`.")
    duration_minutes = optional_int(body.get("duration_minutes"), field="duration_minutes", minimum=1, maximum=1440) or 30
    limit = optional_int(body.get("limit"), field="limit", minimum=1, maximum=50) or 10
    duration = timedelta(minutes=duration_minutes)
    selected_participants = participants_from_body(body)
    ignore_event_id = str(body.get("ignore_event_id") or body.get("ignoreEventId") or "").strip()

    busy = _busy_intervals(
        data_root,
        start_after,
        end_before,
        participants=selected_participants,
        ignore_event_id=ignore_event_id,
    )

    slots: list[dict[str, Any]] = []
    cursor = start_after
    for busy_start, busy_end in busy:
        while len(slots) < limit and cursor + duration <= busy_start:
            slots.append(_slot(cursor, cursor + duration))
            cursor = cursor + duration
        if len(slots) >= limit:
            break
        if busy_end > cursor:
            cursor = busy_end
    while len(slots) < limit and cursor + duration <= end_before:
        slots.append(_slot(cursor, cursor + duration))
        cursor = cursor + duration

    return {
        "action": "find_free_time",
        "duration_minutes": duration_minutes,
        "window": {"start_after": format_time(start_after), "end_before": format_time(end_before)},
        "participants": sorted(selected_participants),
        "busy_count": len(busy),
        "slots": slots[:limit],
    }


def raise_if_rejected_conflicts(
    action: str,
    conflict_policy: str,
    candidate: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    ignore_event_id: str = "",
) -> None:
    if conflict_policy != "reject":
        return
    conflicts = conflicts_for_event(events, candidate, ignore_event_id=ignore_event_id or candidate["id"])
    if conflicts:
        raise CalendarConflictError(
            f"Calendar {action} conflicts with {len(conflicts)} existing event(s).",
            conflicts,
        )


def conflicts_for_event(
    events: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    ignore_event_id: str = "",
) -> list[dict[str, Any]]:
    if not _event_blocks_availability(candidate):
        return []
    start_time = iso_time(candidate["startTime"], "startTime")
    end_time = iso_time(candidate["endTime"], "endTime")
    participant_keys = casefold_set(string_list(candidate.get("attendees")))
    conflicts: list[dict[str, Any]] = []
    for event in events:
        if event["id"] == ignore_event_id:
            continue
        if not _event_blocks_availability(event):
            continue
        event_start = iso_time(event["startTime"], "startTime")
        event_end = iso_time(event["endTime"], "endTime")
        if event_end <= start_time or event_start >= end_time:
            continue
        event_attendees = casefold_set(string_list(event.get("attendees")))
        if participant_keys and event_attendees and event_attendees.isdisjoint(participant_keys):
            continue
        conflicts.append(_conflict_record(event))
    return conflicts


def first_free_slot(
    data_root: Path,
    start_after: datetime,
    end_before: datetime,
    duration: timedelta,
    *,
    participants: set[str],
    ignore_event_id: str = "",
) -> tuple[datetime, datetime] | None:
    busy = _busy_intervals(
        data_root,
        start_after,
        end_before,
        participants=participants,
        ignore_event_id=ignore_event_id,
    )
    cursor = start_after
    for busy_start, busy_end in busy:
        if cursor + duration <= busy_start:
            return cursor, cursor + duration
        if busy_end > cursor:
            cursor = busy_end
    if cursor + duration <= end_before:
        return cursor, cursor + duration
    return None


def _busy_intervals(
    data_root: Path,
    start_after: datetime,
    end_before: datetime,
    *,
    participants: set[str],
    ignore_event_id: str = "",
) -> list[tuple[datetime, datetime]]:
    busy: list[tuple[datetime, datetime]] = []
    participant_keys = casefold_set(participants)
    for event in _events_for_availability(data_root):
        if event["id"] == ignore_event_id:
            continue
        if not _event_blocks_availability(event):
            continue
        if participant_keys:
            event_attendees = casefold_set(string_list(event.get("attendees")))
            if event_attendees and event_attendees.isdisjoint(participant_keys):
                continue
        event_start = iso_time(event["startTime"], "startTime")
        event_end = iso_time(event["endTime"], "endTime")
        if event_end <= start_after or event_start >= end_before:
            continue
        busy.append((max(event_start, start_after), min(event_end, end_before)))
    busy.sort(key=lambda item: item[0])
    return busy


def _slot(start_time: datetime, end_time: datetime) -> dict[str, Any]:
    return {
        "startTime": format_time(start_time),
        "endTime": format_time(end_time),
        "duration_minutes": int((end_time - start_time).total_seconds() // 60),
    }


def window_conflicts(
    data_root: Path,
    start_time: datetime,
    end_time: datetime,
    *,
    participants: set[str],
    ignore_event_id: str = "",
) -> list[dict[str, Any]]:
    probe = {
        "id": "__availability_window__",
        "title": "Availability window",
        "startTime": format_time(start_time),
        "endTime": format_time(end_time),
        "attendees": sorted(participants),
        "category": "Availability",
        "tags": [],
        "timezone": "UTC",
        "all_day": False,
    }
    return conflicts_for_event(_events_for_availability(data_root), probe, ignore_event_id=ignore_event_id)


def _event_blocks_availability(event: dict[str, Any]) -> bool:
    return str(event.get("status") or "confirmed").strip().lower() != "cancelled"


def _conflict_record(event: dict[str, Any]) -> dict[str, Any]:
    return {
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
