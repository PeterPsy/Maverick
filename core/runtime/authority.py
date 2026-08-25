"""Monotonic live authority calculation for pinned agentic turns."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import (
    AgenticRuntimePolicy,
    WorkspaceAgenticProfileBinding,
)
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from core.runtime.agentic_feature_flags import parallel_tool_calls_enabled


@dataclass(frozen=True)
class EffectiveRuntimeAuthority:
    """Ephemeral, non-bearer authority narrowed from pinned and live policy."""

    execution_binding_id: str
    turn_id: str
    certificate_id: str
    allowed_capabilities: RuntimeCapabilitySet
    allowed_tool_handles: tuple[str, ...]
    execution_mode: ExecutionMode
    egress_policy_id: str
    policy_revision_set: tuple[str, ...]
    health_revision: str
    authority_digest: str
    computed_at: datetime


def resolve_effective_runtime_authority(
    store: ProviderStore,
    *,
    binding: RuntimeExecutionBinding,
    adapter: object,
    turn_id: str,
    currently_authorized_tool_handles: tuple[str, ...] = (),
    live_execution_mode: ExecutionMode | None = None,
    health_status: str = "healthy",
    health_revision: str = "runtime-health:unknown",
    observed_upstream_id: str | None = None,
    now: datetime | None = None,
) -> EffectiveRuntimeAuthority:
    """Intersect certified capability with every pinned and live restriction."""
    timestamp = now or datetime.now(tz=UTC)
    certificate = validate_certificate_for_binding(
        store,
        binding=binding,
        adapter=adapter,
        observed_upstream_id=observed_upstream_id,
        now=timestamp,
    )
    if health_status not in {"healthy", "degraded"}:
        raise CapabilityCertificateError("runtime_health_unavailable")
    workspace_binding = validate_live_runtime_binding_governance(
        store,
        binding=binding,
    )
    policy = intersect_runtime_policies(
        binding.profile_policy_ceiling_snapshot,
        binding.workspace_policy_ceiling_snapshot,
        workspace_binding.workspace_policy_ceiling,
    )
    capabilities = _narrow_capabilities(certificate.certified_capabilities, policy)
    tool_handles = _allowed_tool_handles(
        currently_authorized_tool_handles,
        binding.profile_policy_ceiling_snapshot,
        binding.workspace_policy_ceiling_snapshot,
        workspace_binding.workspace_policy_ceiling,
    )
    if not capabilities.tool_orchestration:
        tool_handles = ()
    status = store.get_capability_certificate_status(certificate.certificate_id)
    status_revision = 0 if status is None else status.revision
    execution_mode: ExecutionMode = (
        "sandbox"
        if "sandbox" in {binding.execution_mode, live_execution_mode}
        else "full-access"
    )
    authority = EffectiveRuntimeAuthority(
        execution_binding_id=binding.execution_binding_id,
        turn_id=turn_id,
        certificate_id=certificate.certificate_id,
        allowed_capabilities=capabilities,
        allowed_tool_handles=tool_handles,
        execution_mode=execution_mode,
        egress_policy_id=binding.egress_policy_id,
        policy_revision_set=(
            f"profile:{binding.profile_definition_id}:{binding.profile_definition_revision}",
            f"workspace-snapshot:{binding.workspace_binding_id}:{binding.workspace_binding_revision}",
            f"workspace-live:{workspace_binding.binding_id}:{workspace_binding.revision}",
            f"certificate-status:{certificate.certificate_id}:{status_revision}",
            f"egress:{binding.egress_policy_id}:{binding.egress_policy_revision}",
        ),
        health_revision=str(health_revision or "runtime-health:unknown"),
        authority_digest="",
        computed_at=timestamp,
    )
    return replace(authority, authority_digest=canonical_digest(authority))


def validate_live_runtime_binding_governance(
    store: ProviderStore,
    *,
    binding: RuntimeExecutionBinding,
    allow_inactive_definition: bool = False,
) -> WorkspaceAgenticProfileBinding:
    """Validate mutable workspace authority without rechecking certification."""
    try:
        workspace_binding = store.get_workspace_agentic_profile_binding(
            binding.workspace_binding_id
        )
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("workspace_profile_binding_disabled") from error
    if workspace_binding.workspace_id != binding.workspace_id or not workspace_binding.enabled:
        raise CapabilityCertificateError("workspace_profile_binding_disabled")
    if (
        workspace_binding.egress_policy_id != binding.egress_policy_id
        or workspace_binding.egress_policy_revision != binding.egress_policy_revision
    ):
        raise CapabilityCertificateError("egress_policy_drift_unresolved")
    definition_status = store.get_agentic_profile_definition_status(
        binding.profile_definition_id,
        binding.profile_definition_revision,
    )
    if definition_status is None and not allow_inactive_definition:
        raise CapabilityCertificateError("profile_definition_invalid")
    if definition_status is not None and definition_status.rollout_status == "disabled":
        raise CapabilityCertificateError("profile_definition_invalid")
    if definition_status is not None and (
        definition_status.rollout_status == "suspended"
        and not allow_inactive_definition
    ):
        raise CapabilityCertificateError("profile_definition_invalid")
    if binding.credential_binding_id:
        credential = resolve_provider_binding(
            store,
            provider_id=binding.model_provider_id,
            workspace_id=binding.workspace_id,
            binding_id=binding.credential_binding_id,
        )
        if credential is None:
            raise CapabilityCertificateError("credential_binding_unavailable")
    return workspace_binding


def intersect_runtime_policies(*policies: AgenticRuntimePolicy) -> AgenticRuntimePolicy:
    """Return the greatest restriction common to every supplied policy."""
    if not policies:
        raise ValueError("At least one runtime policy is required.")
    for policy in policies:
        _validate_policy(policy)
    finite_costs = [value for value in (item.max_estimated_cost_microusd for item in policies) if value is not None]
    tool_mode, tool_handles = _intersect_tool_policy(policies)
    return AgenticRuntimePolicy(
        max_steps_per_turn=min(item.max_steps_per_turn for item in policies),
        max_tool_calls_per_turn=min(item.max_tool_calls_per_turn for item in policies),
        max_parallel_tool_calls=min(item.max_parallel_tool_calls for item in policies),
        max_wall_time_seconds=min(item.max_wall_time_seconds for item in policies),
        max_tool_result_bytes=min(item.max_tool_result_bytes for item in policies),
        max_total_tool_result_bytes=min(item.max_total_tool_result_bytes for item in policies),
        max_input_tokens=min(item.max_input_tokens for item in policies),
        max_output_tokens=min(item.max_output_tokens for item in policies),
        max_estimated_cost_microusd=min(finite_costs) if finite_costs else None,
        allowed_surface_kinds=_tuple_intersection(*(item.allowed_surface_kinds for item in policies)),
        tool_handle_mode=tool_mode,
        allowed_tool_handles=tool_handles,
        allow_filesystem_list=all(item.allow_filesystem_list for item in policies),
        allow_filesystem_read=all(item.allow_filesystem_read for item in policies),
        allow_filesystem_write=all(item.allow_filesystem_write for item in policies),
        allow_shell=all(item.allow_shell for item in policies),
        require_confirmation_for_mutating=any(item.require_confirmation_for_mutating for item in policies),
        require_confirmation_for_destructive=any(item.require_confirmation_for_destructive for item in policies),
        allowed_remote_data_classes=_tuple_intersection(
            *(item.allowed_remote_data_classes for item in policies)
        ),
    )


def effective_authority_audit_payload(authority: EffectiveRuntimeAuthority) -> dict[str, object]:
    """Return the redaction-safe persisted projection of ephemeral authority."""
    capabilities = authority.allowed_capabilities
    return {
        "execution_binding_id": authority.execution_binding_id,
        "certificate_id": authority.certificate_id,
        "authority_digest": authority.authority_digest,
        "execution_mode": authority.execution_mode,
        "egress_policy_id": authority.egress_policy_id,
        "policy_revision_set": authority.policy_revision_set,
        "health_revision": authority.health_revision,
        "allowed_tool_handle_count": len(authority.allowed_tool_handles),
        "allowed_capabilities": tuple(
            name
            for name, value in capabilities.__dict__.items()
            if value is True
        ),
    }


def _narrow_capabilities(
    certified: RuntimeCapabilitySet,
    policy: AgenticRuntimePolicy,
) -> RuntimeCapabilitySet:
    surfaces = set(policy.allowed_surface_kinds)
    tools_allowed = (
        policy.max_tool_calls_per_turn > 0
        and bool(surfaces)
        and policy.tool_handle_mode != "none"
    )
    return replace(
        certified,
        tool_orchestration=certified.tool_orchestration and tools_allowed,
        cli=certified.cli and "cli" in surfaces,
        mcp=certified.mcp and "mcp" in surfaces,
        skill_catalog=certified.skill_catalog and tools_allowed,
        filesystem_list=certified.filesystem_list and policy.allow_filesystem_list,
        filesystem_read=certified.filesystem_read and policy.allow_filesystem_read,
        filesystem_write=certified.filesystem_write and policy.allow_filesystem_write,
        shell=certified.shell and policy.allow_shell,
    )


def _allowed_tool_handles(current: tuple[str, ...], *policies: AgenticRuntimePolicy) -> tuple[str, ...]:
    allowed = set(current)
    for policy in policies:
        if policy.tool_handle_mode == "none":
            return ()
        if policy.tool_handle_mode == "exact":
            allowed.intersection_update(policy.allowed_tool_handles)
    return tuple(item for item in current if item in allowed)


def _intersect_tool_policy(
    policies: tuple[AgenticRuntimePolicy, ...],
) -> tuple[str, tuple[str, ...]]:
    if any(item.tool_handle_mode == "none" for item in policies):
        return "none", ()
    exact = [item.allowed_tool_handles for item in policies if item.tool_handle_mode == "exact"]
    if not exact:
        return "all_currently_authorized", ()
    handles = _tuple_intersection(*exact)
    return ("exact", handles) if handles else ("none", ())


def _tuple_intersection(*values: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        return ()
    allowed = set(values[0])
    for items in values[1:]:
        allowed.intersection_update(items)
    return tuple(item for item in values[0] if item in allowed)


def _validate_policy(policy: AgenticRuntimePolicy) -> None:
    positive = (
        policy.max_steps_per_turn,
        policy.max_tool_calls_per_turn,
        policy.max_wall_time_seconds,
        policy.max_tool_result_bytes,
        policy.max_total_tool_result_bytes,
        policy.max_input_tokens,
        policy.max_output_tokens,
    )
    if any(value <= 0 for value in positive) or policy.max_parallel_tool_calls < 0:
        raise CapabilityCertificateError("runtime_policy_limit_invalid")
    if policy.max_parallel_tool_calls > 0 and not parallel_tool_calls_enabled():
        raise CapabilityCertificateError("parallel_tool_calls_disabled")
    if policy.max_estimated_cost_microusd is not None and policy.max_estimated_cost_microusd < 0:
        raise CapabilityCertificateError("runtime_policy_cost_invalid")
    if policy.tool_handle_mode == "none" and policy.allowed_tool_handles:
        raise CapabilityCertificateError("runtime_policy_tool_handles_invalid")
    if policy.tool_handle_mode == "exact":
        if not policy.allowed_tool_handles or any("*" in value for value in policy.allowed_tool_handles):
            raise CapabilityCertificateError("runtime_policy_tool_handles_invalid")
