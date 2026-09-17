"""Runtime-session helpers retained for callers that operate on one session."""

from __future__ import annotations

from core.runtime.runtime_events import RuntimeEventRecord
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.store import RuntimeStore


def resolve_latest_runtime_session(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> RuntimeSessionRecord:
    """Return the persisted session; automatic successor forks are not used."""
    return store.get_session(session.session_id)


def runtime_session_lineage(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> list[RuntimeSessionRecord]:
    """Return the single persisted session."""
    return [store.get_session(session.session_id)]


def runtime_lineage_events(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> list[RuntimeEventRecord]:
    return store.list_events(session.session_id)


def runtime_lineage_turns(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> list[RuntimeTurnRecord]:
    return store.list_turns(session.session_id)
