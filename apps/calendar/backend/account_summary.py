"""Compact account tree metadata, counts and redaction-safe freshness diagnostics."""

from datetime import UTC, datetime
from google_calendars import list_calendars
from google_oauth import list_connections
from store import read_state
from time_values import iso_time


def account_summary(data_root):
    state = read_state(data_root)
    connections = list_connections(data_root)["connections"]
    counts = {"calendar": 0}
    for event in state["events"]:
        connection = (event.get("external_refs") or {}).get(
            "calendar_connection_id"
        ) or "calendar"
        counts[connection] = counts.get(connection, 0) + 1
    now = datetime.now(UTC)
    for connection in connections:
        cursors = [
            c for c in state["sync_state"] if c["connection_id"] == connection["id"]
        ]
        connection["event_count"] = counts.get(connection["id"], 0)
        last = connection.get("last_sync_at")
        connection["sync_status"] = {
            "status": (
                "error"
                if any(c["status"] == "error" for c in cursors)
                else (
                    "partial"
                    if any(c["status"] == "partial" for c in cursors)
                    else "ok" if last else "idle"
                )
            ),
            "last_sync_at": last or "",
            "stale": not last
            or (now - iso_time(last, "last_sync_at")).total_seconds() > 900,
            "error": next((c["error"] for c in cursors if c["error"]), ""),
        }
    return {
        "action": "calendar_accounts.summary",
        "connections": connections,
        "calendars": list_calendars(data_root)["calendars"],
        "local_event_count": counts["calendar"],
    }
