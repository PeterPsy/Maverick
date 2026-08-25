"""Admission rules for queuing work on runtime sessions."""

from __future__ import annotations

from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore


def require_turn_queue_session_executable(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> None:
    """Reject turns whose session is stopped or has transferred ownership."""
    handoff = store.get_continuation_handoff_by_predecessor(
        workspace_id=session.workspace_id,
        predecessor_session_id=session.session_id,
    )
    if handoff is not None:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn on superseded session `{session.session_id}`."
        )
    if session.status not in {"created", "running"}:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` is {session.status}."
        )
