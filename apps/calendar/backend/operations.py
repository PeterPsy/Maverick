"""Calendar event CRUD, movement, and listing operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from availability import first_free_slot, raise_if_rejected_conflicts, window_conflicts
from calendar_visibility import filter_visible_events
from constants import MAX_EVENTS, SCHEMA_VERSION
from errors import CalendarConflictError, CalendarRevisionConflictError
from event_records import (
    event_profile,
    event_revision,
    filter_events,
    normalize_event,
)
from request_inputs import (
    idempotency_key_from_payload,
    move_strategy,
    normalize_conflict_policy,
    participants_from_body,
)
from scalars import string_list
from store import read_state, update_state
from time_values import format_time, iso_time, now_string


def list_events(
    data_root: Path,
    *,
    start_after: Any = None,
    end_before: Any = None,
    query: str = "",
    tags: Any = None,
    category: Any = None,
    attendee: Any = None,
    limit: int | None = None,
    offset: int = 0,
    include_description: bool = True,
    profile: str = "full",
) -> list[dict[str, Any]]:
    """Return events sorted by start time with optional agent-facing filters."""
    state = read_state(data_root)
    events = sorted(
        filter_visible_events(
            [normalize_event(item) for item in state.get("events", [])],
            state.get("calendars", []),
        ),
        key=lambda item: item["startTime"],
    )
    filtered = filter_events(
        events,
        start_after=start_after,
        end_before=end_before,
        query=query,
        tags=tags,
        category=category,
        attendee=attendee,
    )
    window = filtered[offset : offset + limit if limit else None]
    return [event_profile(event, profile=profile, include_description=include_description) for event in window]


def create_event(data_root: Path, event_payload: dict[str, Any], *, conflict_policy: str = "allow") -> tuple[dict[str, Any], bool]:
    idempotency_key = idempotency_key_from_payload(event_payload)
    conflict_policy = normalize_conflict_policy(conflict_policy)
    event: dict[str, Any] | None = None
    idempotent_replay = False

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal event, idempotent_replay
        events = [normalize_event(item) for item in state.get("events", [])]
        if idempotency_key:
            existing = _find_event_by_idempotency_key(events, idempotency_key)
            if existing is not None:
                event = existing
                idempotent_replay = True
                state["schema_version"] = SCHEMA_VERSION
                state["events"] = events
                return state
        if len(events) >= MAX_EVENTS:
            raise ValueError(f"Calendar can store at most {MAX_EVENTS} events.")
        now = now_string()
        event = normalize_event(
            event_payload,
            event_id=f"evt_{uuid4().hex[:12]}",
            created_at=now,
            updated_at=now,
            revision=1,
        )
        conflict_events = filter_visible_events(events, state.get("calendars", []))
        raise_if_rejected_conflicts("create", conflict_policy, event, conflict_events)
        events.append(event)
        state["schema_version"] = SCHEMA_VERSION
        state["events"] = events
        return state

    update_state(data_root, updater)
    return event or {}, idempotent_replay


def update_event(
    data_root: Path,
    event_id: str,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str = "allow",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    updated: dict[str, Any] | None = None
    conflict_policy = normalize_conflict_policy(conflict_policy)

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal updated
        events = [normalize_event(item) for item in state.get("events", [])]
        conflict_events = filter_visible_events(events, state.get("calendars", []))
        updated = _updated_event_from_events(
            events,
            event_id,
            event_payload,
            conflict_policy=conflict_policy,
            expected_revision=expected_revision,
            conflict_events=conflict_events,
        )
        next_events = [updated if event["id"] == event_id else event for event in events]
        state["schema_version"] = SCHEMA_VERSION
        state["events"] = next_events
        return state

    update_state(data_root, updater)
    return updated or {}


def preview_update_event(
    data_root: Path,
    event_id: str,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str = "allow",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Validate and shape an update without writing local Calendar state."""
    conflict_policy = normalize_conflict_policy(conflict_policy)
    state = read_state(data_root)
    events = [normalize_event(item) for item in state.get("events", [])]
    conflict_events = filter_visible_events(events, state.get("calendars", []))
    return _updated_event_from_events(
        events,
        event_id,
        event_payload,
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
        conflict_events=conflict_events,
    )


def delete_event(data_root: Path, event_id: str, *, expected_revision: int | None = None) -> None:
    deleted = False

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal deleted
        events = [normalize_event(item) for item in state.get("events", [])]
        visible_event_ids = {event["id"] for event in filter_visible_events(events, state.get("calendars", []))}
        next_events = []
        for event in events:
            if event["id"] == event_id:
                if event_id not in visible_event_ids:
                    next_events.append(event)
                    continue
                _check_expected_revision("delete", event, expected_revision)
                deleted = True
                continue
            next_events.append(event)
        if not deleted:
            raise ValueError(f"Calendar event `{event_id}` was not found.")
        state["schema_version"] = SCHEMA_VERSION
        state["events"] = next_events
        return state

    update_state(data_root, updater)


