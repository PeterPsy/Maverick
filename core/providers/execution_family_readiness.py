"""Fail-closed readiness for profiles shown in the agentic UI families."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.certified_execution_tcb import is_exact_codex_identity
from core.providers.errors import ProviderNotFoundError
from core.providers.execution_families import (
    MAVERICK_AGENT_EXECUTION_FAMILY,
    NATIVE_AGENT_EXECUTION_FAMILY,
    effective_agentic_execution_family,
)
from core.providers.native_agent_catalog import (
    native_agent_model_available,
    native_agent_model_provider_connected,
)
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
    inspect_full_workspace_contract,
)


@dataclass(frozen=True)
class AgenticFamilyReadiness:
    """Structural family and Full Workspace posture for one exact profile."""

    execution_family: str
    contract_status: str
    full_workspace_contract_revision: str | None
    harness_recipe_id: str | None
    harness_recipe_revision: str | None
    harness_recipe_digest: str | None
    provider_capability_catalog_digest: str | None
    reason_code: str | None

    @property
    def complete(self) -> bool:
        return self.contract_status == "complete" and self.reason_code is None


def inspect_agentic_family_readiness(
    *,
    definition,
    certificate,
    binding,
    registry,
) -> AgenticFamilyReadiness:
    """Classify one agent only from trusted identities and complete contracts."""
    family = effective_agentic_execution_family(
        definition.execution_family,
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        model_provider_id=definition.model_provider_id,
        provider_protocol=definition.provider_protocol,
    )
    if family == NATIVE_AGENT_EXECUTION_FAMILY:
        return _native_readiness(
            definition=definition,
            certificate=certificate,
            binding=binding,
            registry=registry,
        )
    if family == MAVERICK_AGENT_EXECUTION_FAMILY:
        return _maverick_readiness(
            definition=definition,
            certificate=certificate,
            binding=binding,
        )
    return _incomplete(family, "execution_family_unclassified")


def _native_readiness(*, definition, certificate, binding, registry) -> AgenticFamilyReadiness:
    try:
        installation = registry.get_native_agent_installation(
            definition.runtime_engine_id
        )
    except ProviderNotFoundError:
        return _incomplete(
            NATIVE_AGENT_EXECUTION_FAMILY,
            "native_agent_installation_missing",
        )
    manifest = installation.manifest
    recipe = installation.recipe
    full_revision = installation.certificate.full_workspace_contract_revision
    identity_matches = (
        installation.release_eligible
        and manifest.runtime_engine_id == definition.runtime_engine_id
        and manifest.adapter_id == definition.adapter_id
        and definition.adapter_version_constraint == f"=={manifest.adapter_version}"
        and manifest.protocol_id == definition.provider_protocol
        and native_agent_model_provider_connected(
            installation,
            model_provider_id=definition.model_provider_id,
        )
        and installation.effects.workspace_confined
        and installation.effects.process_tree_supervised
        and installation.effects.structured_effect_events
        and manifest.machine_readable
        and not manifest.human_terminal_scraping
        and full_revision == FULL_WORKSPACE_CONTRACT_REVISION
    )
    if not identity_matches:
        return _native_result(installation, "native_agent_contract_incomplete")
    if not native_agent_model_available(
        registry,
        installation,
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
    ):
        return _native_result(installation, "native_agent_model_unavailable")
    legacy_codex = is_exact_codex_identity(
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=definition.adapter_id,
        model_provider_id=definition.model_provider_id,
        provider_protocol=definition.provider_protocol,
    )
    policy = _effective_binding_policy(definition, binding)
    if not legacy_codex:
        if not _native_profile_identity_matches(
            definition=definition,
            certificate=certificate,
            installation=installation,
        ):
            return _native_result(
                installation,
                "native_agent_profile_identity_incomplete",
            )
        if not inspect_full_workspace_contract(
            capabilities=certificate.certified_capabilities,
            policy=policy,
        ).complete:
            return _native_result(installation, "full_workspace_contract_incomplete")
    if not _policy_retains_full_workspace_surfaces(policy):
        return _native_result(installation, "full_workspace_policy_incomplete")
    return _native_result(installation, None)


def _native_profile_identity_matches(*, definition, certificate, installation) -> bool:
    if certificate is None:
        return False
    recipe = installation.recipe
    full_revision = installation.certificate.full_workspace_contract_revision
    expected = (
        NATIVE_AGENT_EXECUTION_FAMILY,
        full_revision,
        recipe.recipe_id,
        recipe.revision,
        recipe.digest,
    )
    definition_identity = (
        definition.execution_family,
        definition.full_workspace_contract_revision,
        definition.harness_recipe_id,
        definition.harness_recipe_revision,
        definition.harness_recipe_digest,
    )
    certificate_identity = (
        certificate.execution_family,
        certificate.full_workspace_contract_revision,
        certificate.harness_recipe_id,
        certificate.harness_recipe_revision,
        certificate.harness_recipe_digest,
    )
    certificate_execution_identity = (
        certificate.runtime_engine_id,
        certificate.adapter_id,
        certificate.adapter_version,
        certificate.model_provider_id,
        certificate.model_id,
        certificate.provider_protocol,
    )
    expected_execution_identity = (
        definition.runtime_engine_id,
        installation.manifest.adapter_id,
        installation.manifest.adapter_version,
        definition.model_provider_id,
        definition.model_id,
        installation.manifest.protocol_id,
    )
    return (
        definition_identity == expected
        and certificate_identity == expected
        and certificate_execution_identity == expected_execution_identity
    )


def _native_result(installation, reason_code: str | None) -> AgenticFamilyReadiness:
    recipe = installation.recipe
    return AgenticFamilyReadiness(
        execution_family=NATIVE_AGENT_EXECUTION_FAMILY,
        contract_status="complete" if reason_code is None else "incomplete",
        full_workspace_contract_revision=(
            installation.certificate.full_workspace_contract_revision
        ),
        harness_recipe_id=recipe.recipe_id,
        harness_recipe_revision=recipe.revision,
        harness_recipe_digest=recipe.digest,
        provider_capability_catalog_digest=None,
        reason_code=reason_code,
    )


def _maverick_readiness(*, definition, certificate, binding) -> AgenticFamilyReadiness:
    identity = (
        definition.full_workspace_contract_revision,
        definition.harness_recipe_id,
        definition.harness_recipe_revision,
        definition.harness_recipe_digest,
        definition.provider_capability_catalog_digest,
        definition.provider_config_id,
        definition.provider_config_revision,
        definition.provider_config_digest,
        definition.protocol_adapter_id,
        definition.protocol_adapter_version,
    )
    if certificate is None:
        return _maverick_result(definition, "maverick_agent_certificate_missing")
    certificate_identity = (
        certificate.full_workspace_contract_revision,
        certificate.harness_recipe_id,
        certificate.harness_recipe_revision,
        certificate.harness_recipe_digest,
        certificate.provider_capability_catalog_digest,
        certificate.provider_config_id,
        certificate.provider_config_revision,
        certificate.provider_config_digest,
        certificate.protocol_adapter_id,
        certificate.protocol_adapter_version,
    )
    if (
        definition.execution_family != MAVERICK_AGENT_EXECUTION_FAMILY
        or certificate.execution_family != MAVERICK_AGENT_EXECUTION_FAMILY
        or identity != certificate_identity
        or identity[0] != FULL_WORKSPACE_CONTRACT_REVISION
        or not all(str(value or "").strip() for value in identity)
        or len(definition.provider_config_digest) != 64
    ):
        return _maverick_result(definition, "maverick_agent_contract_incomplete")
    policy = _effective_binding_policy(definition, binding)
    report = inspect_full_workspace_contract(
        capabilities=certificate.certified_capabilities,
        policy=policy,
    )
    if not report.complete:
        return _maverick_result(definition, "full_workspace_policy_incomplete")
    return _maverick_result(definition, None)


def _maverick_result(definition, reason_code: str | None) -> AgenticFamilyReadiness:
    return AgenticFamilyReadiness(
        execution_family=MAVERICK_AGENT_EXECUTION_FAMILY,
        contract_status="complete" if reason_code is None else "incomplete",
        full_workspace_contract_revision=(
            str(definition.full_workspace_contract_revision or "") or None
        ),
        harness_recipe_id=str(definition.harness_recipe_id or "") or None,
        harness_recipe_revision=(
            str(definition.harness_recipe_revision or "") or None
        ),
        harness_recipe_digest=str(definition.harness_recipe_digest or "") or None,
        provider_capability_catalog_digest=(
            str(definition.provider_capability_catalog_digest or "") or None
        ),
        reason_code=reason_code,
    )


def _policy_retains_full_workspace_surfaces(policy) -> bool:
    handles_complete = (
        policy.tool_handle_mode == "all_currently_authorized"
        or (
            policy.tool_handle_mode == "exact"
            and set(FULL_WORKSPACE_CORE_TOOL_HANDLES).issubset(
                policy.allowed_tool_handles
            )
        )
    )
    return bool(
        handles_complete
        and policy.allow_filesystem_list
        and policy.allow_filesystem_read
        and policy.allow_filesystem_write
        and policy.allow_shell
        and {"cli", "mcp", "app-interface", "core-capability"}.issubset(
            policy.allowed_surface_kinds
        )
    )


def _effective_binding_policy(definition, binding):
    if binding is None:
        return definition.policy_ceiling
    policy = getattr(binding, "workspace_policy_ceiling", None)
    if policy is None:
        policy = getattr(binding, "workspace_policy_ceiling_snapshot", None)
    return policy or definition.policy_ceiling


def _incomplete(family: str, reason_code: str) -> AgenticFamilyReadiness:
    return AgenticFamilyReadiness(
        execution_family=family,
        contract_status="unclassified" if not family else "incomplete",
        full_workspace_contract_revision=None,
        harness_recipe_id=None,
        harness_recipe_revision=None,
        harness_recipe_digest=None,
        provider_capability_catalog_digest=None,
        reason_code=reason_code,
    )


__all__ = ["AgenticFamilyReadiness", "inspect_agentic_family_readiness"]
