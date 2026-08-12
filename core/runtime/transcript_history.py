"""Complete runtime event-history reads through the paged store contract."""

from __future__ import annotations

from core.runtime.store import MAX_RUNTIME_EVENTS_PER_SESSION, RuntimeStore
from core.runtime.transcript_models import RuntimeEventHistoryRead


def read_runtime_event_history(
    store: RuntimeStore,
    session_id: str,
    *,
    snapshot_newest_event_id: str | None = None,
) -> RuntimeEventHistoryRead:
    """Load complete ordered history using only ``list_event_page``."""
    pages: list[list] = []
    warnings: list[str] = []
    seen_event_ids: set[str] = set()
    seen_cursors: set[str] = set()
    before_event_id: str | None = None
    captured_newest_event_id: str | None = None
    complete = True
    while True:
        page = store.list_event_page(
            session_id,
            before_event_id=before_event_id,
            limit=MAX_RUNTIME_EVENTS_PER_SESSION,
        )
        if captured_newest_event_id is None:
            captured_newest_event_id = page.newest_event_id
        unique_events = []
        for event in page.events:
            if event.event_id in seen_event_ids:
                warnings.append(f"duplicate_history_event:{event.event_id}")
                complete = False
                continue
            seen_event_ids.add(event.event_id)
            unique_events.append(event)
        pages.append(unique_events)
        if not page.has_more_before:
            break
        next_cursor = page.oldest_event_id
        if not next_cursor or next_cursor in seen_cursors or not page.events:
            warnings.append("history_archive_cursor_inconsistent")
            complete = False
            break
        seen_cursors.add(next_cursor)
        before_event_id = next_cursor
    events = sorted(
        [event for page_events in pages for event in page_events],
        key=lambda item: (item.created_at, item.event_id),
    )
    requested_snapshot = str(snapshot_newest_event_id or "").strip()
    if requested_snapshot:
        snapshot_index = next((index for index, event in enumerate(events) if event.event_id == requested_snapshot), None)
        if snapshot_index is None:
            warnings.append("snapshot_newest_event_not_found")
            complete = False
            events = []
        else:
            events = events[: snapshot_index + 1]
            captured_newest_event_id = requested_snapshot
    return RuntimeEventHistoryRead(
        events=events,
        snapshot_newest_event_id=captured_newest_event_id,
        warnings=warnings,
        complete=complete,
    )
