"""Idempotent continuation forks for sessions with obsolete runtime authority."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from core.recovery.continuation_admission import assess_runtime_session_admission
from core.recovery.continuation_handoff_service import (
    RuntimeContinuationResult,
    complete_compatible_continuation_fork,
    complete_existing_continuation_handoff,
)
from core.runtime.continuation_lineage import resolve_latest_runtime_session
from core.runtime.errors import (
    RuntimeProfileUpgradeRequiredError,
    RuntimeProviderStateError,
)
from core.runtime.runtime_session import RuntimeSessionRecord


def admit_runtime_session(
    state,
    *,
    session: RuntimeSessionRecord,
    allow_compatible_fork: bool = True,
    now: datetime | None = None,
) -> RuntimeContinuationResult:
    """Resolve current lineage, validate authority, and fork only with proof."""
    timestamp = now or datetime.now(tz=UTC)
    pending = _continuation_handoff_for_session(state, session)
    lock_session = (
        state.runtime_store.get_session(pending.predecessor_session_id)
        if pending is not None
        else resolve_latest_runtime_session(state.runtime_store, session)
    )
    with state.runtime_store.session_lifecycle_handoff(
        workspace_id=lock_session.workspace_id,
        session_id=lock_session.session_id,
    ):
        if pending is not None:
            pending = state.runtime_store.get_continuation_handoff(pending.handoff_id)
            if pending.phase != "completed":
                predecessor = state.runtime_store.get_session(
                    pending.predecessor_session_id
                )
                return complete_existing_continuation_handoff(
                    state,
                    predecessor=predecessor,
                    handoff=pending,
                    now=timestamp,
                )
        current = resolve_latest_runtime_session(
            state.runtime_store,
            state.runtime_store.get_session(lock_session.session_id),
        )
        successor_id = str(uuid4())
        assessment = assess_runtime_session_admission(
            state.provider_store,
            state.runtime_store,
            state.provider_registry,
            session=current,
            target_session_id=successor_id,
            now=timestamp,
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
        return complete_compatible_continuation_fork(
            state,
            predecessor=current,
            assessment=assessment,
            now=timestamp,
        )


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
    sessions = (
        state.runtime_store.list_sessions(workspace_id)
        if workspace_id is not None
        else state.runtime_store.list_all_sessions()
    )
    for session in sessions:
        if session_ids is not None and session.session_id not in session_ids:
            continue
        if session.predecessor_session_id or session.continuation_successor_session_id:
            continue
        target_session_id = _dry_run_successor_id(session.session_id)
        assessment = assess_runtime_session_admission(
            state.provider_store,
            state.runtime_store,
            state.provider_registry,
            session=session,
            target_session_id=target_session_id,
            now=timestamp,
        )
        binding = session.execution_binding
        target = assessment.target_execution_binding
        inventory.append(
            {
                "session_id": session.session_id,
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
    for item in inventory:
        item_session_id = str(item.get("session_id") or "").strip()
        if (
            str(item.get("workspace_id") or "").strip() != workspace_id
            or not item_session_id
            or (session_ids is not None and item_session_id not in session_ids)
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
