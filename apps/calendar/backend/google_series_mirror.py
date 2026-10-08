"""Persist accepted Google series changes while preserving exceptions and revisions."""

from event_records import normalize_event
from google_event_mapping import google_event_payload
from operations import _check_expected_revision
from recurrence import shifted_exceptions
from store import update_state
from time_values import event_time, format_time, iso_time
from zoneinfo import ZoneInfo

SERIES_FIELDS = (
    "title",
    "description",
    "location",
    "attendees",
    "status",
    "transparency",
    "color",
    "reminders",
    "reminders_use_default",
    "all_day",
)


def belongs(event, ref, series_id):
    refs = event.get("external_refs") or {}
    return (
        refs.get("calendar_connection_id") == ref["calendar_connection_id"]
        and refs.get("provider_calendar_id") == ref["provider_calendar_id"]
        and (
            refs.get("provider_event_id") == series_id
            or refs.get("recurring_event_id") == series_id
        )
    )


def original_start(event):
    value = event.get("original_start_time") or (event.get("external_refs") or {}).get(
        "original_start_time", {}
    )
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date")
    return format_time(event_time(value, "original_start_time", event["timezone"]))


def series_exceptions(events, master, ref, series_id):
    """Expanded ordinary instances are a cache; edited instances are exceptions."""
    exceptions = dict((master.get("recurrence") or {}).get("exceptions", {}))
    zone = ZoneInfo(master["timezone"])
    duration = iso_time(master["endTime"], "endTime").astimezone(zone) - iso_time(
        master["startTime"], "startTime"
    ).astimezone(zone)
    for event in events:
        if not belongs(event, ref, series_id):
            continue
        if event.get("recurrence"):
            exceptions.update(event["recurrence"].get("exceptions", {}))
        if not (event.get("external_refs") or {}).get("recurring_event_id"):
            continue
        stamp = original_start(event)
        patch = {
            field: event.get(field)
            for field in SERIES_FIELDS
            if event.get(field) != master.get(field)
        }
        if event["startTime"] != stamp:
            patch["startTime"] = event["startTime"]
        expected_end = format_time(
            iso_time(stamp, "original").astimezone(zone) + duration
        )
        if event["endTime"] != expected_end:
            patch["endTime"] = event["endTime"]
        if patch:
            exceptions[stamp] = patch
    return exceptions


def mirror_series(
    data_root,
    master,
    remote,
    connection,
    calendar,
    series_id,
    current,
    baseline,
    *,
    cut=None,
    exceptions=None,
):
    result = normalize_event(
        google_event_payload(remote, connection=connection, calendar=calendar),
        event_id=master["id"],
        revision=current["revision"] + 1,
    )
    ref = current["external_refs"]
    expected = {e["id"]: e for e in baseline if belongs(e, ref, series_id)}
    if exceptions is None:
        exceptions = series_exceptions(baseline, master, ref, series_id)
    if cut:
        exceptions = {k: v for k, v in exceptions.items() if k < cut}
    elif result.get("recurrence"):
        zone = ZoneInfo(master["timezone"])
        delta = iso_time(result["startTime"], "startTime").astimezone(zone) - iso_time(
            master["startTime"], "startTime"
        ).astimezone(zone)
        exceptions = shifted_exceptions(exceptions, delta, timezone=master["timezone"])
    if result.get("recurrence"):
        result["recurrence"]["exceptions"] = exceptions

    def updater(state):
        next_events = []
        for event in state["events"]:
            if belongs(event, ref, series_id):
                # A concurrent edit must never be removed with an expanded cache row.
                original = expected.get(event["id"])
                if original is None or event != original:
                    _check_expected_revision(
                        "update", event, (original or {}).get("revision", 0)
                    )
                continue
            next_events.append(event)
        state["events"] = next_events + [result]
        return state

    update_state(data_root, updater)
    return result
