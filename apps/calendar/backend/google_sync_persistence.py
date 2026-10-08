"""Atomic reconciliation of fetched Google batches and continuation checkpoints."""

from constants import MAX_EVENTS
from google_event_mapping import google_event_payload
from google_oauth import CalendarOAuthError
from google_records import normalize_sync_cursor
from google_reconciliation import _merge_remote_events
from google_sync_fetch import _replace_connection_calendars
from google_sync_state import (
    _connected_google_connection,
    _sync_cursor_for,
    _remote_calendar_event,
    _upsert_cursor,
    _mark_capacity_error,
    _mark_connection_synced,
)
from store import update_state
from time_values import format_time

SYNC_MODE_FULL_HISTORY = "full_history"


def persist_sync(
    data_root,
    state,
    connection,
    current_time,
    batches,
    targets,
    calendars_payload,
    page_size,
):
    connection_id = connection["id"]
    results = []
    capacity_error = None

    def reconcile(latest):
        nonlocal capacity_error
        _connected_google_connection(latest, connection_id)
        events = latest["events"]
        cursors = list(latest["sync_state"])
        for (
            calendar,
            baseline_cursor,
            mode,
            time_min,
            time_max,
            sync_token,
            items,
            token,
            pages,
            page_token,
            resume,
        ) in batches:
            cursor = _sync_cursor_for(
                cursors,
                connection_id=connection_id,
                provider_calendar_id=calendar["provider_calendar_id"],
            )
            if cursor != baseline_cursor:
                results.append(
                    {
                        "calendar_id": calendar["id"],
                        "status": "partial",
                        "conflicts": ["concurrent_sync"],
                        "truncated": False,
                    }
                )
                continue
            versions = dict(cursor.get("reconcile_versions", {})) if resume else {}
            baseline_events = state["events"]
            if resume and versions:
                baseline_events = [
                    e
                    for e in state["events"]
                    if not _remote_calendar_event(
                        e, connection_id, calendar["provider_calendar_id"]
                    )
                    or versions.get(
                        (e.get("external_refs") or {}).get("provider_event_id")
                    )
                    == [e["id"], e["revision"]]
                ]
                current_ids = {e["id"] for e in state["events"]}
                baseline_events += [
                    {
                        "id": local_id,
                        "revision": revision,
                        "external_refs": {
                            "calendar_connection_id": connection_id,
                            "provider_calendar_id": calendar["provider_calendar_id"],
                            "provider_event_id": remote_id,
                        },
                    }
                    for remote_id, (local_id, revision) in versions.items()
                    if local_id not in current_ids
                ]
            merge = _merge_remote_events(
                events,
                connection=connection,
                calendar=calendar,
                remote_events=items,
                full_sync=not sync_token and not page_token,
                stale_time_min=time_min,
                stale_time_max=time_max,
                now=current_time,
                baseline=baseline_events,
                seen_remote_ids=set(
                    cursor.get("seen_remote_ids", []) if resume else []
                ),
                mapper=google_event_payload,
            )
            if not resume:
                versions = {
                    (e.get("external_refs") or {})["provider_event_id"]: [
                        e["id"],
                        e["revision"],
                    ]
                    for e in baseline_events
                    if _remote_calendar_event(
                        e, connection_id, calendar["provider_calendar_id"]
                    )
                }
            for e in merge["events"]:
                if (
                    _remote_calendar_event(
                        e, connection_id, calendar["provider_calendar_id"]
                    )
                    and e["id"] not in merge["conflicts"]
                ):
                    remote_id = e["external_refs"]["provider_event_id"]
                    if remote_id in merge["seen_remote_ids"]:
                        versions[remote_id] = [e["id"], e["revision"]]
            events = merge["events"]
            complete = not page_token and not merge["conflicts"]
            next_cursor = normalize_sync_cursor(
                {
                    **cursor,
                    "calendar_id": calendar["id"],
                    "status": "ok" if complete else "partial",
                    "sync_mode": mode,
                    "page_size": baseline_cursor["page_size"] if resume else page_size,
                    "sync_token": (
                        (token if mode == SYNC_MODE_FULL_HISTORY else "")
                        if complete
                        else sync_token
                    ),
                    "page_token": page_token,
                    "reconcile_versions": versions if page_token else {},
                    "seen_remote_ids": merge["seen_remote_ids"] if page_token else [],
                    "time_min": time_min,
                    "time_max": time_max,
                    "last_sync_at": (
                        format_time(current_time)
                        if complete
                        else cursor["last_sync_at"]
                    ),
                    "last_full_sync_at": (
                        format_time(current_time)
                        if complete and not sync_token
                        else cursor["last_full_sync_at"]
                    ),
                    "updated_at": format_time(current_time),
                    "error_code": (
                        "calendar_sync_revision_conflict"
                        if merge["conflicts"]
                        else "calendar_sync_page_limit" if page_token else ""
                    ),
                    "error": (
                        "Concurrent event changes preserved; retry sync."
                        if merge["conflicts"]
                        else "More pages remain; continue sync." if page_token else ""
                    ),
                }
            )
            cursors = _upsert_cursor(cursors, next_cursor)
            results.append(
                {
                    "calendar_id": calendar["id"],
                    "provider_calendar_id": calendar["provider_calendar_id"],
                    "full_sync": not sync_token,
                    "pages": pages,
                    "truncated": bool(page_token),
                    "status": next_cursor["status"],
                    "conflicts": merge["conflicts"],
                    **{
                        key: merge[key]
                        for key in ("created", "updated", "deleted", "unchanged")
                    },
                    "sync_mode": mode,
                    "time_min": time_min,
                    "time_max": time_max,
                    "sync_token_updated": bool(
                        complete and token and mode == SYNC_MODE_FULL_HISTORY
                    ),
                }
            )
        latest["calendars"] = _replace_connection_calendars(
            latest["calendars"], connection_id, calendars_payload
        )
        if len(events) > MAX_EVENTS:
            capacity_error = {
                "current_event_count": len(latest["events"]),
                "remote_candidate_count": sum(len(b[6]) for b in batches),
                "candidate_event_count": len(events),
                "max_events": MAX_EVENTS,
            }
            latest["sync_state"] = _mark_capacity_error(
                latest["sync_state"],
                targets,
                connection_id=connection_id,
                updated_at=format_time(current_time),
                **capacity_error,
            )
            return latest
        latest["events"] = events
        latest["sync_state"] = cursors
        if all(r["status"] == "ok" for r in results):
            latest["connections"] = _mark_connection_synced(
                latest["connections"],
                connection_id,
                synced_at=format_time(current_time),
            )
        return latest

    update_state(data_root, reconcile)
    if capacity_error:
        raise CalendarOAuthError(
            "calendar_sync_event_limit",
            f"Calendar sync would exceed the {MAX_EVENTS} event limit.",
            extra=capacity_error,
        )
    return results
