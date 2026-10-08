"""Google future-series splitting, replay protection and recovery after failure."""

import hashlib
from zoneinfo import ZoneInfo
from event_records import normalize_event
from google_mutations import _google_event_body, _remote_ref
from google_oauth import CalendarOAuthError
from google_provider import (
    insert_event,
    get_event,
    patch_event,
    delete_event,
    event_instance,
)
from google_series_mirror import (
    mirror_series as _mirror_series,
    original_start as _original_start,
    series_exceptions,
)
from recurrence import shifted_exceptions
from recurrence_rules import split_rules
from store import read_state
from time_values import iso_time, format_time


def split_google_series(
    data_root,
    *,
    master,
    current,
    patch,
    connection,
    calendar,
    token,
    action,
    transport,
    baseline,
    remote_master,
):
    ref = _remote_ref(current)
    series_remote_id = (
        current["external_refs"].get("recurring_event_id") or ref["provider_event_id"]
    )
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
    trimmed_local = _mirror_series(
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
    successor_body = _google_event_body(candidate)
    successor_body["id"] = hashlib.sha256(
        (series_remote_id + ":" + original_value).encode()
    ).hexdigest()
    try:
        remote = insert_event(
            access_token=token,
            calendar_id=ref["provider_calendar_id"],
            event=successor_body,
            transport=transport,
        )
    except CalendarOAuthError as insert_error:
        try:
            # A successful insert with a lost response must not create a second series.
            remote = get_event(
                access_token=token,
                calendar_id=ref["provider_calendar_id"],
                event_id=successor_body["id"],
                transport=transport,
            )
        except CalendarOAuthError as lookup_error:
            if lookup_error.code != "google_calendar_event_not_found":
                raise CalendarOAuthError(
                    "google_series_split_partial",
                    "The previous series was trimmed; successor creation could not be confirmed. Sync Google before retrying.",
                    status_code=502,
                    extra={
                        "completed_step": "trim_series",
                        "successor_provider_id": successor_body["id"],
                    },
                ) from insert_error
            try:
                restored = patch_event(
                    access_token=token,
                    calendar_id=ref["provider_calendar_id"],
                    event_id=series_remote_id,
                    event={"recurrence": remote_master["recurrence"]},
                    etag=trimmed.get("etag", ""),
                    transport=transport,
                )
                _mirror_series(
                    data_root,
                    master,
                    restored,
                    connection,
                    calendar,
                    series_remote_id,
                    trimmed_local,
                    read_state(data_root)["events"],
                    exceptions=series_exceptions(
                        baseline["events"], master, ref, series_remote_id
                    ),
                )
            except CalendarOAuthError as restore_error:
                raise CalendarOAuthError(
                    "google_series_split_partial",
                    "Successor creation and restoration failed. The trimmed series is preserved locally; sync Google and review the series.",
                    status_code=502,
                    extra={"completed_step": "trim_series"},
                ) from restore_error
            raise CalendarOAuthError(
                "google_series_split_failed",
                "Google could not create the successor. The original series has been restored; your draft is kept.",
                status_code=502,
            ) from insert_error
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
