"""Stable runtime event and turn history snapshots."""

from __future__ import annotations

from core.runtime.store import MAX_RUNTIME_EVENTS_PER_SESSION, RuntimeStore
from core.runtime.transcript_models import RuntimeEventHistoryRead, RuntimeTurnHistoryRead


def read_runtime_event_history(
    store: RuntimeStore,
    session_id: str,
    *,
    snapshot_position: int | None = None,
    snapshot_event_id: str | None = None,
) -> RuntimeEventHistoryRead:
    """Load event history bounded by physical append position."""
    pages: list[list] = []
    warnings: list[str] = []
    seen_event_ids: set[str] = set()
    seen_positions: set[int] = set()
    before_position: int | None = None
    captured_position = snapshot_position
    captured_event_id = snapshot_event_id
    complete = True
    while True:
        page = store.list_event_archive_page(
            session_id,
            before_position=before_position,
            snapshot_position=captured_position,
            snapshot_event_id=captured_event_id,
            limit=MAX_RUNTIME_EVENTS_PER_SESSION,
        )
        if not page.snapshot_found:
            warnings.append("snapshot_event_archive_cursor_not_found")
            complete = False
            pages = []
            break
        if captured_position is None:
            captured_position = page.snapshot_position
            captured_event_id = page.snapshot_event_id
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
        next_position = page.oldest_position
        if next_position is None or next_position in seen_positions or not page.events:
            warnings.append("history_archive_cursor_inconsistent")
            complete = False
            break
        seen_positions.add(next_position)
        before_position = next_position
    events = sorted(
        [event for page_events in pages for event in page_events],
        key=lambda item: (item.created_at, item.event_id),
    )
    return RuntimeEventHistoryRead(
        events=events,
        snapshot_position=captured_position if captured_position is not None else -1,
        snapshot_event_id=captured_event_id,
        warnings=warnings,
        complete=complete,
    )


def read_runtime_turn_history(
    store: RuntimeStore,
    session_id: str,
    *,
    snapshot_position: int | None = None,
    snapshot_turn_id: str | None = None,
) -> RuntimeTurnHistoryRead:
    """Bound immutable turn-input fallbacks by record append position."""
    turns = store.list_turns(session_id)
    resolved_position = len(turns) - 1 if snapshot_position is None else int(snapshot_position)
    if resolved_position == -1:
        return RuntimeTurnHistoryRead(
            turns=[],
            snapshot_position=-1,
            snapshot_turn_id=None,
            warnings=[],
            complete=True,
        )
    if resolved_position < 0 or resolved_position >= len(turns):
        return _missing_turn_snapshot(resolved_position, snapshot_turn_id)
    resolved_turn_id = turns[resolved_position].turn_id
    if snapshot_position is not None and resolved_turn_id != str(snapshot_turn_id or "").strip():
        return _missing_turn_snapshot(resolved_position, snapshot_turn_id)
    return RuntimeTurnHistoryRead(
        turns=turns[: resolved_position + 1],
        snapshot_position=resolved_position,
        snapshot_turn_id=resolved_turn_id,
        warnings=[],
        complete=True,
    )


def _missing_turn_snapshot(position: int, turn_id: str | None) -> RuntimeTurnHistoryRead:
    return RuntimeTurnHistoryRead(
        turns=[],
        snapshot_position=position,
        snapshot_turn_id=turn_id,
        warnings=["snapshot_turn_archive_cursor_not_found"],
        complete=False,
    )
