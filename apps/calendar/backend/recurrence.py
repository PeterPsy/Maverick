"""Bounded recurrence expansion with civil times, stable occurrence ids and exceptions."""

from __future__ import annotations
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from recurrence_rules import MAX_OCCURRENCES, recurrence_rules, rule_set
from time_values import format_time, iso_time


def validate_recurrence(event):
    if recurrence_rules(event.get("recurrence")):
        rule_set(event)


def occurrence_id(series_id, start):
    return series_id + "@" + iso_time(start, "occurrence").strftime("%Y%m%dT%H%M%SZ")


def expand_events(events, start_after=None, end_before=None):
    """Unbounded lists expose series records; bounded windows expose occurrences."""
    if not start_after or not end_before:
        return list(events)
    after, before = iso_time(start_after, "start_after"), iso_time(
        end_before, "end_before"
    )
    if before <= after:
        raise ValueError("Recurrence window must end after it starts.")
    overrides = {}
    for event in events:
        refs = event.get("external_refs") or {}
        if refs.get("recurring_event_id") and refs.get("original_start_time"):
            value = refs["original_start_time"]
            original = (
                value.get("dateTime") or value.get("date")
                if isinstance(value, dict)
                else value
            )
            original = datetime.fromisoformat(original.replace("Z", "+00:00"))
            if original.tzinfo is None:
                original = original.replace(
                    tzinfo=ZoneInfo(event.get("timezone") or "UTC")
                )
            overrides[
                (
                    refs.get("calendar_connection_id"),
                    refs.get("provider_calendar_id"),
                    refs["recurring_event_id"],
                    format_time(original),
                )
            ] = event
    result = []
    for event in events:
        rules = rule_set(event)
        if rules is None:
            result.append(event)
            continue
        zone = ZoneInfo(event.get("timezone") or "UTC")
        start = iso_time(event["startTime"], "startTime").astimezone(zone)
        duration = iso_time(event["endTime"], "endTime").astimezone(zone) - start
        exceptions = (event.get("recurrence") or {}).get("exceptions", {})
        refs = event.get("external_refs") or {}
        count = 0
        for local_start in rules.xafter((after - duration).astimezone(zone), inc=True):
            if local_start >= before:
                break
            count += 1
            if count > MAX_OCCURRENCES:
                raise ValueError(
                    "Recurrence window exceeds 10000 occurrences; narrow the interval."
                )
            # Ignore civil times skipped by daylight saving.
            if local_start.astimezone(UTC).astimezone(zone).replace(
                tzinfo=None
            ) != local_start.replace(tzinfo=None):
                continue
            stamp = format_time(local_start)
            if (
                refs.get("calendar_connection_id"),
                refs.get("provider_calendar_id"),
                refs.get("provider_event_id"),
                stamp,
            ) in overrides:
                continue
            occurrence = {
                **event,
                "id": occurrence_id(event["id"], stamp),
                "series_id": event["id"],
                "original_start_time": stamp,
                "startTime": stamp,
                "endTime": format_time(local_start + duration),
            }
            if event.get("all_day"):
                occurrence.update(
                    all_day_start=local_start.date().isoformat(),
                    all_day_end=(local_start + duration).date().isoformat(),
                )
            patch = exceptions.get(stamp, {})
            if patch.get("deleted"):
                continue
            occurrence.update(patch)
            if event.get("all_day"):
                occurrence.update(
                    all_day_start=iso_time(occurrence["startTime"], "startTime")
                    .astimezone(zone)
                    .date()
                    .isoformat(),
                    all_day_end=iso_time(occurrence["endTime"], "endTime")
                    .astimezone(zone)
                    .date()
                    .isoformat(),
                )
            result.append(occurrence)
        # Moved exceptions can enter the window from outside its original range.
        for stamp, patch in exceptions.items():
            oid = occurrence_id(event["id"], stamp)
            if (
                patch.get("deleted")
                or not patch.get("startTime")
                or any(e["id"] == oid for e in result)
            ):
                continue
            if (
                iso_time(patch["startTime"], "startTime") < before
                and iso_time(
                    patch.get("endTime")
                    or format_time(
                        iso_time(stamp, "original").astimezone(zone) + duration
                    ),
                    "endTime",
                )
                > after
            ):
                moved = {
                    **event,
                    "startTime": stamp,
                    "endTime": format_time(
                        iso_time(stamp, "original").astimezone(zone) + duration
                    ),
                    **patch,
                    "id": oid,
                    "series_id": event["id"],
                    "original_start_time": stamp,
                }
                if moved.get("all_day"):
                    moved.update(
                        all_day_start=iso_time(moved["startTime"], "startTime")
                        .astimezone(zone)
                        .date()
                        .isoformat(),
                        all_day_end=iso_time(moved["endTime"], "endTime")
                        .astimezone(zone)
                        .date()
                        .isoformat(),
                    )
                result.append(moved)
    return sorted(result, key=lambda e: (e["startTime"], e["id"]))


def resolve_occurrence(events, event_id):
    if "@" not in event_id:
        return None
    base, stamp = event_id.rsplit("@", 1)
    try:
        original = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    series = next((e for e in events if e["id"] == base), None)
    if not series:
        return None
    return next(
        (
            e
            for e in expand_events(
                [series],
                format_time(original),
                format_time(original + timedelta(seconds=1)),
            )
            if e["id"] == event_id
        ),
        None,
    )


def shifted_exceptions(exceptions, delta, *, cut=None, timezone="UTC"):
    zone = ZoneInfo(timezone)
    shifted = {}
    for stamp, patch in exceptions.items():
        if cut and iso_time(stamp, "exception") < iso_time(cut, "cut"):
            continue
        next_patch = dict(patch)
        for field in ("startTime", "endTime"):
            if patch.get(field):
                next_patch[field] = format_time(
                    iso_time(patch[field], field).astimezone(zone) + delta
                )
        shifted[format_time(iso_time(stamp, "exception").astimezone(zone) + delta)] = (
            next_patch
        )
    return shifted
