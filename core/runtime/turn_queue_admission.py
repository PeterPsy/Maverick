"""Admission rules for queuing work on runtime sessions."""

from __future__ import annotations

from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore
from core.runtime.remote_agentic_admission import remote_agentic_containment_reason


def require_turn_queue_session_executable(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
) -> None:
    """Reject turns whose session is stopped or has transferred ownership."""
    if session.status == "recovery_required":
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` requires recovery.",
            reason_code="runtime_session_recovery_required",
        )
    containment_reason = remote_agentic_containment_reason(session.execution_binding)
    if containment_reason is not None:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` is remotely contained.",
            reason_code="remote_agentic_session_contained",
        )
    handoff = store.get_continuation_handoff_by_predecessor(
        workspace_id=session.workspace_id,
        predecessor_session_id=session.session_id,
    )
    if handoff is not None:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn on superseded session `{session.session_id}`.",
            reason_code="runtime_session_superseded",
        )
    if session.status not in {"created", "running"}:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` is {session.status}.",
            reason_code="runtime_session_not_executable",
        )
