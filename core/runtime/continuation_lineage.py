"""Runtime-session lineage traversal for continuation forks."""

from __future__ import annotations

from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeStore


MAX_CONTINUATION_LINEAGE_DEPTH = 32


def resolve_latest_runtime_session(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> RuntimeSessionRecord:
    """Follow audited successor pointers to the current executable session."""
    current = session
    visited = {current.session_id}
    for _depth in range(MAX_CONTINUATION_LINEAGE_DEPTH):
        successor_id = str(
            getattr(current, "continuation_successor_session_id", None) or ""
        ).strip()
        if not successor_id:
            return current
        if successor_id in visited:
            raise ValueError("Runtime continuation lineage contains a cycle.")
        successor = store.get_session(successor_id)
        if successor.workspace_id != session.workspace_id:
            raise ValueError("Runtime continuation lineage crosses workspace boundaries.")
        if getattr(successor, "predecessor_session_id", None) != current.session_id:
            raise ValueError("Runtime continuation lineage successor is inconsistent.")
        visited.add(successor_id)
        current = successor
    raise ValueError("Runtime continuation lineage exceeds the supported depth.")


def runtime_session_lineage(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> list[RuntimeSessionRecord]:
    """Return the predecessor chain in chronological order through `session`."""
    lineage = [session]
    visited = {session.session_id}
    current = session
    for _depth in range(MAX_CONTINUATION_LINEAGE_DEPTH):
        predecessor_id = str(
            getattr(current, "predecessor_session_id", None) or ""
        ).strip()
        if not predecessor_id:
            lineage.reverse()
            return lineage
        if predecessor_id in visited:
            raise ValueError("Runtime continuation lineage contains a cycle.")
        try:
            predecessor = store.get_session(predecessor_id)
        except RuntimeSessionNotFoundError as error:
            raise ValueError("Runtime continuation predecessor is missing.") from error
        if predecessor.workspace_id != session.workspace_id:
            raise ValueError("Runtime continuation lineage crosses workspace boundaries.")
        if (
            getattr(predecessor, "continuation_successor_session_id", None)
            != current.session_id
        ):
            raise ValueError("Runtime continuation lineage predecessor is inconsistent.")
        lineage.append(predecessor)
        visited.add(predecessor_id)
        current = predecessor
    raise ValueError("Runtime continuation lineage exceeds the supported depth.")


def runtime_lineage_events(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> list[RuntimeEventRecord]:
    """Return immutable events from every session in one logical conversation."""
    events = [
        event
        for item in runtime_session_lineage(store, session)
        for event in store.list_events(item.session_id)
    ]
    return sorted(events, key=lambda event: (event.created_at, event.event_id))


def runtime_lineage_turns(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> list[RuntimeTurnRecord]:
    """Return immutable turns from every session in one logical conversation."""
    turns = [
        turn
        for item in runtime_session_lineage(store, session)
        for turn in store.list_turns(item.session_id)
    ]
    return sorted(turns, key=lambda turn: (turn.created_at, turn.turn_id))
