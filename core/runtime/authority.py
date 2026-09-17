"""Live runtime permissions for agentic turns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import (
    AgenticRuntimePolicy,
    RuntimeCapabilitySet,
    UNBOUNDED_PARALLEL_TOOL_CALLS,
    WorkspaceAgenticProfileBinding,
)
from core.providers.errors import AgenticRuntimeError, ProviderNotFoundError
from core.providers.execution_families import is_exact_codex_identity
from core.providers.provider_credentials import resolve_provider_binding
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from core.runtime.failure_messages import public_runtime_failure_reason_code
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    feature_enabled,
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
class RuntimeAuthority:
    """Ephemeral permissions derived from session settings and live state."""

    execution_binding_id: str
    turn_id: str
    allowed_capabilities: RuntimeCapabilitySet
    allowed_tool_handles: tuple[str, ...]
    execution_mode: ExecutionMode
    egress_policy_id: str
    health_revision: str
    authority_digest: str
    computed_at: datetime
    actor_policy_allowed: bool = True
    actor_policy_revision: str = "runtime-actor:unknown"
    feature_flag_revision: str = "runtime-features:unknown"
    provider_health_status: str = "healthy"
    provider_id: str = ""
    model_id: str = ""
    model_revision: str | None = None
    model_revision_policy: str = "provider_alias"
    provider_protocol: str = ""
    configured_upstream_ids: tuple[str, ...] = ()
    effective_upstream_ids: tuple[str, ...] = ()
    allowed_remote_data_classes: tuple[str, ...] = ()
    data_collection_policy: str = "deny"
    require_zdr: bool = False
    context_policy_revision: str = ""


def resolve_runtime_authority(
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
) -> RuntimeAuthority:
    """Apply live health, mode, actor, workspace, and tool restrictions."""
    timestamp = now or datetime.now(tz=UTC)
    if (
        str(getattr(adapter, "runtime_engine_id", ""))
        != binding.runtime_engine_id
        or str(getattr(adapter, "adapter_id", "")) != binding.adapter_id
        or str(getattr(adapter, "adapter_version", ""))
        != binding.adapter_version
    ):
        raise AgenticRuntimeError("runtime_adapter_identity_mismatch")
    configured_upstreams = tuple(
        binding.routing_constraint_snapshot.allowed_upstream_ids
    )
    if observed_upstream_id and observed_upstream_id not in configured_upstreams:
        raise AgenticRuntimeError("provider_upstream_not_allowed")
    if health_status not in {"healthy", "degraded"}:
        raise AgenticRuntimeError("runtime_health_unavailable")
    if not actor_policy_allowed:
        raise AgenticRuntimeError("runtime_actor_policy_denied")
    workspace_binding = validate_live_runtime_binding_governance(
        store,
        binding=binding,
    )
    policy = intersect_runtime_policies(
        binding.runtime_policy_snapshot,
        workspace_binding.workspace_policy_ceiling,
    )
    policy_capabilities = _narrow_capabilities(
        binding.capabilities_snapshot,
        policy,
    )
    feature_capabilities, feature_revision = _feature_capability_ceiling(
        binding,
        binding.capabilities_snapshot,
    )
    health_capabilities = _health_capability_ceiling(
        binding.capabilities_snapshot,
        health_status=health_status,
    )
    execution_mode: ExecutionMode = (
        "sandbox"
        if "sandbox" in {binding.execution_mode, live_execution_mode}
        else "full-access"
    )
    execution_mode_capabilities = _execution_mode_capability_ceiling(
        binding.capabilities_snapshot,
        execution_mode=execution_mode,
    )
    capabilities = intersect_runtime_capabilities(
        binding.capabilities_snapshot,
        policy_capabilities,
        feature_capabilities,
        health_capabilities,
        execution_mode_capabilities,
    )
    capabilities = _confirmation_capability_ceiling(capabilities, policy)
    tool_handles = _allowed_tool_handles(
        currently_authorized_tool_handles,
        binding.runtime_policy_snapshot,
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
    # Hosted runtimes treat an empty live handle set as no tool authority.
    if tool_handles or not exact_codex:
        capabilities = _narrow_capabilities_to_live_handles(
            capabilities,
            tool_handles,
        )
    authority = RuntimeAuthority(
        execution_binding_id=binding.execution_binding_id,
        turn_id=turn_id,
        allowed_capabilities=capabilities,
        allowed_tool_handles=tool_handles,
        execution_mode=execution_mode,
        egress_policy_id=binding.egress_policy_id,
        health_revision=str(health_revision or "runtime-health:unknown"),
        authority_digest="",
        computed_at=timestamp,
        actor_policy_allowed=True,
        actor_policy_revision=str(actor_policy_revision or "runtime-actor:unknown"),
        feature_flag_revision=feature_revision,
        provider_health_status=health_status,
        provider_id=binding.model_provider_id,
        model_id=binding.model_id,
        model_revision=binding.model_revision,
        model_revision_policy=binding.model_revision_policy,
        provider_protocol=binding.provider_protocol,
        configured_upstream_ids=configured_upstreams,
        effective_upstream_ids=tuple(
            item
            for item in binding.routing_constraint_snapshot.allowed_upstream_ids
        ),
        allowed_remote_data_classes=policy.allowed_remote_data_classes,
        data_collection_policy=binding.routing_constraint_snapshot.data_collection_policy,
        require_zdr=binding.routing_constraint_snapshot.require_zdr,
        context_policy_revision=(
            ""
            if getattr(binding, "context_policy_snapshot", None) is None
            else binding.context_policy_snapshot.revision
        ),
    )
    return replace(authority, authority_digest=canonical_authority_digest(authority))


def canonical_authority_digest(authority: RuntimeAuthority) -> str:
    """Return stable SHA-256 digest of authority with self-digest zeroed out."""
    return canonical_digest(replace(authority, authority_digest=""))


def validate_live_runtime_binding_governance(
    store: ProviderStore,
    *,
    binding: RuntimeExecutionBinding,
) -> WorkspaceAgenticProfileBinding:
    """Validate mutable workspace authority against current control-plane state."""
    try:
        workspace_binding = store.get_workspace_agentic_profile_binding(
            binding.workspace_binding_id
        )
    except ProviderNotFoundError as error:
        raise AgenticRuntimeError("workspace_profile_binding_disabled") from error
    if workspace_binding.workspace_id != binding.workspace_id or not workspace_binding.enabled:
        raise AgenticRuntimeError("workspace_profile_binding_disabled")
    if (
        workspace_binding.egress_policy_id != binding.egress_policy_id
        or workspace_binding.egress_policy_revision != binding.egress_policy_revision
    ):
        raise AgenticRuntimeError("egress_policy_drift_unresolved")
    if binding.credential_binding_id:
        credential = resolve_provider_binding(
            store,
            provider_id=binding.model_provider_id,
            workspace_id=binding.workspace_id,
            binding_id=binding.credential_binding_id,
        )
        if credential is None:
            raise AgenticRuntimeError("credential_binding_unavailable")
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
        max_parallel_tool_calls=UNBOUNDED_PARALLEL_TOOL_CALLS,
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


def runtime_authority_audit_payload(authority: RuntimeAuthority) -> dict[str, object]:
    """Return the redaction-safe persisted projection of ephemeral authority."""
    capabilities = authority.allowed_capabilities
    return {
        "execution_binding_id": authority.execution_binding_id,
        "authority_digest": authority.authority_digest,
        "execution_mode": authority.execution_mode,
        "egress_policy_id": authority.egress_policy_id,
        "health_revision": authority.health_revision,
        "provider_health_status": authority.provider_health_status,
        "actor_policy_revision": authority.actor_policy_revision,
        "feature_flag_revision": authority.feature_flag_revision,
        "context_policy_revision": authority.context_policy_revision or None,
        "allowed_tool_handle_count": len(authority.allowed_tool_handles),
        "allowed_capabilities": tuple(
            name
            for name, value in capabilities.__dict__.items()
            if value is True
        ),
    }


def runtime_capability_payload(
    authority: RuntimeAuthority,
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
            "model_revision": authority.model_revision,
            "model_revision_policy": authority.model_revision_policy,
            "protocol": authority.provider_protocol,
            "configured_upstream_ids": authority.configured_upstream_ids,
            "effective_upstream_ids": authority.effective_upstream_ids,
            "health_status": authority.provider_health_status,
            "health_revision": authority.health_revision,
        },
        "data_policy": {
            "allowed_remote_data_classes": authority.allowed_remote_data_classes,
            "collection": authority.data_collection_policy,
            "require_zdr": authority.require_zdr,
        },
        "context_policy_revision": authority.context_policy_revision or None,
        "actor_policy_revision": authority.actor_policy_revision,
        "feature_flag_revision": authority.feature_flag_revision,
    }


def blocked_runtime_capability_payload(
    reason_code: str,
    *,
    profile_capabilities: RuntimeCapabilitySet | None = None,
) -> dict[str, object]:
    """Return a fail-closed UI/API snapshot when live authority is unavailable."""
    reference = profile_capabilities or RuntimeCapabilitySet(
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
        "allowed_tool_handles": (),
    }


def validate_runtime_context_capabilities(
    authority: RuntimeAuthority,
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
        raise AgenticRuntimeError("agentic_skill_catalog_not_effective")
    attachment_items = tuple(attachments or ())
    if attachment_items:
        supported_modalities = set(capabilities.attachment_modalities)
        for attachment in attachment_items:
            modality = _attachment_modality(attachment)
            if not modality:
                raise AgenticRuntimeError("agentic_attachment_metadata_invalid")
            if modality not in supported_modalities and "file" not in supported_modalities:
                raise AgenticRuntimeError(
                    "agentic_attachment_modality_not_supported"
                )
    if _has_items(app_references) and not capabilities.app_references:
        raise AgenticRuntimeError("agentic_app_references_not_effective")
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
            raise AgenticRuntimeError("agentic_context_operation_unknown")
        if not operation_capabilities[operation]:
            raise AgenticRuntimeError(reason_codes[operation])


def narrow_hosted_authority_to_policy(
    authority: RuntimeAuthority,
    policy: AgenticRuntimePolicy,
) -> RuntimeAuthority:
    """Apply a policy read after authority resolution as a monotonic fence."""
    _validate_policy(policy)
    capabilities = _narrow_capabilities(
        authority.allowed_capabilities,
        policy,
    )
    capabilities = _confirmation_capability_ceiling(capabilities, policy)
    tool_handles = _allowed_tool_handles(
        authority.allowed_tool_handles,
        policy,
    )
    if not capabilities.tool_orchestration:
        tool_handles = ()
    else:
        tool_handles = _narrow_handles_to_capabilities(
            tool_handles,
            capabilities,
        )
    capabilities = _narrow_capabilities_to_live_handles(
        capabilities,
        tool_handles,
    )
    narrowed = replace(
        authority,
        allowed_capabilities=capabilities,
        allowed_tool_handles=tool_handles,
        allowed_remote_data_classes=_tuple_intersection(
            authority.allowed_remote_data_classes,
            policy.allowed_remote_data_classes,
        ),
        authority_digest="",
    )
    return replace(
        narrowed,
        authority_digest=canonical_authority_digest(narrowed),
    )


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
                raise AgenticRuntimeError("agentic_skill_metadata_invalid")
            continue
        skill_id = getattr(item, "skill_id", None)
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise AgenticRuntimeError("agentic_skill_metadata_invalid")
    for value, reason_code in (
        (attachments, "agentic_attachment_metadata_invalid"),
        (app_references, "agentic_app_reference_metadata_invalid"),
    ):
        items = _sequence_items(value, reason_code=reason_code)
        if any(not isinstance(item, dict) for item in items):
            raise AgenticRuntimeError(reason_code)


def reject_client_data_authority(payload: object) -> None:
    """Reject browser/app attempts to submit classification or egress authority."""
    if not isinstance(payload, dict):
        raise AgenticRuntimeError("runtime_client_authority_not_accepted")
    declared = payload.get("declared_remote_data_class")
    if declared is not None and declared != "":
        raise AgenticRuntimeError("remote_data_declaration_not_accepted")
    for key in _CLIENT_AUTHORITY_FIELDS:
        if key in payload and _client_authority_value_present(payload[key]):
            raise AgenticRuntimeError("runtime_client_authority_not_accepted")
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
                raise AgenticRuntimeError(
                    "runtime_client_authority_not_accepted"
                )


def intersect_runtime_capabilities(
    *capabilities: RuntimeCapabilitySet,
) -> RuntimeCapabilitySet:
    """Return a monotonic intersection; no input can overstate a profile declaration."""
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
    declared: RuntimeCapabilitySet,
    policy: AgenticRuntimePolicy,
) -> RuntimeCapabilitySet:
    surfaces = set(policy.allowed_surface_kinds)
    tools_allowed = (
        policy.max_tool_calls_per_turn > 0
        and bool(surfaces)
        and policy.tool_handle_mode != "none"
    )
    return replace(
        declared,
        tool_orchestration=declared.tool_orchestration and tools_allowed,
        cli=declared.cli and "cli" in surfaces,
        mcp=declared.mcp and "mcp" in surfaces,
        skill_catalog=declared.skill_catalog and tools_allowed,
        app_references=declared.app_references and "app-interface" in surfaces,
        filesystem_list=declared.filesystem_list and policy.allow_filesystem_list,
        filesystem_read=declared.filesystem_read and policy.allow_filesystem_read,
        filesystem_write=declared.filesystem_write and policy.allow_filesystem_write,
        shell=declared.shell and policy.allow_shell,
    )


def _feature_capability_ceiling(
    binding: RuntimeExecutionBinding,
    declared: RuntimeCapabilitySet,
) -> tuple[RuntimeCapabilitySet, str]:
    resolved = _runtime_feature_flags(binding)
    hosted_remote = binding.runtime_engine_id == "maverick-tool-loop"
    ceiling = declared
    if not (
        resolved[MAVERICK_FEATURE_AGENTIC_PROFILES]
        and resolved[MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT]
    ):
        ceiling = _disabled_capabilities(declared)
    elif hosted_remote and not all(resolved.values()):
        ceiling = _disabled_capabilities(declared)
    else:
        ceiling = replace(
            declared,
            confirmation_resume=(
                declared.confirmation_resume
                and resolved[MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION]
            ),
            confirmations=(
                declared.confirmations
                and resolved[MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION]
            ),
            provider_private_state=(
                declared.provider_private_state
                and resolved[MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE]
            ),
        )
    return ceiling, runtime_feature_flag_revision(binding)


def runtime_feature_flag_revision(
    binding: RuntimeExecutionBinding,
) -> str:
    """Return the cheap live feature-switch identity used by authority."""
    return f"runtime-features:{canonical_digest(_runtime_feature_flags(binding))}"


def _runtime_feature_flags(
    binding: RuntimeExecutionBinding,
) -> dict[str, bool]:
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
    elif binding.runtime_engine_id == "antigravity-cli":
        remote_names = (
            MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
            MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
            MAVERICK_FEATURE_ANTIGRAVITY_AGENTIC_PREVIEW,
        )
        resolved.update({name: feature_enabled(name) for name in remote_names})
    return resolved


def _health_capability_ceiling(
    declared: RuntimeCapabilitySet,
    *,
    health_status: str,
) -> RuntimeCapabilitySet:
    if health_status == "healthy":
        return declared
    return replace(
        declared,
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
    declared: RuntimeCapabilitySet,
    *,
    execution_mode: ExecutionMode,
) -> RuntimeCapabilitySet:
    if execution_mode == "full-access":
        return declared
    return replace(declared, shell=False)


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
        raise AgenticRuntimeError(reason_code)
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
    if (
        any(value <= 0 for value in positive)
        or policy.max_parallel_tool_calls
        not in {UNBOUNDED_PARALLEL_TOOL_CALLS, 0}
    ):
        raise AgenticRuntimeError("runtime_policy_limit_invalid")
    if policy.max_estimated_cost_microusd is not None and policy.max_estimated_cost_microusd < 0:
        raise AgenticRuntimeError("runtime_policy_cost_invalid")
    if policy.tool_handle_mode == "none" and policy.allowed_tool_handles:
        raise AgenticRuntimeError("runtime_policy_tool_handles_invalid")
    if policy.tool_handle_mode == "exact":
        if not policy.allowed_tool_handles or any("*" in value for value in policy.allowed_tool_handles):
            raise AgenticRuntimeError("runtime_policy_tool_handles_invalid")
