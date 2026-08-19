"""Runtime integration for resolving and auditing effective authority."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.agentic_adapter import AgenticRuntimeEngineAdapter, RuntimeHealthContext
from core.runtime.authority import (
    EffectiveRuntimeAuthority,
    effective_authority_audit_payload,
    resolve_effective_runtime_authority,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.async_runtime import run_runtime_coroutine
from core.runtime.execution_binding import canonical_digest
from core.runtime.service import record_runtime_event

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState


def resolve_and_record_runtime_authority(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    adapter: AgenticRuntimeEngineAdapter,
    turn_id: str,
    event_type: str = "runtime.authority.evaluated",
) -> EffectiveRuntimeAuthority:
    """Resolve fail-closed authority and persist only its redaction-safe digest summary."""
    binding = session.execution_binding
    if binding is None:
        raise ValueError("Effective authority requires a pinned execution binding.")
    health = run_runtime_coroutine(adapter.health(RuntimeHealthContext(binding=binding)))
    handle_resolver = getattr(adapter, "currently_authorized_tool_handles", None)
    currently_authorized_tool_handles = (
        tuple(handle_resolver(binding)) if callable(handle_resolver) else ()
    )
    authority = resolve_effective_runtime_authority(
        state.provider_store,
        binding=binding,
        adapter=adapter,
        turn_id=turn_id,
        currently_authorized_tool_handles=currently_authorized_tool_handles,
        live_execution_mode=session.effective_mode,
        health_status=health.status,
        health_revision=f"runtime-health:{canonical_digest(health)}",
    )
    record_runtime_event(
        state.runtime_store,
        event_id=str(uuid4()),
        session_id=session.session_id,
        turn_id=None if turn_id.startswith("prewarm:") else turn_id,
        plane="runtime",
        event_type=event_type,
        payload=effective_authority_audit_payload(authority),
        event_bus=getattr(state, "runtime_event_bus", None),
    )
    return authority
