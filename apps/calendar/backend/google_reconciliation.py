"""Reconcile remote changes with the latest mirror inside the state transaction."""

from __future__ import annotations
from datetime import datetime
import hashlib
from typing import Any
from event_records import event_revision, normalize_event
from time_values import format_time, iso_time, event_time


def _merge_remote_events(
    events: list[dict[str, Any]],
    *,
    connection: dict[str, Any],
    calendar: dict[str, Any],
    remote_events: list[dict[str, Any]],
    full_sync: bool,
    stale_time_min: str,
    stale_time_max: str,
    now: datetime,
    baseline: list[dict[str, Any]],
    seen_remote_ids: set[str],
    mapper,
) -> dict[str, Any]:
    next_events, deduplicated = _dedupe_remote_calendar_events(
        events,
        connection_id=connection["id"],
        provider_calendar_id=calendar["provider_calendar_id"],
    )
    existing_by_remote_id = _events_by_remote_id(
        next_events,
        connection_id=connection["id"],
        provider_calendar_id=calendar["provider_calendar_id"],
    )
    active_remote_ids = set(seen_remote_ids)
    baseline_by_id = {item["id"]: item for item in baseline}
    baseline_remote = _events_by_remote_id(
        baseline,
        connection_id=connection["id"],
        provider_calendar_id=calendar["provider_calendar_id"],
    )
    concurrent_ids = {
        e["id"]
        for e in events
        if _matches_remote_calendar(
            e,
            connection_id=connection["id"],
            provider_calendar_id=calendar["provider_calendar_id"],
        )
        and e != baseline_by_id.get(e["id"])
    }
    deleted_remote_ids = set(baseline_remote) - set(existing_by_remote_id)
    conflicts: list[str] = []
    created = updated = unchanged = 0
    deleted = deduplicated

    for remote_event in remote_events:
        provider_event_id = str(remote_event.get("id") or "").strip()
        if not provider_event_id:
            continue
        existing = existing_by_remote_id.get(provider_event_id)
        original = baseline_remote.get(provider_event_id)
        active_remote_ids.add(provider_event_id)
        if remote_event.get("recurringEventId"):
            active_remote_ids.add(remote_event["recurringEventId"])
        if (
            provider_event_id in deleted_remote_ids
            or existing is not None
            and existing["id"] in concurrent_ids
        ):
            conflicts.append((existing or original)["id"])
            continue
        if (
            str(remote_event.get("status") or "").strip().lower() == "cancelled"
            or remote_event.get("deleted") is True
        ):
            if existing is not None:
                next_events = [
                    item for item in next_events if item["id"] != existing["id"]
                ]
                existing_by_remote_id.pop(provider_event_id, None)
                deleted += 1
            if not remote_event.get("recurringEventId"):
                for item in list(next_events):
                    if (
                        _matches_remote_calendar(
                            item,
                            connection_id=connection["id"],
                            provider_calendar_id=calendar["provider_calendar_id"],
                        )
                        and (item.get("external_refs") or {}).get("recurring_event_id")
                        == provider_event_id
                    ):
                        if item["id"] in concurrent_ids:
                            conflicts.append(item["id"])
                            continue
                        next_events.remove(item)
                        deleted += 1
            continue
        active_remote_ids.add(provider_event_id)
        payload = mapper(remote_event, connection=connection, calendar=calendar)
        if payload is None:
            continue
        if existing is None:
            event = normalize_event(
                payload,
                event_id=_local_event_id(
                    connection["id"],
                    calendar["provider_calendar_id"],
                    provider_event_id,
                ),
                created_at=payload.get("created_at") or format_time(now),
                updated_at=payload.get("updated_at") or format_time(now),
                revision=1,
            )
            next_events.append(event)
            existing_by_remote_id[provider_event_id] = event
            created += 1
            continue
        if (existing.get("recurrence") or {}).get("exceptions") and payload.get(
            "recurrence"
        ):
            payload["recurrence"]["exceptions"] = existing["recurrence"]["exceptions"]
        for local_field in ("category", "tags"):
            payload[local_field] = existing.get(local_field, payload.get(local_field))
        event = normalize_event(
            {**existing, **payload, "id": existing["id"]},
            created_at=existing.get("created_at"),
            updated_at=payload.get("updated_at") or format_time(now),
            revision=event_revision(existing.get("revision")) + 1,
        )
        if _event_comparison(existing) == _event_comparison(event):
            unchanged += 1
            continue
        next_events = [
            event if item["id"] == existing["id"] else item for item in next_events
        ]
        existing_by_remote_id[provider_event_id] = event
        updated += 1

    # A cancelled exception can omit start/end. Keep its original civil date as an exclusion.
    for remote in remote_events:
        if (
            remote.get("status") != "cancelled"
            or not remote.get("recurringEventId")
            or not remote.get("originalStartTime")
        ):
            continue
        master = next(
            (
                e
                for e in next_events
                if _matches_remote_calendar(
                    e,
                    connection_id=connection["id"],
                    provider_calendar_id=calendar["provider_calendar_id"],
                )
                and (e.get("external_refs") or {}).get("provider_event_id")
                == remote["recurringEventId"]
            ),
            None,
        )
        if not master or master["id"] in conflicts:
            continue
        if master["id"] in concurrent_ids:
            conflicts.append(master["id"])
            continue
        original = remote["originalStartTime"]
        stamp = format_time(
            event_time(
                original.get("dateTime") or original.get("date"),
                "originalStartTime",
                master["timezone"],
            )
        )
        recurrence = dict(master["recurrence"])
        exceptions = dict(recurrence.get("exceptions", {}))
        if exceptions.get(stamp) != {"deleted": True}:
            exceptions[stamp] = {"deleted": True}
            replacement = normalize_event(
                {**master, "recurrence": {**recurrence, "exceptions": exceptions}},
                revision=master["revision"] + 1,
            )
            next_events = [
                replacement if e["id"] == master["id"] else e for e in next_events
            ]
            updated += 1

    if full_sync:
        conflicts += [
            item["id"]
            for item in next_events
            if _matches_remote_calendar(
                item,
                connection_id=connection["id"],
                provider_calendar_id=calendar["provider_calendar_id"],
            )
            and _event_in_stale_scope(
                item, time_min=stale_time_min, time_max=stale_time_max
            )
            and item != baseline_by_id.get(item["id"])
            and str((item.get("external_refs") or {}).get("provider_event_id") or "")
            not in active_remote_ids
        ]
        stale_ids = {
            item["id"]
            for item in next_events
            if _matches_remote_calendar(
                item,
                connection_id=connection["id"],
                provider_calendar_id=calendar["provider_calendar_id"],
            )
            and item == baseline_by_id.get(item["id"])
            and _event_in_stale_scope(
                item, time_min=stale_time_min, time_max=stale_time_max
            )
            and str((item.get("external_refs") or {}).get("provider_event_id") or "")
            not in active_remote_ids
        }
        if stale_ids:
            next_events = [item for item in next_events if item["id"] not in stale_ids]
            deleted += len(stale_ids)

    return {
        "events": next_events,
        "conflicts": conflicts,
        "seen_remote_ids": sorted(active_remote_ids),
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged,
    }


