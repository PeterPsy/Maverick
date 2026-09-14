"""Immutable runtime execution binding and canonical digest helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import (
    AgenticContextPolicy,
    AgenticRuntimePolicy,
    ModelRevisionPolicy,
    RoutingConstraint,
    RuntimeCapabilitySet,
)


@dataclass(frozen=True)
class RuntimeExecutionBinding:
    """Immutable technical and policy snapshot selected for one session."""

    execution_binding_id: str
    session_id: str
    workspace_id: str
    profile_definition_id: str
    profile_definition_revision: str
    workspace_binding_id: str
    workspace_binding_revision: int
    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    adapter_identity_digest: str
    model_provider_id: str
    model_id: str
    provider_protocol: str
    provider_api_version: str | None
    routing_constraint_snapshot: RoutingConstraint
    credential_binding_id: str | None
    reasoning_effort: str | None
    reasoning_efforts: tuple[str, ...]
    default_reasoning_effort: str | None
    capabilities_snapshot: RuntimeCapabilitySet
    execution_mode: ExecutionMode
    profile_policy_ceiling_snapshot: AgenticRuntimePolicy
    workspace_policy_ceiling_snapshot: AgenticRuntimePolicy
    egress_policy_id: str
    egress_policy_revision: str
    tool_authority_ceiling_digest: str
    binding_digest: str
    created_at: datetime
    legacy_inferred: bool = False
    full_workspace_contract_revision: str = ""
    execution_family: str = ""
    harness_recipe_id: str = ""
    harness_recipe_revision: str = ""
    harness_recipe_digest: str = ""
    provider_capability_catalog_digest: str = ""
    semantic_projection_compiler_revision: str = ""
    tool_contract_revision: str = ""
    context_policy_snapshot: AgenticContextPolicy | None = None
    model_revision: str | None = None
    model_revision_policy: ModelRevisionPolicy = "provider_alias"
    provider_config_id: str = ""
    provider_config_revision: str = ""
    provider_config_digest: str = ""
    protocol_adapter_id: str = ""
    protocol_adapter_version: str = ""


def build_runtime_execution_binding(
    *,
    session_id: str,
    workspace_id: str,
    profile_definition_id: str,
    profile_definition_revision: str,
    workspace_binding_id: str,
    workspace_binding_revision: int,
    runtime_engine_id: str,
    adapter_id: str,
    adapter_version: str,
    adapter_identity_digest: str,
    model_provider_id: str,
    model_id: str,
    provider_protocol: str,
    provider_api_version: str | None,
    routing_constraint: RoutingConstraint,
    credential_binding_id: str | None,
    reasoning_effort: str | None,
    reasoning_efforts: tuple[str, ...],
    default_reasoning_effort: str | None,
    capabilities: RuntimeCapabilitySet,
    execution_mode: ExecutionMode,
    profile_policy_ceiling: AgenticRuntimePolicy,
    workspace_policy_ceiling: AgenticRuntimePolicy,
    egress_policy_id: str,
    egress_policy_revision: str,
    created_at: datetime,
    legacy_inferred: bool = False,
    full_workspace_contract_revision: str = "",
    execution_family: str = "",
    harness_recipe_id: str = "",
    harness_recipe_revision: str = "",
    harness_recipe_digest: str = "",
    provider_capability_catalog_digest: str = "",
    semantic_projection_compiler_revision: str = "",
    tool_contract_revision: str = "",
    context_policy: AgenticContextPolicy | None = None,
    model_revision: str | None = None,
    model_revision_policy: ModelRevisionPolicy = "provider_alias",
    provider_config_id: str = "",
    provider_config_revision: str = "",
    provider_config_digest: str = "",
    protocol_adapter_id: str = "",
    protocol_adapter_version: str = "",
) -> RuntimeExecutionBinding:
    """Build one self-digesting immutable execution binding."""
    for label, digest in (("adapter identity", adapter_identity_digest),):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError(f"Runtime execution binding {label} digest must be SHA-256.")
    normalized_efforts, normalized_default_effort = _reasoning_contract(
        reasoning_efforts,
        default_reasoning_effort,
    )
    normalized_reasoning = str(reasoning_effort or "").strip() or None
    if normalized_reasoning is not None and normalized_reasoning not in normalized_efforts:
        raise ValueError("Runtime execution binding reasoning effort is unsupported.")
    normalized_model_revision = str(model_revision or "").strip() or None
    if model_revision_policy not in {"exact", "provider_alias"} or (
        model_revision_policy == "exact" and normalized_model_revision is None
    ):
        raise ValueError("Runtime execution binding model revision policy is invalid.")
    provider_identity = (
        provider_config_id,
        provider_config_revision,
        provider_config_digest,
        protocol_adapter_id,
        protocol_adapter_version,
    )
    if execution_family == "maverick_agent" and (
        not all(
            isinstance(value, str) and bool(value) and value.strip() == value
            for value in provider_identity
        )
        or len(provider_config_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in provider_config_digest.lower()
        )
    ):
        raise ValueError("Runtime execution binding provider config identity is invalid.")
    policy_digest = canonical_digest(workspace_policy_ceiling)
    record = RuntimeExecutionBinding(
        execution_binding_id=f"runtime-binding-{uuid4().hex}",
        session_id=session_id,
        workspace_id=workspace_id,
        profile_definition_id=profile_definition_id,
        profile_definition_revision=profile_definition_revision,
        workspace_binding_id=workspace_binding_id,
        workspace_binding_revision=workspace_binding_revision,
        runtime_engine_id=runtime_engine_id,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        adapter_identity_digest=adapter_identity_digest,
        model_provider_id=model_provider_id,
        model_id=model_id,
        provider_protocol=provider_protocol,
        provider_api_version=provider_api_version,
        routing_constraint_snapshot=routing_constraint,
        credential_binding_id=credential_binding_id,
        reasoning_effort=normalized_reasoning,
        reasoning_efforts=normalized_efforts,
        default_reasoning_effort=normalized_default_effort,
        capabilities_snapshot=capabilities,
        execution_mode=execution_mode,
        profile_policy_ceiling_snapshot=profile_policy_ceiling,
        workspace_policy_ceiling_snapshot=workspace_policy_ceiling,
        egress_policy_id=egress_policy_id,
        egress_policy_revision=egress_policy_revision,
        tool_authority_ceiling_digest=policy_digest,
        binding_digest="",
        created_at=created_at,
        legacy_inferred=legacy_inferred,
        full_workspace_contract_revision=full_workspace_contract_revision,
        execution_family=execution_family,
        harness_recipe_id=harness_recipe_id,
        harness_recipe_revision=harness_recipe_revision,
        harness_recipe_digest=harness_recipe_digest,
        provider_capability_catalog_digest=provider_capability_catalog_digest,
        semantic_projection_compiler_revision=(
            semantic_projection_compiler_revision
        ),
        tool_contract_revision=tool_contract_revision,
        context_policy_snapshot=context_policy,
        model_revision=normalized_model_revision,
        model_revision_policy=model_revision_policy,
        provider_config_id=provider_config_id,
        provider_config_revision=provider_config_revision,
        provider_config_digest=provider_config_digest,
        protocol_adapter_id=protocol_adapter_id,
        protocol_adapter_version=protocol_adapter_version,
    )
    return replace(record, binding_digest=canonical_digest(record))


def fork_runtime_execution_binding(
    binding: RuntimeExecutionBinding,
    *,
    session_id: str,
    created_at: datetime,
) -> RuntimeExecutionBinding:
    """Create a child-session binding with the same immutable ceiling."""
    forked = replace(
        binding,
        execution_binding_id=f"runtime-binding-{uuid4().hex}",
        session_id=session_id,
        binding_digest="",
        created_at=created_at,
    )
    return replace(forked, binding_digest=canonical_digest(forked))


def execution_binding_from_document(document: dict[str, Any]) -> RuntimeExecutionBinding:
    """Hydrate and validate a direct runtime execution binding."""
    payload = dict(document)
    original_digest = str(payload.get("binding_digest") or "")
    if original_digest != canonical_digest(payload):
        raise ValueError(
            "Runtime execution binding digest does not match its immutable payload."
        )
    payload["routing_constraint_snapshot"] = _routing_constraint_from_document(
        payload["routing_constraint_snapshot"]
    )
    payload["profile_policy_ceiling_snapshot"] = _policy_from_document(
        payload["profile_policy_ceiling_snapshot"]
    )
    payload["workspace_policy_ceiling_snapshot"] = _policy_from_document(
        payload["workspace_policy_ceiling_snapshot"]
    )
    payload["reasoning_efforts"] = tuple(payload.get("reasoning_efforts", ()))
    payload.setdefault("default_reasoning_effort", None)
    capabilities = payload.get("capabilities_snapshot")
    if not isinstance(capabilities, dict):
        capabilities = _legacy_capabilities_for_binding(payload)
    capabilities = dict(capabilities)
    capabilities.setdefault("filesystem_list", False)
    capabilities.setdefault("app_references", False)
    capabilities.setdefault("confirmations", False)
    capabilities["attachment_modalities"] = tuple(
        capabilities.get("attachment_modalities", ())
    )
    payload["capabilities_snapshot"] = RuntimeCapabilitySet(**capabilities)
    payload.setdefault("legacy_inferred", False)
    payload.setdefault("full_workspace_contract_revision", "")
    payload.setdefault("execution_family", "")
    payload.setdefault("harness_recipe_id", "")
    payload.setdefault("harness_recipe_revision", "")
    payload.setdefault("harness_recipe_digest", "")
    payload.setdefault("provider_capability_catalog_digest", "")
    payload.setdefault("semantic_projection_compiler_revision", "")
    payload.setdefault("tool_contract_revision", "")
    payload.setdefault("model_revision", None)
    payload.setdefault("model_revision_policy", "provider_alias")
    payload.setdefault("provider_config_id", "")
    payload.setdefault("provider_config_revision", "")
    payload.setdefault("provider_config_digest", "")
    payload.setdefault("protocol_adapter_id", "")
    payload.setdefault("protocol_adapter_version", "")
    payload["context_policy_snapshot"] = _context_policy_from_document(
        payload.get("context_policy_snapshot")
    )
    payload["binding_digest"] = ""
    binding = RuntimeExecutionBinding(**payload)
    return replace(binding, binding_digest=canonical_digest(binding))


def canonical_digest(value: object) -> str:
    """Return a stable SHA-256 over a domain model's canonical JSON form."""
    payload = _canonical_value(value)
    if isinstance(payload, dict):
        payload = {
            key: item
            for key, item in payload.items()
            if key not in {"binding_digest", "authority_digest"}
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _policy_from_document(document: dict[str, Any]) -> AgenticRuntimePolicy:
    payload = dict(document)
    payload.setdefault("allow_filesystem_list", False)
    for key in ("allowed_surface_kinds", "allowed_tool_handles", "allowed_remote_data_classes"):
        payload[key] = tuple(payload.get(key, ()))
    return AgenticRuntimePolicy(**payload)


def _routing_constraint_from_document(document: dict[str, Any]) -> RoutingConstraint:
    payload = dict(document)
    for key in ("allowed_upstream_ids", "allowed_quantizations"):
        payload[key] = tuple(payload.get(key, ()))
    return RoutingConstraint(**payload)


def _context_policy_from_document(
    document: dict[str, Any] | AgenticContextPolicy | None,
) -> AgenticContextPolicy | None:
    if document is None or isinstance(document, AgenticContextPolicy):
        return document
    return AgenticContextPolicy(**dict(document))


def _legacy_capabilities_for_binding(payload: dict[str, Any]) -> dict[str, object]:
    """Upgrade sessions created before direct capability snapshots."""
    native_codex = payload.get("provider_protocol") == "codex-app-server-stdio"
    return {
        "streaming": True,
        "tool_orchestration": True,
        "cli": True,
        "mcp": True,
        "skill_catalog": True,
        "filesystem_list": True,
        "filesystem_read": True,
        "filesystem_write": True,
        "shell": True,
        "interrupt": True,
        "same_turn_steering": native_codex,
        "recovery": True,
        "confirmation_resume": not native_codex,
        "provider_private_state": not native_codex,
        "attachment_modalities": ("file",),
        "app_references": True,
        "confirmations": not native_codex,
    }


def _reasoning_contract(
    efforts: tuple[str, ...],
    default_effort: str | None,
) -> tuple[tuple[str, ...], str | None]:
    normalized = tuple(str(value or "").strip() for value in efforts)
    if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("Runtime execution binding reasoning efforts are invalid.")
    normalized_default = str(default_effort or "").strip() or None
    if normalized_default is not None and normalized_default not in normalized:
        raise ValueError("Runtime execution binding default reasoning effort is unsupported.")
    return normalized, normalized_default


def _canonical_value(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return _canonical_value(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value
