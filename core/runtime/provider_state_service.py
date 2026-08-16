"""Lifecycle-safe updates for mutable runtime provider state."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.runtime.agentic_runtime_service import update_runtime_provider_state
from core.runtime.errors import RuntimeProviderStateError
from core.runtime.lifecycle_service_events import record_runtime_event
from core.runtime.runtime_events import RuntimeEventRecord

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


def record_provider_thread_id(
    state: PlatformState,
    *,
    session_id: str,
    provider_id: str,
    provider_thread_id: str,
) -> RuntimeEventRecord:
    """Bind continuation state with CAS, retaining only the Phase-0 legacy path."""
    session = state.runtime_store.get_session(session_id)
    if session.execution_binding is not None and session.execution_binding.runtime_engine_id != provider_id:
        raise RuntimeProviderStateError("Provider thread does not match the pinned runtime engine.")
    if session.execution_binding is None:
        state.runtime_store.patch_session_metadata(
            session_id=session_id,
            workspace_id=session.workspace_id,
            updates={"provider_id": provider_id, "provider_thread_id": provider_thread_id},
        )
    else:
        update_runtime_provider_state(
            state.runtime_store,
            session_id=session_id,
            updates={
                "continuation_id": provider_thread_id,
                "provider_thread_id": provider_thread_id,
            },
        )
    return record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session_id,
        plane="runtime",
        event_type="runtime.provider_thread.bound",
        payload={"provider_id": provider_id, "provider_thread_id": provider_thread_id},
        event_bus=state.runtime_event_bus,
    )
