"""Code-owned Full Workspace Agent Contract derived from the Codex baseline."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.errors import CapabilityCertificateError


FULL_WORKSPACE_CONTRACT_REVISION = "codex-baseline-v18"
MAVERICK_AGENT_EXECUTION_FAMILY = "maverick_agent"
MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY = "maverick_agent_candidate"

FULL_WORKSPACE_CORE_TOOL_HANDLES = (
    "core-capability:workspace.instructions",
    "core-capability:filesystem.list",
    "core-capability:filesystem.search",
    "core-capability:filesystem.read",
    "core-capability:filesystem.write",
    "core-capability:filesystem.edit",
    "core-capability:filesystem.patch",
    "core-capability:filesystem.move",
    "core-capability:filesystem.delete",
    "core-capability:shell.run",
    "core-capability:process.start",
    "core-capability:process.status",
    "core-capability:process.input",
    "core-capability:process.interrupt",
    "core-capability:cli.list",
    "core-capability:cli.run",
    "core-capability:mcp.list",
    "core-capability:mcp.call",
    "core-capability:artifact.read",
)
FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS = (
    "core-capability:filesystem.write:create",
    "core-capability:filesystem.write:replace",
    "core-capability:filesystem.edit",
    "core-capability:filesystem.patch",
    "core-capability:filesystem.move",
    "core-capability:filesystem.delete",
    "core-capability:filesystem.read-after-write",
    "core-capability:shell.run",
    "core-capability:process.start",
    "core-capability:process.status",
    "core-capability:process.input",
    "core-capability:process.interrupt",
    "core-capability:cli.list",
    "core-capability:cli.run",
    "core-capability:mcp.list",
    "core-capability:mcp.call",
    "collaboration:cli-create-mcp-wait",
    "security:filesystem.marker-narrowing",
    "security:filesystem.revoke-rebuild",
    "security:tool-result.revoke-egress",
    "security:request.revoke-transport",
    "security:stream.revoke-advance",
    "security:workspace-effect.revoke-commit",
    "security:workspace.git-masked",
)


@dataclass(frozen=True)
class FullWorkspaceContractReport:
    """Redaction-safe validation result for one claimed full agent profile."""

    revision: str
    required_handles: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    missing_handles: tuple[str, ...]
    missing_result_behaviors: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return (
            not self.missing_capabilities
            and not self.missing_handles
            and not self.missing_result_behaviors
        )


def inspect_full_workspace_contract(
    *,
    capabilities,
    policy,
    allowed_handles: tuple[str, ...] | None = None,
) -> FullWorkspaceContractReport:
    """Compare claims with capabilities and the executable result-policy gate."""
    required_capabilities = {
        "streaming": capabilities.streaming,
        "tool_orchestration": capabilities.tool_orchestration,
        "cli": capabilities.cli,
        "mcp": capabilities.mcp,
        "skill_catalog": capabilities.skill_catalog,
        "filesystem_list": capabilities.filesystem_list,
        "filesystem_read": capabilities.filesystem_read,
        "filesystem_write": capabilities.filesystem_write,
        "shell": capabilities.shell,
        "interrupt": capabilities.interrupt,
        "recovery": capabilities.recovery,
        "confirmation_resume": capabilities.confirmation_resume,
        "app_references": capabilities.app_references,
        "confirmations": capabilities.confirmations,
        "attachment:file": "file" in capabilities.attachment_modalities,
        "policy:confirm_mutating": policy.require_confirmation_for_mutating,
        "policy:confirm_destructive": policy.require_confirmation_for_destructive,
        "policy:core_capability_surface": (
            "core-capability" in policy.allowed_surface_kinds
        ),
        "policy:public_result_pairing": (
            "public" in policy.allowed_remote_data_classes
        ),
    }
    missing_capabilities = tuple(
        name for name, enabled in required_capabilities.items() if not enabled
    )
    if allowed_handles is not None:
        allowed = set(allowed_handles)
        missing_handles = tuple(
            handle for handle in FULL_WORKSPACE_CORE_TOOL_HANDLES if handle not in allowed
        )
    elif policy.tool_handle_mode == "all_currently_authorized":
        missing_handles: tuple[str, ...] = ()
    elif policy.tool_handle_mode == "exact":
        allowed = set(policy.allowed_tool_handles)
        missing_handles = tuple(
            handle for handle in FULL_WORKSPACE_CORE_TOOL_HANDLES if handle not in allowed
        )
    else:
        missing_handles = FULL_WORKSPACE_CORE_TOOL_HANDLES
    verified_result_behaviors = set(_hosted_tool_result_behaviors())
    missing_result_behaviors = tuple(
        handle
        for handle in FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS
        if handle not in verified_result_behaviors
    )
    return FullWorkspaceContractReport(
        revision=FULL_WORKSPACE_CONTRACT_REVISION,
        required_handles=FULL_WORKSPACE_CORE_TOOL_HANDLES,
        missing_capabilities=missing_capabilities,
        missing_handles=missing_handles,
        missing_result_behaviors=missing_result_behaviors,
    )


def validate_full_workspace_contract_claim(*, profile, certificate) -> None:
    """Reject a partial profile that claims the common full-workspace revision."""
    profile_revision = str(
        getattr(profile, "full_workspace_contract_revision", "") or ""
    )
    certificate_revision = str(
        getattr(certificate, "full_workspace_contract_revision", "") or ""
    )
    profile_family = str(getattr(profile, "execution_family", "") or "")
    certificate_family = str(
        getattr(certificate, "execution_family", "") or ""
    )
    if profile_family != certificate_family:
        raise CapabilityCertificateError("full_workspace_execution_family_mismatch")
    if (
        profile_family == MAVERICK_AGENT_EXECUTION_FAMILY
        and (not profile_revision or not certificate_revision)
    ):
        raise CapabilityCertificateError(
            "full_workspace_execution_family_contract_required"
        )
    if (
        profile_family == MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY
        and (profile_revision or certificate_revision)
    ):
        raise CapabilityCertificateError(
            "full_workspace_candidate_contract_forbidden"
        )
    if not profile_revision and not certificate_revision:
        return
    if profile_revision != certificate_revision:
        raise CapabilityCertificateError("full_workspace_contract_identity_mismatch")
    if profile_revision != FULL_WORKSPACE_CONTRACT_REVISION:
        raise CapabilityCertificateError("full_workspace_contract_revision_unknown")
    context_policy = getattr(profile, "context_policy", None)
    required_profile_identity = (
        getattr(profile, "execution_family", ""),
        getattr(profile, "harness_recipe_id", ""),
        getattr(profile, "harness_recipe_revision", ""),
        getattr(profile, "harness_recipe_digest", ""),
        getattr(profile, "provider_capability_catalog_digest", ""),
        getattr(profile, "semantic_projection_compiler_revision", ""),
        getattr(profile, "tool_contract_revision", ""),
    )
    if (
        context_policy is None
        or context_policy.compaction_mode != "provider_history"
        or context_policy.max_request_input_tokens <= 0
        or context_policy.context_reserve_tokens <= 0
        or context_policy.compaction_trigger_tokens <= 0
        or context_policy.max_compacted_state_bytes <= 0
        or context_policy.summary_max_bytes <= 0
        or context_policy.tool_result_inline_bytes <= 0
        or context_policy.tool_result_summary_bytes <= 0
        or getattr(profile, "tool_contract_revision", "")
        != FULL_WORKSPACE_CONTRACT_REVISION
        or not all(str(value or "").strip() for value in required_profile_identity)
    ):
        raise CapabilityCertificateError("full_workspace_context_contract_incomplete")
    report = inspect_full_workspace_contract(
        capabilities=certificate.certified_capabilities,
        policy=profile.policy_ceiling,
    )
    if not report.complete:
        raise CapabilityCertificateError("full_workspace_contract_incomplete")


def validate_full_workspace_binding(*, certificate, binding) -> None:
    """Require an immutable session pin to retain the certificate contract id."""
    certificate_revision = str(
        getattr(certificate, "full_workspace_contract_revision", "") or ""
    )
    binding_revision = str(
        getattr(binding, "full_workspace_contract_revision", "") or ""
    )
    if certificate_revision != binding_revision:
        raise CapabilityCertificateError("full_workspace_contract_binding_mismatch")


def validate_full_workspace_live_authority(
    *,
    revision: str,
    capabilities,
    policy,
    allowed_handles: tuple[str, ...],
) -> None:
    """Fail atomically when live governance removes any required capability."""
    if not revision:
        return
    if revision != FULL_WORKSPACE_CONTRACT_REVISION:
        raise CapabilityCertificateError("full_workspace_contract_revision_unknown")
    report = inspect_full_workspace_contract(
        capabilities=capabilities,
        policy=policy,
        allowed_handles=allowed_handles,
    )
    if not report.complete:
        raise CapabilityCertificateError(
            "full_workspace_contract_live_authority_incomplete"
        )


def _hosted_tool_result_behaviors() -> tuple[str, ...]:
    # Import lazily: result admission depends on the tool catalog, whose
    # authority path imports certificate validation and therefore this module.
    from core.runtime.hosted_tool_result_behavior import (
        inspect_hosted_tool_result_behavior,
    )

    return inspect_hosted_tool_result_behavior()


__all__ = [
    "FULL_WORKSPACE_CONTRACT_REVISION",
    "FULL_WORKSPACE_CORE_TOOL_HANDLES",
    "FULL_WORKSPACE_REQUIRED_RESULT_BEHAVIORS",
    "MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY",
    "MAVERICK_AGENT_EXECUTION_FAMILY",
    "FullWorkspaceContractReport",
    "inspect_full_workspace_contract",
    "validate_full_workspace_binding",
    "validate_full_workspace_contract_claim",
    "validate_full_workspace_live_authority",
]