def _events_by_remote_id(
    events: list[dict[str, Any]], *, connection_id: str, provider_calendar_id: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if not _matches_remote_calendar(
            event,
            connection_id=connection_id,
            provider_calendar_id=provider_calendar_id,
        ):
            continue
        refs = (
            event.get("external_refs")
            if isinstance(event.get("external_refs"), dict)
            else {}
        )
        provider_event_id = str(refs.get("provider_event_id") or "").strip()
        if provider_event_id:
            result[provider_event_id] = event
    return result


def _dedupe_remote_calendar_events(
    events: list[dict[str, Any]],
    *,
    connection_id: str,
    provider_calendar_id: str,
) -> tuple[list[dict[str, Any]], int]:
    best_by_remote_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for event in events:
        if not _matches_remote_calendar(
            event,
            connection_id=connection_id,
            provider_calendar_id=provider_calendar_id,
        ):
            continue
        refs = (
            event.get("external_refs")
            if isinstance(event.get("external_refs"), dict)
            else {}
        )
        provider_event_id = str(refs.get("provider_event_id") or "").strip()
        if not provider_event_id:
            continue
        current = best_by_remote_id.get(provider_event_id)
        if current is None:
            best_by_remote_id[provider_event_id] = event
            continue
        keep, drop = _preferred_remote_mirror(current, event)
        best_by_remote_id[provider_event_id] = keep
        duplicate_ids.add(str(drop.get("id") or ""))
    duplicate_ids.discard("")
    if not duplicate_ids:
        return list(events), 0
    return [
        event for event in events if str(event.get("id") or "") not in duplicate_ids
    ], len(duplicate_ids)


def _preferred_remote_mirror(
    left: dict[str, Any], right: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if _remote_mirror_sort_key(right) > _remote_mirror_sort_key(left):
        return right, left
    return left, right


def _remote_mirror_sort_key(event: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(event.get("updated_at") or ""),
        event_revision(event.get("revision")),
        str(event.get("created_at") or ""),
        str(event.get("id") or ""),
    )


def _matches_remote_calendar(
    event: dict[str, Any], *, connection_id: str, provider_calendar_id: str
) -> bool:
    refs = (
        event.get("external_refs")
        if isinstance(event.get("external_refs"), dict)
        else {}
    )
    return (
        str(refs.get("calendar_connection_id") or "").strip() == connection_id
        and str(refs.get("provider_calendar_id") or "").strip() == provider_calendar_id
        and str(refs.get("provider_event_id") or "").strip()
    )


def _event_in_stale_scope(
    event: dict[str, Any], *, time_min: str, time_max: str
) -> bool:
    if not time_min and not time_max:
        return True
    try:
        start_time = iso_time(event.get("startTime"), "startTime")
        end_time = iso_time(event.get("endTime"), "endTime")
        min_time = iso_time(time_min, "time_min") if time_min else None
        max_time = iso_time(time_max, "time_max") if time_max else None
    except ValueError:
        return False
    if min_time and end_time <= min_time:
        return False
    if max_time and start_time >= max_time:
        return False
    return True


def _event_comparison(event: dict[str, Any]) -> dict[str, Any]:
    ignored = {"updated_at", "revision"}
    return {key: value for key, value in event.items() if key not in ignored}


def _local_event_id(
    connection_id: str, provider_calendar_id: str, provider_event_id: str
) -> str:
    digest = hashlib.sha256(
        f"{connection_id}\n{provider_calendar_id}\n{provider_event_id}".encode("utf-8")
    ).hexdigest()
    return f"evt_gcal_{digest[:24]}"


def google_idempotency_key(
    connection_id: str, provider_calendar_id: str, provider_event_id: str
) -> str:
    digest = hashlib.sha256(
        f"{connection_id}\n{provider_calendar_id}\n{provider_event_id}".encode("utf-8")
    ).hexdigest()
    return f"google:{digest[:48]}"
