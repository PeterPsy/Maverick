"""Idempotent phase machine for an execution-authority continuation handoff."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib

from core.recovery.continuation_admission import RuntimeAdmissionAssessment
from core.recovery.continuation_materialization import (
    close_predecessor_runtime_process,
    ensure_successor_session,
    fence_predecessor_and_start_successor,
    quarantine_continuation_successor,
    rebind_logical_thread,
    transfer_provider_state,
)
from core.recovery.continuation_validation import revalidate_continuation_handoff
from core.runtime.continuation_handoff import (
    RuntimeContinuationHandoff,
    continuation_handoff_phase_index,
)
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from core.runtime.execution_binding import canonical_digest
from core.runtime.lifecycle import record_runtime_event
from core.runtime.runtime_session import RuntimeSessionRecord


CONTINUATION_FORK_REASON = "adapter_profile_upgrade"


@dataclass(frozen=True)
class RuntimeContinuationResult:
    """Admission result and current session for one logical conversation."""

    status: str
    session: RuntimeSessionRecord
    assessment: RuntimeAdmissionAssessment
    handoff: RuntimeContinuationHandoff | None = None


def complete_compatible_continuation_fork(
    state,
    *,
    predecessor: RuntimeSessionRecord,
    assessment: RuntimeAdmissionAssessment,
    now: datetime,
) -> RuntimeContinuationResult:
    """Persist a compatibility proof and run its resumable phase machine."""
    target = assessment.target_execution_binding
    if target is None or assessment.compatibility_digest is None:
        raise RuntimeProviderStateError(
            "runtime_continuation_compatibility_proof_missing"
        )
    provider_state = state.runtime_store.get_provider_state(predecessor.session_id)
    handoff = RuntimeContinuationHandoff(
        handoff_id=_handoff_id(predecessor.session_id, target.binding_digest),
        workspace_id=predecessor.workspace_id,
        predecessor_session_id=predecessor.session_id,
        successor_session_id=target.session_id,
        reason_code=CONTINUATION_FORK_REASON,
        source_binding_digest=predecessor.execution_binding.binding_digest,
        source_detail_code=str(
            assessment.detail_code or "runtime_profile_upgrade_required"
        ),
        target_binding_digest=target.binding_digest,
        source_provider_state_revision=provider_state.revision,
        source_provider_state_digest=canonical_digest(provider_state),
        compatible_capabilities=assessment.compatible_capabilities,
        compatibility_digest=assessment.compatibility_digest,
        target_execution_binding=target,
        phase="planned",
        revision=0,
        created_at=now,
        updated_at=now,
    )
    existing = state.runtime_store.get_continuation_handoff_by_predecessor(
        workspace_id=predecessor.workspace_id,
        predecessor_session_id=predecessor.session_id,
    )
    handoff = (
        state.runtime_store.initialize_continuation_handoff(handoff)
        if existing is None
        else existing
    )
    return complete_existing_continuation_handoff(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )


def complete_existing_continuation_handoff(
    state,
    *,
    predecessor: RuntimeSessionRecord,
    handoff: RuntimeContinuationHandoff,
    now: datetime,
) -> RuntimeContinuationResult:
    """Resume any interrupted handoff from its durable phase record."""
    if (
        handoff.predecessor_session_id != predecessor.session_id
        or predecessor.execution_binding is None
        or handoff.source_binding_digest != predecessor.execution_binding.binding_digest
    ):
        raise RuntimeProviderStateError("runtime_continuation_predecessor_conflict")
    _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    assessment = RuntimeAdmissionAssessment(
        status="compatible_upgrade",
        session_id=predecessor.session_id,
        reason_code="runtime_profile_upgrade_compatible",
        detail_code=handoff.source_detail_code,
        target_execution_binding=handoff.target_execution_binding,
        compatible_capabilities=handoff.compatible_capabilities,
        compatibility_digest=handoff.compatibility_digest,
    )
    successor = ensure_successor_session(state, predecessor, handoff)
    handoff = _advance_handoff(state, handoff, "successor_prepared", now=now)
    _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    close_predecessor_runtime_process(state, handoff)
    _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    transfer_provider_state(state, handoff)
    handoff = _advance_handoff(
        state,
        handoff,
        "provider_state_transferred",
        now=now,
    )
    _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    state.runtime_store.link_continuation_successor(
        workspace_id=handoff.workspace_id,
        predecessor_session_id=handoff.predecessor_session_id,
        successor_session_id=handoff.successor_session_id,
        handoff_id=handoff.handoff_id,
        now=now,
    )
    target_executable = _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    fence_predecessor_and_start_successor(
        state,
        handoff,
        start_successor=target_executable,
        now=now,
    )
    handoff = _advance_handoff(state, handoff, "predecessor_fenced", now=now)
    _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    thread = rebind_logical_thread(state, predecessor, successor, now=now)
    handoff = _advance_handoff(state, handoff, "thread_rebound", now=now)
    _revalidate_or_quarantine(
        state,
        predecessor=predecessor,
        handoff=handoff,
        now=now,
    )
    _record_handoff_events(state, handoff, now=now)
    handoff = _advance_handoff(state, handoff, "completed", now=now)
    if thread is not None and getattr(state, "runtime_thread_event_bus", None) is not None:
        state.runtime_thread_event_bus.publish(
            workspace_id=thread.workspace_id,
            event={"action": "updated", "thread_id": thread.thread_id},
        )
    return RuntimeContinuationResult(
        status="forked",
        session=state.runtime_store.get_session(successor.session_id),
        assessment=assessment,
        handoff=handoff,
    )


def _revalidate_or_quarantine(
    state,
    *,
    predecessor: RuntimeSessionRecord,
    handoff: RuntimeContinuationHandoff,
    now: datetime,
) -> bool:
    try:
        return revalidate_continuation_handoff(
            state,
            predecessor=predecessor,
            handoff=handoff,
            now=now,
        )
    except RuntimeProfileUpgradeRequiredError:
        quarantine_continuation_successor(state, handoff)
        raise


def _advance_handoff(state, handoff, phase: str, *, now: datetime):
    current = state.runtime_store.get_continuation_handoff(handoff.handoff_id)
    if continuation_handoff_phase_index(
        current.phase
    ) >= continuation_handoff_phase_index(phase):
        return current
    updated = replace(
        current,
        phase=phase,
        revision=current.revision + 1,
        updated_at=now,
        completed_at=now if phase == "completed" else current.completed_at,
    )
    return state.runtime_store.update_continuation_handoff(
        updated,
        expected_revision=current.revision,
    )


def _record_handoff_events(state, handoff, *, now: datetime) -> None:
    event_bus = getattr(state, "runtime_event_bus", None)
    common = {
        "handoff_id": handoff.handoff_id,
        "reason_code": handoff.reason_code,
        "source_detail_code": handoff.source_detail_code,
        "compatibility_digest": handoff.compatibility_digest,
        "source_binding_digest": handoff.source_binding_digest,
        "target_binding_digest": handoff.target_binding_digest,
        "compatible_capabilities": handoff.compatible_capabilities,
    }
    events = (
        (
            f"{handoff.handoff_id}:predecessor",
            handoff.predecessor_session_id,
            "runtime.continuation.forked",
            {**common, "successor_session_id": handoff.successor_session_id},
        ),
        (
            f"{handoff.handoff_id}:successor",
            handoff.successor_session_id,
            "runtime.continuation.accepted",
            {**common, "predecessor_session_id": handoff.predecessor_session_id},
        ),
    )
    for event_id, session_id, event_type, payload in events:
        if any(
            event.event_id == event_id
            for event in state.runtime_store.list_events(session_id)
        ):
            continue
        record_runtime_event(
            state.runtime_store,
            event_id=event_id,
            session_id=session_id,
            plane="runtime",
            event_type=event_type,
            payload=payload,
            event_bus=event_bus,
            now=now,
        )


def _handoff_id(predecessor_session_id: str, target_binding_digest: str) -> str:
    digest = hashlib.sha256(
        f"{predecessor_session_id}\0{target_binding_digest}".encode("utf-8")
    ).hexdigest()[:24]
    return f"runtime-continuation-{digest}"
