"""One monotonic lattice for certified or explicitly granted ceilings.

The caller must validate its authorization base first. This calculation neither
validates a certificate nor turns an experimental grant into certification.
"""

from dataclasses import dataclass

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import AgenticRuntimePolicy, WorkspaceAgenticProfileBinding
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.errors import CapabilityCertificateError
from core.providers.certified_execution_tcb import is_exact_codex_identity
from core.runtime.full_workspace_contract import validate_full_workspace_live_authority


@dataclass(frozen=True)
class RestrictedRuntimeCeiling:
    capabilities: RuntimeCapabilitySet
    tool_handles: tuple[str, ...]
    execution_mode: ExecutionMode
    policy: AgenticRuntimePolicy
    workspace_binding: WorkspaceAgenticProfileBinding
    feature_revision: str


def restrict_runtime_authority_ceiling(
    store, *, binding, capability_ceiling: RuntimeCapabilitySet,
    currently_authorized_tool_handles: tuple[str, ...] = (),
    live_execution_mode: ExecutionMode | None = None, health_status: str = "healthy",
    actor_policy_allowed: bool = True,
    additional_policy_ceilings: tuple[AgenticRuntimePolicy, ...] = (),
) -> RestrictedRuntimeCeiling:
    from core.runtime.authority import (
        validate_live_runtime_binding_governance, intersect_runtime_policies,
        _narrow_capabilities, _feature_capability_ceiling, _health_capability_ceiling,
        _execution_mode_capability_ceiling, intersect_runtime_capabilities,
        _confirmation_capability_ceiling, _allowed_tool_handles,
        _narrow_handles_to_capabilities, _narrow_capabilities_to_live_handles,
    )
    if health_status not in {"healthy", "degraded"}:
        raise CapabilityCertificateError("runtime_health_unavailable")
    if not actor_policy_allowed:
        raise CapabilityCertificateError("runtime_actor_policy_denied")
    workspace_binding = validate_live_runtime_binding_governance(
        store,
        binding=binding,
    )
    policy = intersect_runtime_policies(
        binding.profile_policy_ceiling_snapshot,
        binding.workspace_policy_ceiling_snapshot,
        workspace_binding.workspace_policy_ceiling,
        *additional_policy_ceilings,
    )
    policy_capabilities = _narrow_capabilities(
        capability_ceiling,
        policy,
    )
    feature_capabilities, feature_revision = _feature_capability_ceiling(
        binding,
        capability_ceiling,
    )
    health_capabilities = _health_capability_ceiling(
        capability_ceiling,
        health_status=health_status,
    )
    execution_mode: ExecutionMode = (
        "sandbox"
        if "sandbox" in {binding.execution_mode, live_execution_mode}
        else "full-access"
    )
    execution_mode_capabilities = _execution_mode_capability_ceiling(
        capability_ceiling,
        execution_mode=execution_mode,
    )
    capabilities = intersect_runtime_capabilities(
        capability_ceiling,
        policy_capabilities,
        feature_capabilities,
        health_capabilities,
        execution_mode_capabilities,
    )
    capabilities = _confirmation_capability_ceiling(capabilities, policy)
    tool_handles = _allowed_tool_handles(
        currently_authorized_tool_handles,
        binding.profile_policy_ceiling_snapshot,
        binding.workspace_policy_ceiling_snapshot,
        workspace_binding.workspace_policy_ceiling,
        *additional_policy_ceilings,
    )
    if not capabilities.tool_orchestration:
        tool_handles = ()
    else:
        tool_handles = _narrow_handles_to_capabilities(tool_handles, capabilities)
    exact_codex = is_exact_codex_identity(
        runtime_engine_id=binding.runtime_engine_id,
        adapter_id=binding.adapter_id,
        model_provider_id=binding.model_provider_id,
        provider_protocol=binding.provider_protocol,
    )
    # The exact local Codex app-server contract predates a live catalog API.
    # Hosted runtimes, by contrast, treat an empty live handle set as no tool
    # authority rather than as permission to fall back to the certificate.
    if tool_handles or not exact_codex:
        capabilities = _narrow_capabilities_to_live_handles(
            capabilities,
            tool_handles,
        )
    validate_full_workspace_live_authority(
        revision=binding.full_workspace_contract_revision,
        capabilities=capabilities,
        policy=policy,
        allowed_handles=tool_handles,
    )
    return RestrictedRuntimeCeiling(capabilities, tool_handles, execution_mode, policy, workspace_binding, feature_revision)
