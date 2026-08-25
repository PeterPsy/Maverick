"""Idempotent continuation forks for sessions with obsolete runtime authority."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from core.recovery.continuation_admission import (
    RuntimeAdmissionAssessment,
    assess_runtime_session_admission,
    runtime_session_has_nonterminal_turns,
)
from core.recovery.continuation_handoff_service import (
    RuntimeContinuationResult,
    complete_compatible_continuation_fork,
    complete_existing_continuation_handoff,
)
from core.recovery.continuation_validation import revalidate_continuation_handoff
from core.runtime.continuation_lineage import resolve_latest_runtime_session
from core.runtime.errors import (
    RuntimeProfileUpgradeRequiredError,
    RuntimeProviderStateError,
    RuntimeSessionNotFoundError,
)
from core.runtime.message_admission import runtime_message_admission_handoff
from core.runtime.runtime_session import RuntimeSessionRecord


MAX_CONTINUATION_ADMISSION_HOPS = 8


class _ContinuationAdmissionRetry(RuntimeError):
    def __init__(self, session: RuntimeSessionRecord) -> None:
        super().__init__(session.session_id)
        self.session = session


def admit_runtime_session(
    state,
    *,
    session: RuntimeSessionRecord,
    allow_compatible_fork: bool = True,
    now: datetime | None = None,
) -> RuntimeContinuationResult:
    """Resolve current lineage, validate authority, and fork only with proof."""
    timestamp = now or datetime.now(tz=UTC)
    candidate = session
    last_fork: RuntimeContinuationResult | None = None
    for _hop in range(MAX_CONTINUATION_ADMISSION_HOPS):
        try:
            result = _admit_runtime_session_once(
                state,
                session=candidate,
                allow_compatible_fork=allow_compatible_fork,
                now=timestamp,
            )
        except _ContinuationAdmissionRetry as retry:
            candidate = retry.session
            continue
        if result.status == "direct":
            if last_fork is None:
                return result
            return RuntimeContinuationResult(
                status="forked",
                session=result.session,
                assessment=last_fork.assessment,
                handoff=last_fork.handoff,
            )
        last_fork = result
        candidate = result.session
    raise RuntimeProfileUpgradeRequiredError(
        "runtime_profile_upgrade_required",
        detail_code="runtime_continuation_hop_limit_exceeded",
    )


def _admit_runtime_session_once(
    state,
    *,
    session: RuntimeSessionRecord,
    allow_compatible_fork: bool,
    now: datetime,
) -> RuntimeContinuationResult:
    handoff = _continuation_handoff_for_session(state, session)
    pending = handoff if handoff is not None and handoff.phase != "completed" else None
    lock_session = (
        state.runtime_store.get_session(pending.predecessor_session_id)
        if pending is not None
        else resolve_latest_runtime_session(state.runtime_store, session)
    )
    successor_id = (
        pending.successor_session_id if pending is not None else str(uuid4())
    )
    admission_session_ids = {lock_session.session_id, successor_id}
    with ExitStack() as admission_stack:
        for session_id in sorted(admission_session_ids):
            admission_stack.enter_context(runtime_message_admission_handoff(session_id))
        lifecycle_session_ids = {lock_session.session_id}
        if pending is not None:
            lifecycle_session_ids.add(successor_id)
        for session_id in sorted(lifecycle_session_ids):
            admission_stack.enter_context(
                state.runtime_store.session_lifecycle_handoff(
                    workspace_id=lock_session.workspace_id,
                    session_id=session_id,
                )
            )
        live_handoff = _continuation_handoff_for_session(
            state,
            state.runtime_store.get_session(lock_session.session_id),
        )
        if live_handoff is not None and live_handoff.phase != "completed":
            if live_handoff.successor_session_id not in admission_session_ids:
                raise _ContinuationAdmissionRetry(lock_session)
            predecessor = state.runtime_store.get_session(
                live_handoff.predecessor_session_id
            )
            _require_handoff_turns_idle(state, live_handoff)
            return complete_existing_continuation_handoff(
                state,
                predecessor=predecessor,
                handoff=live_handoff,
                now=now,
            )
        current = resolve_latest_runtime_session(
            state.runtime_store,
            state.runtime_store.get_session(lock_session.session_id),
        )
        if current.session_id not in admission_session_ids:
            raise _ContinuationAdmissionRetry(current)
        assessment = assess_runtime_session_admission(
            state.provider_store,
            state.runtime_store,
            state.provider_registry,
            session=current,
            target_session_id=successor_id,
            now=now,
        )
        if assessment.status == "direct":
            return RuntimeContinuationResult(
                status="direct",
                session=current,
                assessment=assessment,
            )
        if assessment.status != "compatible_upgrade" or not allow_compatible_fork:
            raise RuntimeProfileUpgradeRequiredError(
                assessment.reason_code or "runtime_profile_upgrade_required",
                detail_code=assessment.detail_code,
            )
        admission_stack.enter_context(
            state.runtime_store.session_lifecycle_handoff(
                workspace_id=current.workspace_id,
                session_id=successor_id,
            )
        )
        return complete_compatible_continuation_fork(
            state,
            predecessor=current,
            assessment=assessment,
            now=now,
        )


def _require_handoff_turns_idle(state, handoff) -> None:
    session_ids = (
        handoff.predecessor_session_id,
        handoff.successor_session_id,
    )
    if any(
        runtime_session_has_nonterminal_turns(state.runtime_store, session_id)
        for session_id in session_ids
        if _session_exists(state, session_id)
    ):
        raise RuntimeProfileUpgradeRequiredError(
            "runtime_profile_upgrade_required",
            detail_code="runtime_profile_upgrade_turn_busy",
        )


def _session_exists(state, session_id: str) -> bool:
    try:
        state.runtime_store.get_session(session_id)
    except RuntimeSessionNotFoundError:
        return False
    return True


def continuation_repair_inventory(
    state,
    *,
    workspace_id: str | None = None,
    session_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Classify sessions without writing handoffs, turns, or runtime metadata."""
    timestamp = now or datetime.now(tz=UTC)
    inventory: list[dict[str, object]] = []
    sessions = _continuation_inventory_tips(
        state,
        workspace_id=workspace_id,
        session_ids=session_ids,
    )
    for session in sessions:
        target_session_id = _dry_run_successor_id(session.session_id)
        assessment = _inventory_admission_assessment(
            state,
            session=session,
            target_session_id=target_session_id,
            now=timestamp,
        )
        binding = session.execution_binding
        target = assessment.target_execution_binding
        inventory.append(
            {
                "session_id": session.session_id,
                "lineage_root_session_id": (
                    session.lineage_root_session_id or session.session_id
                ),
                "workspace_id": session.workspace_id,
                "status": assessment.status,
                "reason_code": assessment.reason_code,
                "detail_code": assessment.detail_code,
                "source_profile_revision": (
                    None if binding is None else binding.profile_definition_revision
                ),
                "target_profile_revision": (
                    None if target is None else target.profile_definition_revision
                ),
                "source_binding_digest": None if binding is None else binding.binding_digest,
                "target_binding_digest": None if target is None else target.binding_digest,
                "compatibility_digest": assessment.compatibility_digest,
                "compatible_capabilities": assessment.compatible_capabilities,
            }
        )
    return inventory


