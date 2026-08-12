"""Content-free audit records for runtime transcript reads."""

from __future__ import annotations

from typing import Any

from core.observability.service import record_platform_audit
from core.runtime.transcript_models import RuntimeTranscriptReadContext


def record_runtime_transcript_audit(
    observability_store,
    *,
    action: str,
    surface: str,
    context: RuntimeTranscriptReadContext,
    outcome: str,
    target_thread_id: str | None = None,
    authorization_relation: str | None = None,
    profile: str | None = None,
    page_limit: int | None = None,
    returned_count: int | None = None,
    redactions_applied: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist only identifiers and bounded read metadata, never transcript text."""
    if observability_store is None:
        return
    payload: dict[str, Any] = {
        "caller_runtime_session_id": context.caller_runtime_session_id,
        "target_thread_id": target_thread_id,
        "authorization_relation": authorization_relation,
        "profile": profile,
        "page_limit": page_limit,
        "returned_count": returned_count,
        "redactions_applied": redactions_applied,
        "outcome": outcome,
    }
    if extra:
        payload.update(extra)
    record_platform_audit(
        observability_store,
        action=action,
        status="succeeded" if outcome == "authorized" else "failed",
        source_domain=f"runtime_{surface}",
        detail=f"Runtime transcript read {outcome}.",
        workspace_id=context.workspace_id,
        runtime_session_id=context.caller_runtime_session_id,
        payload=payload,
    )
