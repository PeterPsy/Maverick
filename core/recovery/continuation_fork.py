"""Direct continuation admission without automatic profile migrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from core.recovery.continuation_admission import (
    RuntimeAdmissionAssessment,
    assess_runtime_session_admission,
)
from core.runtime.continuation_lineage import resolve_latest_runtime_session
from core.runtime.errors import RuntimeProfileUpgradeRequiredError
from core.runtime.hosted_agentic_lifecycle import recover_hosted_agentic_session
from core.runtime.runtime_session import RuntimeSessionRecord


@dataclass(frozen=True)
class RuntimeContinuationResult:
    """A directly admitted current runtime session."""

    status: str
    session: RuntimeSessionRecord
    assessment: RuntimeAdmissionAssessment
    handoff: None = None


def admit_runtime_session(
    state,
    *,
    session: RuntimeSessionRecord,
    allow_compatible_fork: bool = True,
    provider_pairing_source_turn_id: str | None = None,
    now: datetime | None = None,
) -> RuntimeContinuationResult:
    """Admit the latest persisted session without rewriting its configuration."""
    del allow_compatible_fork
    timestamp = now or datetime.now(tz=UTC)
    if session.status == "recovery_required":
        raise RuntimeProfileUpgradeRequiredError(
            "runtime_session_restart_required",
            detail_code=session.recovery_reason_code or "runtime_state_ambiguous",
        )
    if provider_pairing_source_turn_id is None:
        recovery = recover_hosted_agentic_session(
            state, session=session, trigger="pre_admission"
        )
        if recovery.applicable and not recovery.recovered:
            raise RuntimeProfileUpgradeRequiredError(
                "runtime_session_restart_required",
                detail_code=recovery.reason_code,
            )
    current = resolve_latest_runtime_session(state.runtime_store, session)
    assessment = assess_runtime_session_admission(
        state.provider_store,
        state.runtime_store,
        state.provider_registry,
        session=current,
        provider_pairing_source_turn_id=provider_pairing_source_turn_id,
        now=timestamp,
        workspace_store=getattr(state, "workspace_store", None),
    )
    if assessment.status != "direct":
        raise RuntimeProfileUpgradeRequiredError(
            assessment.reason_code or "runtime_session_restart_required",
            detail_code=assessment.detail_code,
        )
    return RuntimeContinuationResult("direct", current, assessment)


def continuation_repair_inventory(
    state,
    *,
    workspace_id: str | None = None,
    session_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Report sessions that are usable or require an explicit restart."""
    timestamp = now or datetime.now(tz=UTC)
    inventory: list[dict[str, object]] = []
    for session in state.runtime_store.list_sessions(workspace_id):
        if session_ids is not None and session.session_id not in session_ids:
            continue
        assessment = assess_runtime_session_admission(
            state.provider_store,
            state.runtime_store,
            state.provider_registry,
            session=session,
            now=timestamp,
            workspace_store=getattr(state, "workspace_store", None),
        )
        inventory.append({
            "session_id": session.session_id,
            "workspace_id": session.workspace_id,
            "status": assessment.status,
            "reason_code": assessment.reason_code,
            "detail_code": assessment.detail_code,
            "model_id": None if session.execution_binding is None else session.execution_binding.model_id,
        })
    return inventory


def repair_compatible_runtime_continuations(
    state,
    *,
    workspace_id: str | None = None,
    session_ids: set[str] | None = None,
    expected_session_ids: set[str] | None = None,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, object]:
    """Retained operator command: report only; automatic repair was removed."""
    inventory = continuation_repair_inventory(
        state,
        workspace_id=workspace_id,
        session_ids=session_ids,
        now=now,
    )
    actual = {str(item["session_id"]) for item in inventory}
    if expected_session_ids is not None and actual != expected_session_ids:
        raise ValueError("runtime_continuation_repair_scope_mismatch")
    return {
        "dry_run": dry_run,
        "items": inventory,
        "counts": {
            "direct": sum(item["status"] == "direct" for item in inventory),
            "restart_required": sum(item["status"] != "direct" for item in inventory),
            "repaired": 0,
        },
    }


def continuation_state(state, session: RuntimeSessionRecord) -> dict[str, object]:
    current = resolve_latest_runtime_session(state.runtime_store, session)
    return {
        "status": "direct",
        "session_id": current.session_id,
    }
