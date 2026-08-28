"""Monotonic live authority calculation for pinned agentic turns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import (
    AgenticRuntimePolicy,
    WorkspaceAgenticProfileBinding,
)
from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.certificate_service import validate_certificate_for_binding
from core.providers.certified_execution_tcb import is_exact_codex_identity
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from core.runtime.failure_messages import public_runtime_failure_reason_code
from core.runtime.full_workspace_contract import (
    validate_full_workspace_live_authority,
)
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    feature_enabled,
    parallel_tool_calls_enabled,
    provider_preview_feature,
)


_CLIENT_AUTHORITY_FIELDS = frozenset(
    {
        "agentic_egress_policy_id",
        "allowed_remote_data_classes",
        "attestation",
        "attestation_id",
        "attestation_revision",
        "classification",
        "classification_revision",
        "data_attestation",
        "data_class",
        "effective_data_class",
        "egress_policy_id",
        "egress_policy_revision",
        "source_data_class",
        "trust_level",
    }
)


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
    actor_policy_allowed: bool = True
    actor_policy_revision: str = "runtime-actor:unknown"
    feature_flag_revision: str = "runtime-features:unknown"
    provider_health_status: str = "healthy"
    provider_id: str = ""
    model_id: str = ""
    provider_protocol: str = ""
    certified_upstream_ids: tuple[str, ...] = ()
    effective_upstream_ids: tuple[str, ...] = ()
    allowed_remote_data_classes: tuple[str, ...] = ()
    data_collection_policy: str = "deny"
    require_zdr: bool = False
    certificate_suite_id: str = ""
    certificate_suite_version: str = ""
    certificate_expires_at: datetime | None = None
    tcb_manifest_id: str = ""
    tcb_manifest_version: str = ""
    tcb_structure_digest: str = ""
    tcb_live_digest: str = ""
    tcb_posture: str = "unavailable"
    full_workspace_contract_revision: str = ""
    execution_family: str = ""
    harness_recipe_id: str = ""
    harness_recipe_revision: str = ""
    harness_recipe_digest: str = ""
    provider_capability_catalog_digest: str = ""
    semantic_projection_compiler_revision: str = ""
    tool_contract_revision: str = ""
    context_policy_revision: str = ""


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
    actor_policy_allowed: bool = True,
    actor_policy_revision: str = "runtime-actor:unknown",
    now: datetime | None = None,
    adapter_artifact_digest: str | None = None,
) -> EffectiveRuntimeAuthority:
    """Intersect certified capability with every pinned and live restriction."""
    timestamp = now or datetime.now(tz=UTC)
    certificate = validate_certificate_for_binding(
        store,
        binding=binding,
        adapter=adapter,
        observed_upstream_id=observed_upstream_id,
        now=timestamp,
        adapter_artifact_digest=adapter_artifact_digest,
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
    )
    policy_capabilities = _narrow_capabilities(
        certificate.certified_capabilities,
        policy,
    )
    feature_capabilities, feature_revision = _feature_capability_ceiling(
        binding,
        certificate.certified_capabilities,
    )
    health_capabilities = _health_capability_ceiling(
        certificate.certified_capabilities,
        health_status=health_status,
    )
    execution_mode: ExecutionMode = (
        "sandbox"
        if "sandbox" in {binding.execution_mode, live_execution_mode}
        else "full-access"
    )
    execution_mode_capabilities = _execution_mode_capability_ceiling(
        certificate.certified_capabilities,
        execution_mode=execution_mode,
    )
    capabilities = intersect_runtime_capabilities(
        certificate.certified_capabilities,
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
    status = store.get_capability_certificate_status(certificate.certificate_id)
    status_revision = 0 if status is None else status.revision
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
        actor_policy_allowed=True,
        actor_policy_revision=str(actor_policy_revision or "runtime-actor:unknown"),
        feature_flag_revision=feature_revision,
        provider_health_status=health_status,
        provider_id=binding.model_provider_id,
        model_id=binding.model_id,
        provider_protocol=binding.provider_protocol,
        certified_upstream_ids=tuple(certificate.certified_upstream_ids),
        effective_upstream_ids=tuple(
            item
            for item in binding.routing_constraint_snapshot.allowed_upstream_ids
            if item in certificate.certified_upstream_ids
        ),
        allowed_remote_data_classes=policy.allowed_remote_data_classes,
        data_collection_policy=binding.routing_constraint_snapshot.data_collection_policy,
        require_zdr=binding.routing_constraint_snapshot.require_zdr,
        certificate_suite_id=certificate.suite_id,
        certificate_suite_version=certificate.suite_version,
        certificate_expires_at=certificate.expires_at,
        tcb_manifest_id=certificate.tcb_manifest_id,
        tcb_manifest_version=certificate.tcb_manifest_version,
        tcb_structure_digest=certificate.tcb_structure_digest,
        tcb_live_digest=certificate.tcb_live_digest,
        tcb_posture=(
            "exact_local_contract"
            if is_exact_codex_identity(
                runtime_engine_id=certificate.runtime_engine_id,
                adapter_id=certificate.adapter_id,
                model_provider_id=certificate.model_provider_id,
                provider_protocol=certificate.provider_protocol,
            )
            else "active"
        ),
        full_workspace_contract_revision=(
            binding.full_workspace_contract_revision
        ),
        execution_family=getattr(binding, "execution_family", ""),
        harness_recipe_id=getattr(binding, "harness_recipe_id", ""),
        harness_recipe_revision=getattr(binding, "harness_recipe_revision", ""),
        harness_recipe_digest=getattr(binding, "harness_recipe_digest", ""),
        provider_capability_catalog_digest=getattr(
            binding,
            "provider_capability_catalog_digest",
            "",
        ),
        semantic_projection_compiler_revision=getattr(
            binding,
            "semantic_projection_compiler_revision",
            "",
        ),
        tool_contract_revision=getattr(binding, "tool_contract_revision", ""),
        context_policy_revision=(
            ""
            if getattr(binding, "context_policy_snapshot", None) is None
            else binding.context_policy_snapshot.revision
        ),
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
        "provider_health_status": authority.provider_health_status,
        "actor_policy_revision": authority.actor_policy_revision,
        "feature_flag_revision": authority.feature_flag_revision,
        "tcb_posture": authority.tcb_posture,
        "full_workspace_contract_revision": (
            authority.full_workspace_contract_revision or None
        ),
        "execution_family": authority.execution_family or None,
        "harness_recipe": {
            "id": authority.harness_recipe_id or None,
            "revision": authority.harness_recipe_revision or None,
            "digest": authority.harness_recipe_digest or None,
            "provider_capability_catalog_digest": (
                authority.provider_capability_catalog_digest or None
            ),
        },
        "semantic_projection_compiler_revision": (
            authority.semantic_projection_compiler_revision or None
        ),
        "tool_contract_revision": authority.tool_contract_revision or None,
        "context_policy_revision": authority.context_policy_revision or None,
        "allowed_tool_handle_count": len(authority.allowed_tool_handles),
        "allowed_capabilities": tuple(
            name
            for name, value in capabilities.__dict__.items()
            if value is True
        ),
    }


def effective_runtime_capability_payload(
    authority: EffectiveRuntimeAuthority,
) -> dict[str, object]:
    """Project the one server-owned snapshot without bearer or credential authority."""
    return {
        "status": "active",
        "reason_code": None,
        "snapshot_digest": authority.authority_digest,
        "computed_at": authority.computed_at,
        "execution_mode": authority.execution_mode,
        "capabilities": asdict(authority.allowed_capabilities),
        "allowed_tool_handles": authority.allowed_tool_handles,
        "provider": {
            "provider_id": authority.provider_id,
            "model_id": authority.model_id,
            "protocol": authority.provider_protocol,
            "certified_upstream_ids": authority.certified_upstream_ids,
            "effective_upstream_ids": authority.effective_upstream_ids,
            "health_status": authority.provider_health_status,
            "health_revision": authority.health_revision,
        },
        "data_policy": {
            "allowed_remote_data_classes": authority.allowed_remote_data_classes,
            "collection": authority.data_collection_policy,
            "require_zdr": authority.require_zdr,
        },
        "certificate": {
            "certificate_id": authority.certificate_id,
            "suite_id": authority.certificate_suite_id,
            "suite_version": authority.certificate_suite_version,
            "expires_at": authority.certificate_expires_at,
        },
        "tcb": {
            "manifest_id": authority.tcb_manifest_id or None,
            "manifest_version": authority.tcb_manifest_version or None,
            "structure_digest": authority.tcb_structure_digest or None,
            "live_digest": authority.tcb_live_digest or None,
            "posture": authority.tcb_posture,
        },
        "full_workspace_contract_revision": (
            authority.full_workspace_contract_revision or None
        ),
        "execution_family": authority.execution_family or None,
        "harness_recipe": {
            "id": authority.harness_recipe_id or None,
            "revision": authority.harness_recipe_revision or None,
            "digest": authority.harness_recipe_digest or None,
            "provider_capability_catalog_digest": (
                authority.provider_capability_catalog_digest or None
            ),
        },
        "semantic_projection_compiler_revision": (
            authority.semantic_projection_compiler_revision or None
        ),
        "tool_contract_revision": authority.tool_contract_revision or None,
        "context_policy_revision": authority.context_policy_revision or None,
        "policy_revisions": authority.policy_revision_set,
        "actor_policy_revision": authority.actor_policy_revision,
        "feature_flag_revision": authority.feature_flag_revision,
    }


def blocked_runtime_capability_payload(
    reason_code: str,
    *,
    certified_capabilities: RuntimeCapabilitySet | None = None,
) -> dict[str, object]:
    """Return a fail-closed UI/API snapshot when live authority is unavailable."""
    reference = certified_capabilities or RuntimeCapabilitySet(
        streaming=False,
        tool_orchestration=False,
        cli=False,
        mcp=False,
        skill_catalog=False,
        filesystem_list=False,
        filesystem_read=False,
        filesystem_write=False,
        shell=False,
        interrupt=False,
        same_turn_steering=False,
        recovery=False,
        confirmation_resume=False,
        provider_private_state=False,
        attachment_modalities=(),
        app_references=False,
        confirmations=False,
    )
    capabilities = _disabled_capabilities(reference)
    normalized_reason = public_runtime_failure_reason_code(reason_code)
    digest_payload = {
        "status": "blocked",
        "reason_code": normalized_reason,
        "capabilities": capabilities,
    }
    return {
        "status": "blocked",
        "reason_code": normalized_reason,
        "snapshot_digest": canonical_digest(digest_payload),
        "capabilities": asdict(capabilities),
        "provider": {"health_status": "unavailable"},
        "data_policy": {
            "allowed_remote_data_classes": (),
            "collection": "deny",
            "require_zdr": False,
        },
        "certificate": {},
        "tcb": {"posture": "ineligible"},
        "allowed_tool_handles": (),
    }


def validate_effective_context_capabilities(
    authority: EffectiveRuntimeAuthority,
    *,
    invoked_skills: object = (),
    attachments: object = (),
    app_references: object = (),
    requested_operations: tuple[str, ...] = (),
) -> None:
    """Reject every unsupported context item explicitly before persistence/egress."""
    validate_agentic_context_shape(
        invoked_skills=invoked_skills,
        attachments=attachments,
        app_references=app_references,
    )
    capabilities = authority.allowed_capabilities
    if _has_items(invoked_skills) and not capabilities.skill_catalog:
        raise CapabilityCertificateError("agentic_skill_catalog_not_effective")
    attachment_items = tuple(attachments or ())
    if attachment_items:
        certified_modalities = set(capabilities.attachment_modalities)
        for attachment in attachment_items:
            modality = _attachment_modality(attachment)
            if not modality:
                raise CapabilityCertificateError("agentic_attachment_metadata_invalid")
            if modality not in certified_modalities and "file" not in certified_modalities:
                raise CapabilityCertificateError(
                    "agentic_attachment_modality_not_certified"
                )
    if _has_items(app_references) and not capabilities.app_references:
        raise CapabilityCertificateError("agentic_app_references_not_effective")
    operation_capabilities = {
        "filesystem_read": capabilities.filesystem_read,
        "filesystem_write": capabilities.filesystem_write,
        "shell": capabilities.shell,
        "cli": capabilities.cli,
        "mcp": capabilities.mcp,
        "confirmation": capabilities.confirmations,
        "recovery": capabilities.recovery,
    }
    reason_codes = {
        "filesystem_read": "agentic_filesystem_read_not_effective",
        "filesystem_write": "agentic_filesystem_write_not_effective",
        "shell": "agentic_shell_not_effective",
        "cli": "agentic_cli_not_effective",
        "mcp": "agentic_mcp_not_effective",
        "confirmation": "agentic_confirmation_not_effective",
        "recovery": "agentic_recovery_not_effective",
    }
    for operation in requested_operations:
        if operation not in operation_capabilities:
            raise CapabilityCertificateError("agentic_context_operation_unknown")
        if not operation_capabilities[operation]:
            raise CapabilityCertificateError(reason_codes[operation])


def validate_agentic_context_shape(
    *,
    invoked_skills: object = (),
    attachments: object = (),
    app_references: object = (),
) -> None:
    """Reject malformed context instead of coercing or silently filtering it."""
    skill_items = _sequence_items(
        invoked_skills,
        reason_code="agentic_skill_metadata_invalid",
    )
    for item in skill_items:
        if isinstance(item, str):
            if not item.strip():
                raise CapabilityCertificateError("agentic_skill_metadata_invalid")
            continue
        skill_id = getattr(item, "skill_id", None)
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise CapabilityCertificateError("agentic_skill_metadata_invalid")
    for value, reason_code in (
        (attachments, "agentic_attachment_metadata_invalid"),
        (app_references, "agentic_app_reference_metadata_invalid"),
    ):
        items = _sequence_items(value, reason_code=reason_code)
        if any(not isinstance(item, dict) for item in items):
            raise CapabilityCertificateError(reason_code)


def reject_client_data_authority(payload: object) -> None:
    """Reject browser/app attempts to submit classification or egress authority."""
    if not isinstance(payload, dict):
        raise CapabilityCertificateError("runtime_client_authority_not_accepted")
    declared = payload.get("declared_remote_data_class")
    if declared is not None and declared != "":
        raise CapabilityCertificateError("remote_data_declaration_not_accepted")
    for key in _CLIENT_AUTHORITY_FIELDS:
        if key in payload and _client_authority_value_present(payload[key]):
            raise CapabilityCertificateError("runtime_client_authority_not_accepted")
    for field_name in ("attachments", "app_references"):
        values = payload.get(field_name)
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            if any(
                key in value and _client_authority_value_present(value[key])
                for key in _CLIENT_AUTHORITY_FIELDS
            ):
                raise CapabilityCertificateError(
                    "runtime_client_authority_not_accepted"
                )


def intersect_runtime_capabilities(
    *capabilities: RuntimeCapabilitySet,
) -> RuntimeCapabilitySet:
    """Return a monotonic intersection; no input can overstate a certificate."""
    if not capabilities:
        raise ValueError("At least one runtime capability set is required.")
    first = capabilities[0]
    boolean_fields = tuple(
        name
        for name, value in asdict(first).items()
        if isinstance(value, bool)
    )
    modalities = _tuple_intersection(
        *(item.attachment_modalities for item in capabilities)
    )
    return replace(
        first,
        **{
            field_name: all(getattr(item, field_name) for item in capabilities)
            for field_name in boolean_fields
        },
        attachment_modalities=modalities,
    )


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
        app_references=certified.app_references and "app-interface" in surfaces,
        filesystem_list=certified.filesystem_list and policy.allow_filesystem_list,
        filesystem_read=certified.filesystem_read and policy.allow_filesystem_read,
        filesystem_write=certified.filesystem_write and policy.allow_filesystem_write,
        shell=certified.shell and policy.allow_shell,
    )


def _feature_capability_ceiling(
    binding: RuntimeExecutionBinding,
    certified: RuntimeCapabilitySet,
) -> tuple[RuntimeCapabilitySet, str]:
    flag_names = (
        MAVERICK_FEATURE_AGENTIC_PROFILES,
        MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
        MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
        MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    )
    resolved = {name: feature_enabled(name) for name in flag_names}
    hosted_remote = binding.runtime_engine_id == "maverick-tool-loop"
    if hosted_remote:
        hosted_names = (
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
            MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
        )
        resolved.update({name: feature_enabled(name) for name in hosted_names})
        provider_flag = provider_preview_feature(binding.model_provider_id)
        if provider_flag is not None:
            resolved[provider_flag[0]] = feature_enabled(provider_flag[0])
    ceiling = certified
    if not (
        resolved[MAVERICK_FEATURE_AGENTIC_PROFILES]
        and resolved[MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT]
    ):
        ceiling = _disabled_capabilities(certified)
    elif hosted_remote and not all(resolved.values()):
        ceiling = _disabled_capabilities(certified)
    else:
        ceiling = replace(
            certified,
            confirmation_resume=(
                certified.confirmation_resume
                and resolved[MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION]
            ),
            confirmations=(
                certified.confirmations
                and resolved[MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION]
            ),
            provider_private_state=(
                certified.provider_private_state
                and resolved[MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE]
            ),
        )
    revision = f"runtime-features:{canonical_digest(resolved)}"
    return ceiling, revision


def _health_capability_ceiling(
    certified: RuntimeCapabilitySet,
    *,
    health_status: str,
) -> RuntimeCapabilitySet:
    if health_status == "healthy":
        return certified
    return replace(
        certified,
        tool_orchestration=False,
        cli=False,
        mcp=False,
        filesystem_write=False,
        shell=False,
        recovery=False,
        confirmation_resume=False,
        confirmations=False,
    )


def _execution_mode_capability_ceiling(
    certified: RuntimeCapabilitySet,
    *,
    execution_mode: ExecutionMode,
) -> RuntimeCapabilitySet:
    if execution_mode == "full-access":
        return certified
    return replace(certified, shell=False)


def _confirmation_capability_ceiling(
    capabilities: RuntimeCapabilitySet,
    policy: AgenticRuntimePolicy,
) -> RuntimeCapabilitySet:
    confirmation_required = (
        policy.require_confirmation_for_mutating
        or policy.require_confirmation_for_destructive
    )
    if not confirmation_required or capabilities.confirmations:
        return capabilities
    # Tool handles carry no trustworthy effect class until catalog resolution.
    # With confirmation unavailable, retaining any tool authority could
    # overstate a mutating or destructive handle, so the ceiling is all-tools.
    return replace(
        capabilities,
        tool_orchestration=False,
        cli=False,
        mcp=False,
        filesystem_list=False,
        filesystem_read=False,
        filesystem_write=False,
        shell=False,
    )


def _disabled_capabilities(reference: RuntimeCapabilitySet) -> RuntimeCapabilitySet:
    return replace(
        reference,
        **{
            field_name: False
            for field_name, value in asdict(reference).items()
            if isinstance(value, bool)
        },
        attachment_modalities=(),
    )


def _narrow_capabilities_to_live_handles(
    capabilities: RuntimeCapabilitySet,
    handles: tuple[str, ...],
) -> RuntimeCapabilitySet:
    allowed = set(handles)
    narrowed = replace(
        capabilities,
        cli=capabilities.cli
        and any(
            item.startswith("cli:") or item.startswith("core-capability:cli.")
            for item in allowed
        ),
        mcp=capabilities.mcp
        and any(
            item.startswith("mcp:") or item.startswith("core-capability:mcp.")
            for item in allowed
        ),
        filesystem_list=(
            capabilities.filesystem_list
            and "core-capability:filesystem.list" in allowed
        ),
        filesystem_read=(
            capabilities.filesystem_read
            and any(
                item
                in {
                    "core-capability:workspace.instructions",
                    "core-capability:filesystem.search",
                    "core-capability:filesystem.read",
                    "core-capability:artifact.read",
                }
                for item in allowed
            )
        ),
        filesystem_write=(
            capabilities.filesystem_write
            and any(
                item.startswith("core-capability:filesystem.")
                and item.rsplit(".", 1)[-1]
                in {"write", "edit", "patch", "move", "delete"}
                for item in allowed
            )
        ),
        shell=(
            capabilities.shell
            and any(
                item == "core-capability:shell.run"
                or item.startswith("core-capability:process.")
                for item in allowed
            )
        ),
    )
    return replace(
        narrowed,
        tool_orchestration=(
            narrowed.tool_orchestration
            and any(
                (
                    narrowed.cli,
                    narrowed.mcp,
                    narrowed.filesystem_list,
                    narrowed.filesystem_read,
                    narrowed.filesystem_write,
                    narrowed.shell,
                    any(item.startswith("app-interface:") for item in allowed),
                )
            )
        ),
    )


def _narrow_handles_to_capabilities(
    handles: tuple[str, ...],
    capabilities: RuntimeCapabilitySet,
) -> tuple[str, ...]:
    def effective(handle: str) -> bool:
        if handle.startswith("cli:"):
            return capabilities.cli
        if handle.startswith("mcp:"):
            return capabilities.mcp
        if handle.startswith("core-capability:cli."):
            return capabilities.cli
        if handle.startswith("core-capability:mcp."):
            return capabilities.mcp
        return {
            "core-capability:workspace.instructions": capabilities.filesystem_read,
            "core-capability:filesystem.list": capabilities.filesystem_list,
            "core-capability:filesystem.search": capabilities.filesystem_read,
            "core-capability:filesystem.read": capabilities.filesystem_read,
            "core-capability:filesystem.write": capabilities.filesystem_write,
            "core-capability:filesystem.edit": capabilities.filesystem_write,
            "core-capability:filesystem.patch": capabilities.filesystem_write,
            "core-capability:filesystem.move": capabilities.filesystem_write,
            "core-capability:filesystem.delete": capabilities.filesystem_write,
            "core-capability:shell.run": capabilities.shell,
            "core-capability:process.start": capabilities.shell,
            "core-capability:process.status": capabilities.shell,
            "core-capability:process.input": capabilities.shell,
            "core-capability:process.interrupt": capabilities.shell,
            "core-capability:artifact.read": capabilities.filesystem_read,
        }.get(handle, True)

    return tuple(handle for handle in handles if effective(handle))


def _has_items(value: object) -> bool:
    return isinstance(value, (list, tuple)) and bool(value)


def _client_authority_value_present(value: object) -> bool:
    return value is not None and value != ""


def _sequence_items(value: object, *, reason_code: str) -> tuple[object, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise CapabilityCertificateError(reason_code)
    return tuple(value)


def _attachment_modality(attachment: dict[str, object]) -> str:
    content_type = str(
        attachment.get("type") or attachment.get("content_type") or ""
    ).strip().lower()
    if not content_type:
        return ""
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("text/") or content_type == "application/json":
        return "text"
    if content_type == "application/pdf":
        return "pdf"
    if content_type in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return "document"
    if content_type in {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        return "spreadsheet"
    return "file"


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
