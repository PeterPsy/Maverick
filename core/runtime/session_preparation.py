"""Persisted publication barrier for runtime session creation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.execution_binding import RuntimeExecutionBinding
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.session_provider_state import initial_runtime_state, initialize_bound_provider_state
from core.runtime.store import RuntimeStore


def prepare_runtime_session(
    store: RuntimeStore,
    session: RuntimeSessionRecord,
    binding: RuntimeExecutionBinding | None,
    *,
    now: datetime,
) -> tuple[RuntimeSessionRecord, bool]:
    """Initialize and publish a session, repairing an exact interrupted retry."""
    try:
        saved = store.insert_session(session)
    except RuntimeProviderStateError:
        saved = store.get_session(session.session_id)
        if not _same_session_preparation(saved, session):
            raise
        if saved.preparation_status == "prepared":
            return saved, False
        now = saved.updated_at

    initialize_bound_provider_state(
        store,
        binding,
        session_id=session.session_id,
        workspace_id=session.workspace_id,
        now=now,
    )
    store.save_state(
        initial_runtime_state(
            session_id=session.session_id,
            workspace_id=session.workspace_id,
            now=now,
        )
    )
    store.mark_session_prepared(
        session_id=session.session_id,
        workspace_id=session.workspace_id,
        now=now,
    )
    return replace(saved, preparation_status="prepared", updated_at=now), True


def _same_session_preparation(existing: RuntimeSessionRecord, requested: RuntimeSessionRecord) -> bool:
    """Allow retries only for the exact immutable session aggregate."""
    return existing == replace(
        requested,
        preparation_status=existing.preparation_status,
        updated_at=existing.updated_at,
    )
