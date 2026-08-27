"""Runtime integration for resolving and auditing effective authority."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.agentic_adapter import AgenticRuntimeEngineAdapter, RuntimeHealthContext
from core.providers.agentic_workspace_policy import actor_selection_allowed
from core.providers.service import effective_provider_registry
from core.providers.store import ProviderStore
from core.runtime.authority import (
    EffectiveRuntimeAuthority,
    effective_authority_audit_payload,
    resolve_effective_runtime_authority,
    validate_effective_context_capabilities,
)
from core.runtime.runtime_actor import resolve_runtime_actor_roles
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
    authority = resolve_runtime_authority_snapshot(
        state,
        session=session,
        adapter=adapter,
        turn_id=turn_id,
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


def resolve_runtime_authority_snapshot(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    adapter: AgenticRuntimeEngineAdapter,
    turn_id: str,
    currently_authorized_tool_handles: tuple[str, ...] | None = None,
    provider_store: ProviderStore | None = None,
    adapter_artifact_digest: str | None = None,
) -> EffectiveRuntimeAuthority:
    """Compute the same live snapshot used by admission, dispatch, and refresh."""
    binding = session.execution_binding
    if binding is None:
        raise ValueError("Effective authority requires a pinned execution binding.")
    health = run_runtime_coroutine(adapter.health(RuntimeHealthContext(binding=binding)))
    if currently_authorized_tool_handles is None:
        handle_resolver = getattr(adapter, "currently_authorized_tool_handles", None)
        currently_authorized_tool_handles = (
            tuple(handle_resolver(binding)) if callable(handle_resolver) else ()
        )
    active_provider_store = provider_store or state.provider_store
    actor_allowed, actor_revision = live_runtime_actor_policy(
        state,
        session=session,
        provider_store=active_provider_store,
    )
    return resolve_effective_runtime_authority(
        active_provider_store,
        binding=binding,
        adapter=adapter,
        turn_id=turn_id,
        currently_authorized_tool_handles=currently_authorized_tool_handles,
        live_execution_mode=session.effective_mode,
        health_status=health.status,
        health_revision=f"runtime-health:{canonical_digest(health)}",
        actor_policy_allowed=actor_allowed,
        actor_policy_revision=actor_revision,
        adapter_artifact_digest=adapter_artifact_digest,
    )


def live_runtime_actor_policy(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    provider_store: ProviderStore | None = None,
) -> tuple[bool, str]:
    """Re-evaluate the mutable actor policy for every authority refresh."""
    binding = session.execution_binding
    if binding is None:
        return True, "runtime-actor:not-agentic"
    active_provider_store = provider_store or state.provider_store
    workspace_binding = active_provider_store.get_workspace_agentic_profile_binding(
        binding.workspace_binding_id
    )
    try:
        platform_role, user_id, workspace_role = resolve_runtime_actor_roles(
            state,
            user_id=session.owner_user_id,
            workspace_id=session.workspace_id,
        )
    except Exception:
        return False, (
            f"workspace-actor:{workspace_binding.binding_id}:"
            f"{workspace_binding.revision}"
        )
    return (
        actor_selection_allowed(
            workspace_binding,
            user_id=user_id,
            platform_role=platform_role,
            workspace_role=workspace_role,
            agent_type_id=str(session.agent_type_id or ""),
        ),
        f"workspace-actor:{workspace_binding.binding_id}:{workspace_binding.revision}",
    )


def preflight_runtime_context_capabilities(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    turn_id: str,
    adapter: AgenticRuntimeEngineAdapter | None = None,
    invoked_skills: object = (),
    attachments: object = (),
    app_references: object = (),
) -> EffectiveRuntimeAuthority | None:
    """Block unsupported context before a turn, event, or provider side effect."""
    if session.execution_binding is None:
        return None
    if adapter is None:
        from core.providers.service import resolve_runtime_engine_for_session

        _provider, _selection, adapter, _legacy = resolve_runtime_engine_for_session(
            state.provider_store,
            session=session,
            registry=getattr(state, "provider_registry", None),
        )
    authority = resolve_runtime_authority_snapshot(
        state,
        session=session,
        adapter=adapter,
        turn_id=turn_id,
    )
    validate_effective_context_capabilities(
        authority,
        invoked_skills=invoked_skills,
        attachments=attachments,
        app_references=app_references,
    )
    return authority


def preflight_execution_binding_context(
    state: PlatformState,
    *,
    binding,
    turn_id: str,
    live_execution_mode,
    actor_policy_revision: str,
    invoked_skills: object = (),
    attachments: object = (),
    app_references: object = (),
    adapter: AgenticRuntimeEngineAdapter | None = None,
) -> EffectiveRuntimeAuthority:
    """Compute and validate the canonical snapshot before session persistence."""
    if adapter is None:
        registry = effective_provider_registry(
            state.provider_store,
            registry=getattr(state, "provider_registry", None),
        )
        adapter = registry.get_agentic_runtime_adapter(binding.runtime_engine_id)
    health = run_runtime_coroutine(adapter.health(RuntimeHealthContext(binding=binding)))
    handle_resolver = getattr(adapter, "currently_authorized_tool_handles", None)
    handles = tuple(handle_resolver(binding)) if callable(handle_resolver) else ()
    authority = resolve_effective_runtime_authority(
        state.provider_store,
        binding=binding,
        adapter=adapter,
        turn_id=turn_id,
        currently_authorized_tool_handles=handles,
        live_execution_mode=live_execution_mode,
        health_status=health.status,
        health_revision=f"runtime-health:{canonical_digest(health)}",
        actor_policy_allowed=True,
        actor_policy_revision=actor_policy_revision,
    )
    validate_effective_context_capabilities(
        authority,
        invoked_skills=invoked_skills,
        attachments=attachments,
        app_references=app_references,
    )
    return authority