def preview_delete_event(data_root: Path, event_id: str, *, expected_revision: int | None = None) -> dict[str, Any]:
    """Validate that an event can be deleted and return the current event."""
    event = _read_event(data_root, event_id)
    _check_expected_revision("delete", event, expected_revision)
    return event


def move_event(
    data_root: Path,
    event_id: str,
    body: dict[str, Any],
    *,
    conflict_policy: str = "allow",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Move one event, preserving duration unless a new end time is supplied."""
    return update_event(
        data_root,
        event_id,
        move_event_payload(data_root, event_id, body),
        conflict_policy=conflict_policy,
        expected_revision=expected_revision,
    )


def move_event_payload(data_root: Path, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Return the update payload for a move without writing Calendar state."""
    event = _read_event(data_root, event_id)
    start_value = body.get("startTime") or body.get("start_time")
    if not start_value and move_strategy(body) == "first_free":
        return _first_free_move_payload(
            data_root,
            event_id,
            event,
            body,
        )
    if not start_value:
        raise ValueError("`startTime` is required unless `move_strategy` is `first_free`.")
    start_time = iso_time(start_value, "startTime")
    if body.get("endTime") or body.get("end_time"):
        end_time = iso_time(body.get("endTime") or body.get("end_time"), "endTime")
    else:
        duration = iso_time(event["endTime"], "endTime") - iso_time(event["startTime"], "startTime")
        end_time = start_time + duration
    return {
        "startTime": format_time(start_time),
        "endTime": format_time(end_time),
    }


def _first_free_move_payload(
    data_root: Path,
    event_id: str,
    event: dict[str, Any],
    body: dict[str, Any],
) -> dict[str, Any]:
    start_after = iso_time(body.get("start_after") or body.get("startAfter"), "start_after")
    end_before = iso_time(body.get("end_before") or body.get("endBefore"), "end_before")
    if end_before <= start_after:
        raise ValueError("`end_before` must be after `start_after`.")

    duration = iso_time(event["endTime"], "endTime") - iso_time(event["startTime"], "startTime")
    selected_participants = participants_from_body(body) or set(string_list(event.get("attendees")))
    slot = first_free_slot(
        data_root,
        start_after,
        end_before,
        duration,
        participants=selected_participants,
        ignore_event_id=event_id,
    )
    if slot is None:
        conflicts = window_conflicts(
            data_root,
            start_after,
            end_before,
            participants=selected_participants,
            ignore_event_id=event_id,
        )
        raise CalendarConflictError(
            "Calendar move could not find a free slot matching the event duration in the requested window.",
            conflicts,
        )
    return {
        "startTime": format_time(slot[0]),
        "endTime": format_time(slot[1]),
    }


def _find_event_by_idempotency_key(events: list[dict[str, Any]], idempotency_key: str) -> dict[str, Any] | None:
    for event in events:
        if str(event.get("idempotency_key") or "") == idempotency_key:
            return event
    return None


def _check_expected_revision(action: str, event: dict[str, Any], expected_revision: int | None) -> None:
    if expected_revision is None:
        raise ValueError(f"`expected_revision` is required for Calendar {action}.")
    actual_revision = event_revision(event.get("revision"))
    if actual_revision == expected_revision:
        return
    event_id = str(event.get("id") or "")
    raise CalendarRevisionConflictError(
        f"Calendar {action} expected revision {expected_revision} for event `{event_id}`, but current revision is {actual_revision}.",
        event_id=event_id,
        expected_revision=expected_revision,
        actual_revision=actual_revision,
        current_event=event_profile(event, profile="compact", include_description=False),
    )


def _updated_event_from_events(
    events: list[dict[str, Any]],
    event_id: str,
    event_payload: dict[str, Any],
    *,
    conflict_policy: str,
    expected_revision: int | None,
    conflict_events: list[dict[str, Any]],
) -> dict[str, Any]:
    _reject_create_only_fields(event_payload)
    visible_event_ids = {event["id"] for event in conflict_events}
    for event in events:
        if event["id"] != event_id:
            continue
        if event_id not in visible_event_ids:
            break
        _check_expected_revision("update", event, expected_revision)
        updated = normalize_event(
            {**event, **event_payload, "id": event_id},
            created_at=event.get("created_at"),
            updated_at=now_string(),
            revision=event_revision(event.get("revision")) + 1,
        )
        raise_if_rejected_conflicts("update", conflict_policy, updated, conflict_events, ignore_event_id=event_id)
        return updated
    raise ValueError(f"Calendar event `{event_id}` was not found.")


def _reject_create_only_fields(event_payload: dict[str, Any]) -> None:
    if "idempotency_key" in event_payload or "idempotencyKey" in event_payload:
        raise ValueError("`idempotency_key` is create-only and cannot be changed after event creation.")


def _read_event(data_root: Path, event_id: str) -> dict[str, Any]:
    event = get_event(data_root, event_id)
    if event is not None:
        return event
    raise ValueError(f"Calendar event `{event_id}` was not found.")


def get_event(data_root: Path, event_id: str) -> dict[str, Any] | None:
    for event in list_events(data_root):
        if event["id"] == event_id:
            return event
    return None
