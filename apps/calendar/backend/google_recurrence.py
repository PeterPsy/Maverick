"""Google series and occurrence edits, including split-at-occurrence semantics."""

from __future__ import annotations
from google_event_mapping import google_event_payload
from google_mutations import (
    _connection_and_calendar,
    _ensure_writable_calendar,
    _google_event_body,
    _remote_ref,
)
from google_oauth import CalendarOAuthError
from google_provider import (
    get_event,
    event_instance,
    patch_event,
    delete_event,
    insert_event,
    refresh_access_token,
    transfer_event,
)
from operations import (
    get_event as local_event,
    _check_expected_revision,
    move_event_payload,
)
from event_records import normalize_event
from recurrence_rules import split_rules
from store import update_state, read_state
from google_series_mirror import (
    belongs as _belongs,
    mirror_series as _mirror_series,
    original_start as _original_start,
    series_exceptions,
)
from availability import raise_if_rejected_conflicts
from calendar_visibility import filter_availability_events
from recurrence import expand_events, shifted_exceptions
from request_inputs import conflict_policy_from_body
from time_values import format_time, iso_time
from zoneinfo import ZoneInfo


def mutate_google_occurrence(
    data_root, body, action, secrets, secret_errors, transport
):
    baseline = read_state(data_root)
    current = local_event(data_root, body["id"])
    _check_expected_revision(action, current, body.get("expected_revision"))
    ref = _remote_ref(current)
    connection, calendar = _connection_and_calendar(
        data_root, ref, fallback_event=current
    )
    _ensure_writable_calendar(calendar, operation=action)
    token = refresh_access_token(
        app_secrets=secrets, app_secret_errors=secret_errors, transport=transport
    )
    series_remote_id = (
        current["external_refs"].get("recurring_event_id") or ref["provider_event_id"]
    )
    remote_master = get_event(
        access_token=token,
        calendar_id=ref["provider_calendar_id"],
        event_id=series_remote_id,
        transport=transport,
    )
    master = normalize_event(
        google_event_payload(remote_master, connection=connection, calendar=calendar),
        event_id=current.get("series_id") or current["id"],
    )
    scope = body.get("recurrence_scope", "occurrence")
    if not current.get("series_id") and not current["external_refs"].get(
        "recurring_event_id"
    ):
        scope = "series"
    patch = dict(body.get("event") or {})
    requested_refs = patch.get("external_refs") or {}
    patch.pop("id", None)
    patch.pop("idempotency_key", None)
    patch.pop("external_refs", None)
    if patch.get("recurrence") == current.get("recurrence"):
        patch.pop("recurrence", None)
    if action == "move":
        patch.update(move_event_payload(data_root, body["id"], body))
    if scope not in {"occurrence", "future", "series"}:
        raise ValueError("recurrence_scope must be occurrence, future or series.")
    if scope == "future" and _original_start(current) == master["startTime"]:
        scope = "series"
    if scope == "series":
        zone = ZoneInfo(master["timezone"])
        for field in ("startTime", "endTime"):
            if patch.get(field):
                delta = iso_time(patch[field], field).astimezone(zone) - iso_time(
                    current[field], field
                ).astimezone(zone)
                patch[field] = format_time(
                    iso_time(master[field], field).astimezone(zone) + delta
                )
    if patch.get("source") == "calendar":
        raise ValueError(
            "Google recurring events must remain on their Google calendar."
        )
    requested_calendar = requested_refs.get("provider_calendar_id")
    requested_connection = requested_refs.get("calendar_connection_id")
    if requested_connection and requested_connection != ref["calendar_connection_id"]:
        raise ValueError(
            "Transfers require a destination within the same connected account."
        )
    if requested_calendar and requested_calendar != ref["provider_calendar_id"]:
        if scope != "series":
            raise ValueError("Select entire series to transfer a recurring event.")
        if not any(
            c["connection_id"] == ref["calendar_connection_id"]
            and c["provider_calendar_id"] == requested_calendar
            for c in baseline["calendars"]
        ):
            raise ValueError(
                "Destination calendar must be known and have verified write permissions."
            )
        destination_ref = {**ref, "provider_calendar_id": requested_calendar}
        _, destination = _connection_and_calendar(
            data_root, destination_ref, fallback_event=current
        )
        _ensure_writable_calendar(destination, operation="transfer")
        moved = transfer_event(
            access_token=token,
            calendar_id=ref["provider_calendar_id"],
            event_id=series_remote_id,
            destination=requested_calendar,
            transport=transport,
        )
        current = _mirror_series(
            data_root,
            master,
            moved,
            connection,
            destination,
            series_remote_id,
            current,
            baseline["events"],
        )
        master = current
        baseline = read_state(data_root)
        calendar = destination
        ref = _remote_ref(current)
        series_remote_id = ref["provider_event_id"]
        remote_master = moved
    remote_id = series_remote_id
    if scope == "occurrence":
        # Full-history occurrences are virtual; obtain the provider instance id.
        original = current["original_start_time"]
        remote = event_instance(
            access_token=token,
            calendar_id=ref["provider_calendar_id"],
            series_id=series_remote_id,
            original_start=original,
            transport=transport,
        )
        if not remote:
            raise CalendarOAuthError(
                "calendar_occurrence_not_found",
                "Google occurrence was not found.",
                status_code=404,
            )
        remote_id = remote["id"]
        candidate = normalize_event(
            {**current, **patch, "recurrence": {}}, event_id=master["id"]
        )
    else:
        candidate = normalize_event({**master, **patch}, event_id=master["id"])
    if action != "delete":
        other_events = [
            e for e in baseline["events"] if not _belongs(e, ref, series_remote_id)
        ]
        raise_if_rejected_conflicts(
            action,
            conflict_policy_from_body(body),
            candidate,
            expand_events(
                filter_availability_events(other_events, baseline["calendars"]),
                candidate["startTime"],
                candidate["endTime"],
            ),
        )
    if scope == "future":
        original_value = _original_start(current)
        old, future = split_rules(master, original_value)
        zone = ZoneInfo(master["timezone"])
        delta = iso_time(
            patch.get("startTime") or current["startTime"], "startTime"
        ).astimezone(zone) - iso_time(original_value, "original").astimezone(zone)
        exceptions = shifted_exceptions(
            series_exceptions(baseline["events"], master, ref, series_remote_id),
            delta,
            cut=original_value,
            timezone=master["timezone"],
        )
        candidate = normalize_event(
            {
                **current,
                **patch,
                "external_refs": master["external_refs"],
                "recurrence": patch.get("recurrence")
                or {"rules": future, "exceptions": exceptions},
            },
            event_id=master["id"],
        )
        trimmed = patch_event(
            access_token=token,
            calendar_id=ref["provider_calendar_id"],
            event_id=series_remote_id,
            event={"recurrence": old},
            etag=remote_master.get("etag", ""),
            transport=transport,
        )
        # Mirror the first accepted operation before attempting the second.
        _mirror_series(
            data_root,
            master,
            trimmed,
            connection,
            calendar,
            series_remote_id,
            current,
            baseline["events"],
            cut=original_value,
        )
        if action == "delete":
            return current
        remote = insert_event(
            access_token=token,
            calendar_id=ref["provider_calendar_id"],
            event=_google_event_body(candidate),
            transport=transport,
        )
        from uuid import uuid4

        candidate["id"] = f"evt_{uuid4().hex[:12]}"
        result = _mirror_series(
            data_root,
            candidate,
            remote,
            connection,
            calendar,
            remote["id"],
            current,
            [],
            exceptions=exceptions,
        )
        _copy_exceptions(
            token,
            ref["provider_calendar_id"],
            remote["id"],
            candidate,
            exceptions,
            transport,
        )
        return result
    if action == "delete":
        delete_event(
            access_token=token,
            calendar_id=ref["provider_calendar_id"],
            event_id=remote_id,
            transport=transport,
        )
        if scope == "series":

            def remove(state):
                state["events"] = [
                    e for e in state["events"] if not _belongs(e, ref, series_remote_id)
                ]
                return state

            update_state(data_root, remove)
        else:
            from recurrence_mutations import mutate_occurrence

            mutate_occurrence(
                data_root, body, action, "allow", body.get("expected_revision")
            )
        return current
    remote_body = _google_event_body(candidate)
    if scope == "occurrence":
        remote_body.pop("recurrence", None)
    remote = patch_event(
        access_token=token,
        calendar_id=ref["provider_calendar_id"],
        event_id=remote_id,
        event=remote_body,
        etag=(
            remote_master.get("etag", "")
            if scope == "series"
            else remote.get("etag", "")
        ),
        transport=transport,
    )
    if scope == "series":
        return _mirror_series(
            data_root,
            master,
            remote,
            connection,
            calendar,
            series_remote_id,
            current,
            baseline["events"],
        )
    # Apply an exception to the master so bounded reads immediately reflect it.
    from recurrence_mutations import mutate_occurrence

    accepted = google_event_payload(remote, connection=connection, calendar=calendar)
    exception_patch = {key: accepted[key] for key in patch if key in accepted}
    exception_patch.update(startTime=accepted["startTime"], endTime=accepted["endTime"])
    return mutate_occurrence(
        data_root,
        {**body, "event": exception_patch},
        action,
        "allow",
        body.get("expected_revision"),
    )


def _copy_exceptions(token, calendar_id, series_id, master, exceptions, transport):
    # Splitting creates a new provider series; explicitly migrate its exceptions.
    for stamp, patch in exceptions.items():
        instance = event_instance(
            access_token=token,
            calendar_id=calendar_id,
            series_id=series_id,
            original_start=stamp,
            transport=transport,
        )
        if not instance:
            continue  # The updated rule may exclude this occurrence.
        if patch.get("deleted"):
            delete_event(
                access_token=token,
                calendar_id=calendar_id,
                event_id=instance["id"],
                transport=transport,
            )
            continue
        payload = normalize_event(
            {
                **master,
                **patch,
                "startTime": patch.get("startTime") or stamp,
                "endTime": patch.get("endTime")
                or format_time(
                    iso_time(stamp, "original")
                    + (
                        iso_time(master["endTime"], "endTime")
                        - iso_time(master["startTime"], "startTime")
                    )
                ),
            },
            event_id=master["id"],
        )
        body = _google_event_body(payload)
        body.pop("recurrence", None)
        patch_event(
            access_token=token,
            calendar_id=calendar_id,
            event_id=instance["id"],
            event=body,
            etag=instance.get("etag", ""),
            transport=transport,
        )
