"""Revision-safe mutation scopes for local recurring series and exceptions."""

from __future__ import annotations
from uuid import uuid4
from zoneinfo import ZoneInfo
from availability import raise_if_rejected_conflicts
from calendar_visibility import filter_availability_events
from event_records import normalize_event
from operations import _check_expected_revision, move_event_payload
from constants import MAX_EVENTS
from recurrence import expand_events, resolve_occurrence, shifted_exceptions
from recurrence_rules import split_rules
from store import update_state
from time_values import iso_time, format_time, now_string


def mutate_occurrence(data_root, body, action, policy, expected_revision):
    result = None

    def updater(state):
        nonlocal result
        events = state["events"]
        occurrence = resolve_occurrence(events, body["id"])
        if occurrence is None:
            raise ValueError(f"Calendar event `{body['id']}` was not found.")
        series = next(e for e in events if e["id"] == occurrence["series_id"])
        _check_expected_revision(action, series, expected_revision)
        scope = body.get("recurrence_scope", "occurrence")
        if scope not in {"occurrence", "future", "series"}:
            raise ValueError("recurrence_scope must be occurrence, future or series.")
        patch = dict(body.get("event") or {})
        for key in (
            "id",
            "series_id",
            "original_start_time",
            "revision",
            "idempotency_key",
            "expected_revision",
            "recurrence_scope",
        ):
            patch.pop(key, None)
        if patch.get("recurrence") == occurrence.get("recurrence"):
            patch.pop("recurrence", None)
        if action == "move":
            patch = move_event_payload(data_root, body["id"], body)
        if (
            scope == "future"
            and occurrence["original_start_time"] == series["startTime"]
        ):
            scope = "series"
        if scope == "series":
            if action == "delete":
                state["events"] = [e for e in events if e["id"] != series["id"]]
                result = occurrence
                return state
            # Shift the whole series by the occurrence's civil time delta.
            if patch.get("startTime"):
                zone = ZoneInfo(series["timezone"])
                delta = iso_time(patch["startTime"], "startTime").astimezone(
                    zone
                ) - iso_time(occurrence["startTime"], "startTime").astimezone(zone)
                patch["startTime"] = format_time(
                    iso_time(series["startTime"], "startTime").astimezone(zone) + delta
                )
                if patch.get("endTime"):
                    delta_end = iso_time(patch["endTime"], "endTime").astimezone(
                        zone
                    ) - iso_time(occurrence["endTime"], "endTime").astimezone(zone)
                    patch["endTime"] = format_time(
                        iso_time(series["endTime"], "endTime").astimezone(zone)
                        + delta_end
                    )
            if "recurrence" not in patch and patch.get("startTime"):
                recurrence = dict(series["recurrence"])
                recurrence["exceptions"] = shifted_exceptions(
                    recurrence.get("exceptions", {}), delta, timezone=series["timezone"]
                )
                patch["recurrence"] = recurrence
            updated = normalize_event(
                {**series, **patch},
                revision=series["revision"] + 1,
                updated_at=now_string(),
            )
            raise_if_rejected_conflicts(
                action,
                policy,
                updated,
                expand_events(
                    filter_availability_events(
                        [e for e in events if e["id"] != series["id"]],
                        state["calendars"],
                    ),
                    updated["startTime"],
                    updated["endTime"],
                ),
            )
            state["events"] = [
                updated if e["id"] == series["id"] else e for e in events
            ]
            result = updated
            return state
        recurrence = dict(series["recurrence"])
        exceptions = dict(recurrence.get("exceptions", {}))
        if scope == "future":
            old_rules, future_rules = split_rules(
                series, occurrence["original_start_time"]
            )
            recurrence = {
                "rules": old_rules,
                "exceptions": {
                    k: v
                    for k, v in exceptions.items()
                    if k < occurrence["original_start_time"]
                },
            }
            if action != "delete":
                if len(events) >= MAX_EVENTS:
                    raise ValueError(f"Calendar can store at most {MAX_EVENTS} events.")
                zone = ZoneInfo(series["timezone"])
                delta = iso_time(
                    patch.get("startTime") or occurrence["startTime"], "startTime"
                ).astimezone(zone) - iso_time(
                    occurrence["original_start_time"], "original_start_time"
                ).astimezone(
                    zone
                )
                future_exceptions = shifted_exceptions(
                    exceptions,
                    delta,
                    cut=occurrence["original_start_time"],
                    timezone=series["timezone"],
                )
                first_stamp = format_time(
                    iso_time(
                        occurrence["original_start_time"], "original_start_time"
                    ).astimezone(zone)
                    + delta
                )
                if first_stamp in future_exceptions:
                    future_exceptions[first_stamp] = {
                        k: v
                        for k, v in future_exceptions[first_stamp].items()
                        if k not in patch
                    }
                new_series = normalize_event(
                    {
                        **occurrence,
                        **patch,
                        "recurrence": patch.get("recurrence")
                        or {"rules": future_rules, "exceptions": future_exceptions},
                        "idempotency_key": "",
                    },
                    event_id=f"evt_{uuid4().hex[:12]}",
                    revision=1,
                    created_at=now_string(),
                    updated_at=now_string(),
                )
                raise_if_rejected_conflicts(
                    action,
                    policy,
                    new_series,
                    expand_events(
                        filter_availability_events(
                            [e for e in events if e["id"] != series["id"]],
                            state["calendars"],
                        ),
                        new_series["startTime"],
                        new_series["endTime"],
                    ),
                )
                events.append(new_series)
                result = new_series
        else:
            if action == "delete":
                exceptions[occurrence["original_start_time"]] = {"deleted": True}
                result = occurrence
            else:
                patch.pop("recurrence", None)
                normalized = normalize_event(
                    {**occurrence, **patch}, event_id=series["id"]
                )
                raise_if_rejected_conflicts(
                    action,
                    policy,
                    {**normalized, "id": occurrence["id"]},
                    expand_events(
                        filter_availability_events(events, state["calendars"]),
                        normalized["startTime"],
                        normalized["endTime"],
                    ),
                    ignore_event_id=occurrence["id"],
                )
                exceptions[occurrence["original_start_time"]] = {
                    **exceptions.get(occurrence["original_start_time"], {}),
                    **{k: normalized[k] for k in patch if k in normalized},
                }
            if action != "delete" and any(
                field in patch for field in ("startTime", "endTime")
            ):
                exceptions[occurrence["original_start_time"]].update(
                    startTime=normalized["startTime"], endTime=normalized["endTime"]
                )
            recurrence["exceptions"] = exceptions
        updated = normalize_event(
            {**series, "recurrence": recurrence},
            revision=series["revision"] + 1,
            updated_at=now_string(),
        )
        state["events"] = [updated if e["id"] == series["id"] else e for e in events]
        if action != "delete" and scope == "occurrence":
            result = resolve_occurrence(state["events"], body["id"])
        return state

    update_state(data_root, updater)
    return result