def _inventory_admission_assessment(
    state,
    *,
    session: RuntimeSessionRecord,
    target_session_id: str,
    now: datetime,
) -> RuntimeAdmissionAssessment:
    handoff = _continuation_handoff_for_session(state, session)
    if handoff is None or handoff.phase == "completed":
        return assess_runtime_session_admission(
            state.provider_store,
            state.runtime_store,
            state.provider_registry,
            session=session,
            target_session_id=target_session_id,
            now=now,
        )
    try:
        predecessor = state.runtime_store.get_session(
            handoff.predecessor_session_id
        )
        _require_handoff_turns_idle(state, handoff)
        revalidate_continuation_handoff(
            state,
            predecessor=predecessor,
            handoff=handoff,
            now=now,
        )
    except RuntimeProfileUpgradeRequiredError as error:
        return RuntimeAdmissionAssessment(
            status="upgrade_required",
            session_id=session.session_id,
            reason_code=error.reason_code,
            detail_code=error.detail_code,
        )
    return RuntimeAdmissionAssessment(
        status="compatible_upgrade",
        session_id=session.session_id,
        reason_code="runtime_profile_upgrade_compatible",
        detail_code="runtime_continuation_handoff_pending",
        target_execution_binding=handoff.target_execution_binding,
        compatible_capabilities=handoff.compatible_capabilities,
        compatibility_digest=handoff.compatibility_digest,
    )


