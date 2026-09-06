"""Admission rules for queuing work on runtime sessions."""

from __future__ import annotations

from core.runtime.errors import RuntimeTurnQueueRejectedError
from core.runtime.provider_step_admission import provider_step_admission_reason
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeStore
from core.runtime.remote_agentic_admission import remote_agentic_containment_reason


def require_turn_queue_session_executable(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
    *,
    turn_id: str | None = None,
    workspace_store: object | None = None,
    lab_authorization=None,
) -> None:
    """Reject turns whose session is stopped or has transferred ownership."""
    if session.status == "recovery_required":
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` requires recovery.",
            reason_code="runtime_session_recovery_required",
        )
    if lab_authorization is not None:
        from core.certification_lab.authority import LabRuntimeAuthorization

        if type(lab_authorization) is not LabRuntimeAuthorization or lab_authorization.runtime_store is not store:
            raise RuntimeTurnQueueRejectedError("Invalid lab context.", reason_code="lab_trusted_context_invalid")
        lab_authorization.validate_session(session)
        containment_reason = None
    else:
        containment_reason = remote_agentic_containment_reason(
            session.execution_binding, workspace_id=session.workspace_id,
            workspace_store=workspace_store,
        )
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
    persisted = store.get_session(session.session_id)
    if (
        persisted.workspace_id != session.workspace_id
        or persisted.execution_binding != session.execution_binding
        or persisted.owner_user_id != session.owner_user_id
        or persisted.created_by_user_id != session.created_by_user_id
    ):
        raise RuntimeTurnQueueRejectedError(
            "Cannot queue a runtime turn for a mismatched persisted session.",
            reason_code="runtime_session_not_executable",
        )
    if persisted.status == "recovery_required":
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` requires recovery.",
            reason_code="runtime_session_recovery_required",
        )
    if persisted.status not in {"created", "running"}:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` is {persisted.status}.",
            reason_code="runtime_session_not_executable",
        )
    journal_reason = provider_step_admission_reason(
        store,
        session_id=session.session_id,
        turn_id=turn_id,
        allow_same_turn_pairing=False,
    )
    if journal_reason is not None:
        raise RuntimeTurnQueueRejectedError(
            f"Cannot queue a runtime turn while session `{session.session_id}` has unresolved provider state.",
            reason_code=journal_reason,
        )
