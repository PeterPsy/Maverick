"""Initialization helpers for a session's mutable provider state."""

from __future__ import annotations

from datetime import datetime

from core.runtime.execution_binding import RuntimeExecutionBinding
from core.runtime.provider_state import RuntimeProviderState
from core.runtime.runtime_state import RuntimeStateRecord
from core.runtime.store import RuntimeStore


def initial_runtime_state(*, session_id: str, workspace_id: str, now: datetime) -> RuntimeStateRecord:
    """Build the canonical initial lifecycle state for a new session."""
    return RuntimeStateRecord(
        session_id=session_id,
        workspace_id=workspace_id,
        current_turn_id=None,
        session_status="created",
        turn_status=None,
        last_progress_at=None,
        watchdog_deadline_at=None,
        forced_stop_reason=None,
        last_error_detail=None,
        updated_at=now,
    )


def initialize_bound_provider_state(
    store: RuntimeStore,
    binding: RuntimeExecutionBinding | None,
    *,
    session_id: str,
    workspace_id: str,
    now: datetime,
) -> None:
    """Insert revision zero when a session has an immutable execution binding."""
    if binding is None:
        return
    store.initialize_provider_state(
        RuntimeProviderState(
            session_id=session_id,
            workspace_id=workspace_id,
            runtime_engine_id=binding.runtime_engine_id,
            model_provider_id=binding.model_provider_id,
            continuation_id=None,
            provider_thread_id=None,
            provider_request_id=None,
            provider_private_envelope=None,
            revision=0,
            turn_generation=None,
            updated_at=now,
        )
    )
