"""Runtime integration for resolving and auditing effective authority."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from core.providers.agentic_adapter import AgenticRuntimeEngineAdapter, RuntimeHealthContext
from core.providers.agentic_workspace_policy import actor_selection_allowed
from core.providers.certificate_targets import validate_api_binding_certificate_target
from core.providers.certified_execution_tcb import certified_tcb_revision_fence
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.service import effective_provider_registry
from core.providers.store import ProviderStore
from core.runtime.authority import (
    EffectiveRuntimeAuthority,
    effective_authority_audit_payload,
    resolve_effective_runtime_authority,
    runtime_feature_flag_revision,
    validate_live_runtime_binding_governance,
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
    from core.certification_lab.runtime_context import lab_authorization_for_state

    lab = lab_authorization_for_state(state, binding)
    if lab is not None:
        return lab.resolve(session=session, adapter=adapter, turn_id=turn_id,
                           tool_handles=currently_authorized_tool_handles, health=health,
                           actor_allowed=actor_allowed, actor_revision=actor_revision)
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


def revalidate_runtime_authority_snapshot(
    state: PlatformState,
    *,
    session: RuntimeSessionRecord,
    adapter: AgenticRuntimeEngineAdapter,
    authority: EffectiveRuntimeAuthority,
    provider_store: ProviderStore | None = None,
    now: datetime | None = None,
) -> EffectiveRuntimeAuthority:
    """Check mutable revocation inputs without rerunning TCB/behavior proof."""
    from core.certification_lab.runtime_context import lab_authorization_for_state

    binding = session.execution_binding
    if binding is None or authority.execution_binding_id != binding.execution_binding_id:
        raise CapabilityCertificateError("runtime_authority_unavailable")
    active_provider_store = provider_store or state.provider_store
    lab = lab_authorization_for_state(state, binding)
    if lab is None:
        _revalidate_production_certificate(active_provider_store, binding=binding, adapter=adapter,
                                           authority=authority, now=now)
    else:
        lab.revalidate(session=session, authority=authority)
    workspace_binding = validate_live_runtime_binding_governance(
        active_provider_store,
        binding=binding,
    )
    if not _authority_revision_matches(
        authority,
        f"workspace-live:{workspace_binding.binding_id}:{workspace_binding.revision}",
    ):
        raise CapabilityCertificateError("runtime_policy_changed")
    actor_allowed, actor_revision = live_runtime_actor_policy(
        state,
        session=session,
        provider_store=active_provider_store,
    )
    if not actor_allowed:
        raise CapabilityCertificateError("runtime_actor_policy_denied")
    if actor_revision != authority.actor_policy_revision:
        raise CapabilityCertificateError("runtime_actor_policy_changed")
    if runtime_feature_flag_revision(binding) != authority.feature_flag_revision:
        raise CapabilityCertificateError("runtime_feature_flags_changed")
    health = run_runtime_coroutine(
        adapter.health(RuntimeHealthContext(binding=binding))
    )
    if health.status not in {"healthy", "degraded"}:
        raise CapabilityCertificateError("runtime_health_unavailable")
    if (
        f"runtime-health:{canonical_digest(health)}"
        != authority.health_revision
    ):
        raise CapabilityCertificateError("runtime_health_changed")
    effective_mode = (
        "sandbox"
        if "sandbox" in {binding.execution_mode, session.effective_mode}
        else "full-access"
    )
    if effective_mode != authority.execution_mode:
        raise CapabilityCertificateError("runtime_execution_mode_changed")
    if not authority.tcb_revision_fence:
        raise CapabilityCertificateError(
            "certificate_tcb_revision_fence_missing"
        )
    if certified_tcb_revision_fence() != authority.tcb_revision_fence:
        raise CapabilityCertificateError("certificate_tcb_drift")
    return authority


def _revalidate_production_certificate(active_provider_store, *, binding, adapter, authority, now):
    from core.runtime.authorization_domain import require_production_authorization

    require_production_authorization(binding)
    require_production_authorization(authority)
    if authority.certificate_id != binding.capability_certificate_id:
        raise CapabilityCertificateError("runtime_authority_unavailable")
    try:
        certificate = active_provider_store.get_capability_certificate(
            binding.capability_certificate_id
        )
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("certificate_missing") from error
    status = active_provider_store.get_capability_certificate_status(
        certificate.certificate_id
    )
    if status is None:
        raise CapabilityCertificateError("certificate_status_missing")
    if status.status != "active":
        raise CapabilityCertificateError("certificate_revoked")
    from core.providers.certificate_service import _is_native_certificate
    from core.providers.native_agent_certificates import native_installation_for_adapter, validate_native_connection_certificate

    if _is_native_certificate(certificate):
        from core.providers.native_model_revision import require_native_model_revision_transport

        require_native_model_revision_transport(binding)
        validate_native_connection_certificate(
            active_provider_store, certificate, now=now, installation=native_installation_for_adapter(adapter),
        )
    validate_api_binding_certificate_target(
        active_provider_store, binding=binding, certificate=certificate,
    )
    if not _authority_revision_matches(
        authority,
        f"certificate-status:{certificate.certificate_id}:{status.revision}",
    ):
        raise CapabilityCertificateError("certificate_status_changed")
    timestamp = now or datetime.now(tz=UTC)
    if (
        authority.certificate_expires_at is None
        or certificate.expires_at != authority.certificate_expires_at
        or timestamp >= certificate.expires_at
    ):
        raise CapabilityCertificateError("certificate_expired")
    if (
        certificate.tcb_manifest_id != authority.tcb_manifest_id
        or certificate.tcb_manifest_version != authority.tcb_manifest_version
        or certificate.tcb_structure_digest != authority.tcb_structure_digest
        or certificate.tcb_live_digest != authority.tcb_live_digest
    ):
        raise CapabilityCertificateError("certificate_tcb_binding_mismatch")


def _authority_revision_matches(
    authority: EffectiveRuntimeAuthority,
    revision: str,
) -> bool:
    return revision in authority.policy_revision_set


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
    if getattr(binding, 'authorization_domain', 'production') == 'certification_lab' and (
        platform_role != 'member' or workspace_role != 'member'
    ):
        return False, f"workspace-actor:{workspace_binding.binding_id}:{workspace_binding.revision}"
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