def repair_compatible_runtime_continuations(
    state,
    *,
    workspace_id: str,
    session_ids: set[str] | None = None,
    dry_run: bool = True,
    now: datetime | None = None,
    inventory: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Inventory or materialize every explicitly compatible session in scope."""
    inventory = (
        list(inventory)
        if inventory is not None
        else continuation_repair_inventory(
            state,
            workspace_id=workspace_id,
            session_ids=session_ids,
            now=now,
        )
    )
    allowed_session_ids = _resolved_scope_session_ids(
        state,
        workspace_id=workspace_id,
        session_ids=session_ids,
    )
    for item in inventory:
        item_session_id = str(item.get("session_id") or "").strip()
        if (
            str(item.get("workspace_id") or "").strip() != workspace_id
            or not item_session_id
            or (
                allowed_session_ids is not None
                and item_session_id not in allowed_session_ids
            )
        ):
            raise RuntimeProviderStateError(
                "runtime_continuation_repair_scope_mismatch"
            )
    results: list[dict[str, object]] = []
    if not dry_run:
        compatible_ids = {
            str(item["session_id"])
            for item in inventory
            if item["status"] == "compatible_upgrade"
        }
        for session_id in sorted(compatible_ids):
            source = state.runtime_store.get_session(session_id)
            if source.workspace_id != workspace_id:
                raise RuntimeProviderStateError(
                    "runtime_continuation_repair_scope_mismatch"
                )
            result = admit_runtime_session(state, session=source, now=now)
            results.append(
                {
                    "predecessor_session_id": session_id,
                    "successor_session_id": result.session.session_id,
                    "handoff_id": None if result.handoff is None else result.handoff.handoff_id,
                    "status": result.status,
                }
            )
    return {
        "workspace_id": workspace_id,
        "dry_run": dry_run,
        "inspected_count": len(inventory),
        "compatible_count": sum(
            1 for item in inventory if item["status"] == "compatible_upgrade"
        ),
        "inventory": inventory,
        "results": results,
    }


def _continuation_inventory_tips(
    state,
    *,
    workspace_id: str | None,
    session_ids: set[str] | None,
) -> list[RuntimeSessionRecord]:
    if session_ids is None:
        candidates = (
            state.runtime_store.list_sessions(workspace_id)
            if workspace_id is not None
            else state.runtime_store.list_all_sessions()
        )
    else:
        candidates = [
            state.runtime_store.get_session(session_id)
            for session_id in sorted(session_ids)
        ]
    tips: dict[str, RuntimeSessionRecord] = {}
    for candidate in candidates:
        if workspace_id is not None and candidate.workspace_id != workspace_id:
            raise RuntimeProviderStateError("runtime_continuation_repair_scope_mismatch")
        tip = resolve_latest_runtime_session(state.runtime_store, candidate)
        tips[tip.session_id] = tip
    return [tips[session_id] for session_id in sorted(tips)]


def _resolved_scope_session_ids(
    state,
    *,
    workspace_id: str,
    session_ids: set[str] | None,
) -> set[str] | None:
    if session_ids is None:
        return None
    return {
        session.session_id
        for session in _continuation_inventory_tips(
            state,
            workspace_id=workspace_id,
            session_ids=session_ids,
        )
    }


def continuation_state(
    *,
    provider_store,
    runtime_store,
    provider_registry,
    workspace_store=None,
    observability_store=None,
    runtime_event_bus=None,
    runtime_thread_event_bus=None,
    repository_root=None,
):
    """Build the minimal state facade needed by operator repair surfaces."""
    return SimpleNamespace(
        provider_store=provider_store,
        runtime_store=runtime_store,
        provider_registry=provider_registry,
        workspace_store=workspace_store,
        observability_store=observability_store,
        runtime_event_bus=runtime_event_bus,
        runtime_thread_event_bus=runtime_thread_event_bus,
        repository_root=repository_root,
    )


def _continuation_handoff_for_session(state, session):
    handoff_id = str(session.continuation_handoff_id or "").strip()
    if handoff_id:
        return state.runtime_store.get_continuation_handoff(handoff_id)
    return state.runtime_store.get_continuation_handoff_by_predecessor(
        workspace_id=session.workspace_id,
        predecessor_session_id=session.session_id,
    )


def _dry_run_successor_id(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    return f"continuation-dry-run-{digest}"
