"""Immutable runtime execution binding and canonical digest helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

from core.execution_policy.models import ExecutionMode
from core.providers.agentic_models import AgenticRuntimePolicy, RoutingConstraint


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
    capability_certificate_id: str
    certificate_evidence_digest: str
    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    adapter_artifact_digest: str
    model_provider_id: str
    model_id: str
    provider_protocol: str
    provider_api_version: str | None
    routing_constraint_snapshot: RoutingConstraint
    credential_binding_id: str | None
    reasoning_effort: str | None
    execution_mode: ExecutionMode
    profile_policy_ceiling_snapshot: AgenticRuntimePolicy
    workspace_policy_ceiling_snapshot: AgenticRuntimePolicy
    egress_policy_id: str
    egress_policy_revision: str
    tool_authority_ceiling_digest: str
    binding_digest: str
    created_at: datetime
    legacy_inferred: bool = False


def build_runtime_execution_binding(
    *,
    session_id: str,
    workspace_id: str,
    profile_definition_id: str,
    profile_definition_revision: str,
    workspace_binding_id: str,
    workspace_binding_revision: int,
    capability_certificate_id: str,
    runtime_engine_id: str,
    adapter_id: str,
    adapter_version: str,
    adapter_artifact_digest: str,
    model_provider_id: str,
    model_id: str,
    provider_protocol: str,
    provider_api_version: str | None,
    routing_constraint: RoutingConstraint,
    credential_binding_id: str | None,
    reasoning_effort: str | None,
    execution_mode: ExecutionMode,
    profile_policy_ceiling: AgenticRuntimePolicy,
    workspace_policy_ceiling: AgenticRuntimePolicy,
    egress_policy_id: str,
    egress_policy_revision: str,
    certificate_evidence_digest: str,
    created_at: datetime,
    legacy_inferred: bool = False,
) -> RuntimeExecutionBinding:
    """Build one self-digesting immutable execution binding."""
    for label, digest in (
        ("certificate evidence", certificate_evidence_digest),
        ("adapter artifact", adapter_artifact_digest),
    ):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError(f"Runtime execution binding {label} digest must be SHA-256.")
    policy_digest = canonical_digest(workspace_policy_ceiling)
    record = RuntimeExecutionBinding(
        execution_binding_id=f"runtime-binding-{uuid4().hex}",
        session_id=session_id,
        workspace_id=workspace_id,
        profile_definition_id=profile_definition_id,
        profile_definition_revision=profile_definition_revision,
        workspace_binding_id=workspace_binding_id,
        workspace_binding_revision=workspace_binding_revision,
        capability_certificate_id=capability_certificate_id,
        certificate_evidence_digest=certificate_evidence_digest,
        runtime_engine_id=runtime_engine_id,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        adapter_artifact_digest=adapter_artifact_digest,
        model_provider_id=model_provider_id,
        model_id=model_id,
        provider_protocol=provider_protocol,
        provider_api_version=provider_api_version,
        routing_constraint_snapshot=routing_constraint,
        credential_binding_id=credential_binding_id,
        reasoning_effort=reasoning_effort,
        execution_mode=execution_mode,
        profile_policy_ceiling_snapshot=profile_policy_ceiling,
        workspace_policy_ceiling_snapshot=workspace_policy_ceiling,
        egress_policy_id=egress_policy_id,
        egress_policy_revision=egress_policy_revision,
        tool_authority_ceiling_digest=policy_digest,
        binding_digest="",
        created_at=created_at,
        legacy_inferred=legacy_inferred,
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
    """Hydrate nested policy and routing records from a stored document."""
    payload = dict(document)
    legacy_policy_fields = tuple(
        field_name
        for field_name in (
            "profile_policy_ceiling_snapshot",
            "workspace_policy_ceiling_snapshot",
        )
        if "allow_filesystem_list" not in payload[field_name]
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
    payload.setdefault("legacy_inferred", False)
    binding = RuntimeExecutionBinding(**payload)
    digest_matches = binding.binding_digest == canonical_digest(binding)
    if not digest_matches and legacy_policy_fields:
        legacy_payload = asdict(binding)
        for field_name in legacy_policy_fields:
            legacy_payload[field_name].pop("allow_filesystem_list", None)
        digest_matches = binding.binding_digest == canonical_digest(legacy_payload)
    if not digest_matches:
        raise ValueError("Runtime execution binding digest does not match its immutable payload.")
    return binding


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
