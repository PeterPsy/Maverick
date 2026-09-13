"""Automatic, snapshot-backed continuation after certified profile rollout."""

from __future__ import annotations

from datetime import UTC, datetime

from core.observability.service import record_platform_audit, record_platform_event
from core.recovery.continuation_fork import (
    continuation_repair_inventory,
    repair_compatible_runtime_continuations,
)
from core.recovery.continuation_snapshot import snapshot_runtime_continuation_state


def repair_runtime_continuations_after_certified_rollout(
    state,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Fork every provably compatible chat after active profiles converge.

    Certificate publication itself is intentionally immutable. This hook runs
    after profile and workspace-binding rollout, snapshots every candidate
    lineage, and materializes a current certified successor. A failed snapshot
    prevents all writes for that workspace; a failed handoff remains resumable
    and does not prevent unrelated chats or the backend from starting.
    """
    timestamp = now or datetime.now(tz=UTC)
    workspace_ids = sorted(
        {
            session.workspace_id
            for session in state.runtime_store.list_all_sessions()
            if session.runtime_mode == "agentic"
        }
    )
    workspace_results: list[dict[str, object]] = []
    for workspace_id in workspace_ids:
        workspace_results.append(
            _repair_workspace_continuations(
                state,
                workspace_id=workspace_id,
                now=timestamp,
            )
        )
    return {
        "workspace_count": len(workspace_results),
        "candidate_count": sum(
            int(item["candidate_count"]) for item in workspace_results
        ),
        "repaired_count": sum(
            int(item["repaired_count"]) for item in workspace_results
        ),
        "failure_count": sum(
            int(item["failure_count"]) for item in workspace_results
        ),
        "workspaces": workspace_results,
    }


def _repair_workspace_continuations(
    state,
    *,
    workspace_id: str,
    now: datetime,
) -> dict[str, object]:
    try:
        inventory = continuation_repair_inventory(
            state,
            workspace_id=workspace_id,
            now=now,
        )
    except Exception as error:
        # Best-effort startup reconciliation must not take down Core.
        result = _workspace_result(
            workspace_id,
            candidate_count=0,
            repaired_count=0,
            failures=[_failure_payload(None, error)],
        )
        _record_rollout_repair(state, result=result, now=now)
        return result
    candidates = [
        item
        for item in inventory
        if item.get("status") == "compatible_upgrade"
        and _is_codex_session(state, str(item["session_id"]))
    ]
    if not candidates:
        return _workspace_result(
            workspace_id,
            candidate_count=0,
            repaired_count=0,
            failures=[],
        )
    candidate_ids = {str(item["session_id"]) for item in candidates}
    try:
        snapshot = snapshot_runtime_continuation_state(
            state.repository_root,
            workspace_id=workspace_id,
            session_ids=candidate_ids,
            now=now,
        )
    except Exception as error:
        # Snapshot failure is fail-closed for mutation, not host startup.
        result = _workspace_result(
            workspace_id,
            candidate_count=len(candidates),
            repaired_count=0,
            failures=[_failure_payload(None, error)],
        )
        _record_rollout_repair(state, result=result, now=now)
        return result

    repaired_count = 0
    failures: list[dict[str, str | None]] = []
    for item in candidates:
        session_id = str(item["session_id"])
        try:
            repair = repair_compatible_runtime_continuations(
                state,
                workspace_id=workspace_id,
                session_ids={session_id},
                dry_run=False,
                now=now,
                inventory=[item],
            )
            repaired_count += len(repair["results"])
        except Exception as error:
            # Each durable handoff is independently resumable.
            failures.append(_failure_payload(session_id, error))
    result = _workspace_result(
        workspace_id,
        candidate_count=len(candidates),
        repaired_count=repaired_count,
        failures=failures,
        snapshot=snapshot,
    )
    _record_rollout_repair(state, result=result, now=now)
    return result


def _workspace_result(
    workspace_id: str,
    *,
    candidate_count: int,
    repaired_count: int,
    failures: list[dict[str, str | None]],
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "workspace_id": workspace_id,
        "candidate_count": candidate_count,
        "repaired_count": repaired_count,
        "failure_count": len(failures),
        "failures": failures,
        "snapshot": snapshot,
    }


def _failure_payload(
    session_id: str | None,
    error: Exception,
) -> dict[str, str | None]:
    explicit_reason = str(
        getattr(error, "detail_code", None)
        or getattr(error, "reason_code", None)
        or ""
    ).strip()
    message = str(error).strip()
    safe_message = (
        message
        if message
        and len(message) <= 160
        and all(char.isalnum() or char in "_-.:" for char in message)
        else ""
    )
    return {
        "session_id": session_id,
        "reason_code": explicit_reason or safe_message or error.__class__.__name__,
    }


def _is_codex_session(state, session_id: str) -> bool:
    binding = state.runtime_store.get_session(session_id).execution_binding
    return binding is not None and binding.runtime_engine_id == "codex"


def _record_rollout_repair(state, *, result: dict[str, object], now: datetime) -> None:
    observability_store = getattr(state, "observability_store", None)
    if observability_store is None:
        return
    failures = list(result["failures"])
    snapshot = result.get("snapshot")
    payload = {
        "candidate_count": result["candidate_count"],
        "repaired_count": result["repaired_count"],
        "failure_count": result["failure_count"],
        "failure_reason_codes": [item["reason_code"] for item in failures],
        "snapshot_id": (
            snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None
        ),
    }
    status = "failed" if failures else "succeeded"
    workspace_id = str(result["workspace_id"])
    record_platform_audit(
        observability_store,
        action="recovery.continuation.certified_rollout",
        status=status,
        source_domain="recovery",
        detail=(
            f"Repaired {result['repaired_count']} of "
            f"{result['candidate_count']} certified runtime continuations."
        ),
        workspace_id=workspace_id,
        provider_id="codex",
        payload=payload,
        now=now,
    )
    record_platform_event(
        observability_store,
        event_type="runtime.continuation.certified_rollout_reconciled",
        event_plane="platform",
        source_domain="recovery",
        workspace_id=workspace_id,
        provider_id="codex",
        payload=payload,
        now=now,
    )


__all__ = ["repair_runtime_continuations_after_certified_rollout"]
