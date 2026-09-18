"""Small immutable runtime configuration stored with an agentic session."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
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
    """Concrete provider/model settings needed to continue one session."""

    execution_binding_id: str
    session_id: str
    workspace_id: str
    workspace_binding_id: str
    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    model_provider_id: str
    model_id: str
    provider_protocol: str
    provider_api_version: str | None
    routing_constraint_snapshot: RoutingConstraint
    credential_binding_id: str | None
    reasoning_effort: str | None
    capabilities_snapshot: RuntimeCapabilitySet
    execution_mode: ExecutionMode
    runtime_policy_snapshot: AgenticRuntimePolicy
    egress_policy_id: str
    egress_policy_revision: str
    created_at: datetime
    context_policy_snapshot: AgenticContextPolicy | None = None
    model_revision: str | None = None
    model_revision_policy: ModelRevisionPolicy = "provider_alias"


def build_runtime_execution_binding(
    *,
    session_id: str,
    workspace_id: str,
    workspace_binding_id: str,
    runtime_engine_id: str,
    adapter_id: str,
    adapter_version: str,
    model_provider_id: str,
    model_id: str,
    provider_protocol: str,
    provider_api_version: str | None,
    routing_constraint: RoutingConstraint,
    credential_binding_id: str | None,
    reasoning_effort: str | None,
    reasoning_efforts: tuple[str, ...],
    capabilities: RuntimeCapabilitySet,
    execution_mode: ExecutionMode,
    runtime_policy: AgenticRuntimePolicy,
    egress_policy_id: str,
    egress_policy_revision: str,
    created_at: datetime,
    context_policy: AgenticContextPolicy | None = None,
    model_revision: str | None = None,
    model_revision_policy: ModelRevisionPolicy = "provider_alias",
) -> RuntimeExecutionBinding:
    """Build the minimal immutable session record."""
    supported_efforts = _reasoning_contract(reasoning_efforts)
    normalized_reasoning = str(reasoning_effort or "").strip() or None
    if normalized_reasoning is not None and normalized_reasoning not in supported_efforts:
        raise ValueError("Runtime execution binding reasoning effort is unsupported.")
    normalized_model_revision = str(model_revision or "").strip() or None
    if model_revision_policy not in {"exact", "provider_alias"} or (
        model_revision_policy == "exact" and normalized_model_revision is None
    ):
        raise ValueError("Runtime execution binding model revision policy is invalid.")
    return RuntimeExecutionBinding(
        execution_binding_id=f"runtime-binding-{uuid4().hex}",
        session_id=session_id,
        workspace_id=workspace_id,
        workspace_binding_id=workspace_binding_id,
        runtime_engine_id=runtime_engine_id,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        model_provider_id=model_provider_id,
        model_id=model_id,
        provider_protocol=provider_protocol,
        provider_api_version=provider_api_version,
        routing_constraint_snapshot=routing_constraint,
        credential_binding_id=credential_binding_id,
        reasoning_effort=normalized_reasoning,
        capabilities_snapshot=capabilities,
        execution_mode=execution_mode,
        runtime_policy_snapshot=runtime_policy,
        egress_policy_id=egress_policy_id,
        egress_policy_revision=egress_policy_revision,
        created_at=created_at,
        context_policy_snapshot=context_policy,
        model_revision=normalized_model_revision,
        model_revision_policy=model_revision_policy,
    )


def copy_runtime_execution_binding_for_child(
    binding: RuntimeExecutionBinding,
    *,
    session_id: str,
    created_at: datetime,
) -> RuntimeExecutionBinding:
    """Copy the parent's concrete settings for an inter-agent child."""
    return replace(
        binding,
        execution_binding_id=f"runtime-binding-{uuid4().hex}",
        session_id=session_id,
        created_at=created_at,
    )


def execution_binding_from_document(document: dict[str, Any]) -> RuntimeExecutionBinding:
    """Hydrate the current direct execution-binding schema."""
    payload = dict(document)
    payload["routing_constraint_snapshot"] = _routing_constraint_from_document(
        payload["routing_constraint_snapshot"]
    )
    payload["runtime_policy_snapshot"] = _policy_from_document(
        payload["runtime_policy_snapshot"]
    )
    capabilities = dict(payload["capabilities_snapshot"])
    capabilities["attachment_modalities"] = tuple(
        capabilities.get("attachment_modalities", ())
    )
    payload["capabilities_snapshot"] = RuntimeCapabilitySet(**capabilities)
    payload["context_policy_snapshot"] = _context_policy_from_document(
        payload.get("context_policy_snapshot")
    )
    # Persisted sessions can outlive schema reductions. Retired metadata grants
    # no authority and must not make the remaining execution inputs unreadable.
    current_fields = {field.name for field in fields(RuntimeExecutionBinding)}
    return RuntimeExecutionBinding(
        **{key: value for key, value in payload.items() if key in current_fields}
    )


def canonical_digest(value: object) -> str:
    """Return stable SHA-256 for ordinary identity and audit use."""
    encoded = json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _policy_from_document(document: dict[str, Any]) -> AgenticRuntimePolicy:
    payload = dict(document)
    for key in (
        "allowed_surface_kinds",
        "allowed_tool_handles",
        "allowed_remote_data_classes",
    ):
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


def _reasoning_contract(efforts: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(str(value or "").strip() for value in efforts)
    if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("Runtime execution binding reasoning efforts are invalid.")
    return normalized


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
