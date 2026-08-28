"""Immutable runtime execution binding and canonical digest helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
from itertools import combinations
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
    certified_reasoning_efforts: tuple[str, ...]
    default_reasoning_effort: str | None
    execution_mode: ExecutionMode
    profile_policy_ceiling_snapshot: AgenticRuntimePolicy
    workspace_policy_ceiling_snapshot: AgenticRuntimePolicy
    egress_policy_id: str
    egress_policy_revision: str
    tool_authority_ceiling_digest: str
    binding_digest: str
    created_at: datetime
    legacy_inferred: bool = False
    tcb_manifest_id: str = ""
    tcb_manifest_version: str = ""
    tcb_structure_digest: str = ""
    tcb_live_digest: str = ""
    full_workspace_contract_revision: str = ""


@dataclass(frozen=True)
class _LegacySchemaFieldGroup:
    """Fields introduced together by one persisted-binding schema extension."""

    binding_fields: tuple[str, ...] = ()
    policy_fields: tuple[str, ...] = ()


_LEGACY_SCHEMA_FIELD_GROUPS = (
    _LegacySchemaFieldGroup(
        binding_fields=("certified_reasoning_efforts", "default_reasoning_effort"),
    ),
    _LegacySchemaFieldGroup(
        binding_fields=(
            "tcb_manifest_id",
            "tcb_manifest_version",
            "tcb_structure_digest",
            "tcb_live_digest",
        ),
    ),
    _LegacySchemaFieldGroup(
        policy_fields=(
            "profile_policy_ceiling_snapshot",
            "workspace_policy_ceiling_snapshot",
        ),
    ),
    _LegacySchemaFieldGroup(
        binding_fields=("full_workspace_contract_revision",),
    ),
)


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
    certified_reasoning_efforts: tuple[str, ...],
    default_reasoning_effort: str | None,
    execution_mode: ExecutionMode,
    profile_policy_ceiling: AgenticRuntimePolicy,
    workspace_policy_ceiling: AgenticRuntimePolicy,
    egress_policy_id: str,
    egress_policy_revision: str,
    certificate_evidence_digest: str,
    created_at: datetime,
    legacy_inferred: bool = False,
    tcb_manifest_id: str = "",
    tcb_manifest_version: str = "",
    tcb_structure_digest: str = "",
    tcb_live_digest: str = "",
    full_workspace_contract_revision: str = "",
) -> RuntimeExecutionBinding:
    """Build one self-digesting immutable execution binding."""
    if (
        runtime_engine_id != "codex"
        or adapter_id != "codex-app-server"
        or model_provider_id != "codex"
        or provider_protocol != "codex-app-server-stdio"
    ) and not any(
        (
            tcb_manifest_id,
            tcb_manifest_version,
            tcb_structure_digest,
            tcb_live_digest,
        )
    ):
        # Lazy import avoids a module cycle: the TCB manifest itself uses the
        # canonical digest helper defined in this module.
        from core.providers.certified_execution_tcb import certified_tcb_identity

        current_tcb = certified_tcb_identity()
        tcb_manifest_id = current_tcb.manifest_id
        tcb_manifest_version = current_tcb.manifest_version
        tcb_structure_digest = current_tcb.structure_digest
        tcb_live_digest = current_tcb.live_digest
    for label, digest in (
        ("certificate evidence", certificate_evidence_digest),
        ("adapter artifact", adapter_artifact_digest),
    ):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError(f"Runtime execution binding {label} digest must be SHA-256.")
    normalized_efforts, normalized_default_effort = _reasoning_contract(
        certified_reasoning_efforts,
        default_reasoning_effort,
    )
    normalized_reasoning = str(reasoning_effort or "").strip() or None
    if normalized_reasoning is not None and normalized_reasoning not in normalized_efforts:
        raise ValueError("Runtime execution binding reasoning effort is not certified.")
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
        reasoning_effort=normalized_reasoning,
        certified_reasoning_efforts=normalized_efforts,
        default_reasoning_effort=normalized_default_effort,
        execution_mode=execution_mode,
        profile_policy_ceiling_snapshot=profile_policy_ceiling,
        workspace_policy_ceiling_snapshot=workspace_policy_ceiling,
        egress_policy_id=egress_policy_id,
        egress_policy_revision=egress_policy_revision,
        tool_authority_ceiling_digest=policy_digest,
        binding_digest="",
        created_at=created_at,
        legacy_inferred=legacy_inferred,
        tcb_manifest_id=tcb_manifest_id,
        tcb_manifest_version=tcb_manifest_version,
        tcb_structure_digest=tcb_structure_digest,
        tcb_live_digest=tcb_live_digest,
        full_workspace_contract_revision=full_workspace_contract_revision,
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
    legacy_compatible_field_groups = tuple(
        group
        for group in _LEGACY_SCHEMA_FIELD_GROUPS
        if all(
            _legacy_binding_field_has_fail_closed_default(payload, field_name)
            for field_name in group.binding_fields
        )
        and all(
            _legacy_policy_field_has_fail_closed_default(payload, field_name)
            for field_name in group.policy_fields
        )
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
    payload["certified_reasoning_efforts"] = tuple(
        payload.get("certified_reasoning_efforts", ())
    )
    payload.setdefault("default_reasoning_effort", None)
    payload.setdefault("legacy_inferred", False)
    payload.setdefault("tcb_manifest_id", "")
    payload.setdefault("tcb_manifest_version", "")
    payload.setdefault("tcb_structure_digest", "")
    payload.setdefault("tcb_live_digest", "")
    payload.setdefault("full_workspace_contract_revision", "")
    binding = RuntimeExecutionBinding(**payload)
    digest_matches = binding.binding_digest == canonical_digest(binding)
    if not digest_matches:
        digest_matches = _matches_legacy_digest(
            binding,
            compatible_field_groups=legacy_compatible_field_groups,
        )
    if not digest_matches:
        raise ValueError("Runtime execution binding digest does not match its immutable payload.")
    return binding


def _matches_legacy_digest(
    binding: RuntimeExecutionBinding,
    *,
    compatible_field_groups: tuple[_LegacySchemaFieldGroup, ...],
) -> bool:
    """Accept exact legacy digests for explicit atomic schema extensions only."""
    current_payload = asdict(binding)
    for group_count in range(1, len(compatible_field_groups) + 1):
        for selected_groups in combinations(compatible_field_groups, group_count):
            legacy_payload = dict(current_payload)
            for group in selected_groups:
                for field_name in group.binding_fields:
                    legacy_payload.pop(field_name, None)
                for field_name in group.policy_fields:
                    legacy_policy = dict(legacy_payload[field_name])
                    legacy_policy.pop("allow_filesystem_list", None)
                    legacy_payload[field_name] = legacy_policy
            if binding.binding_digest == canonical_digest(legacy_payload):
                return True
    return False


def _legacy_binding_field_has_fail_closed_default(
    payload: dict[str, Any],
    field_name: str,
) -> bool:
    if field_name not in payload:
        return True
    if field_name == "certified_reasoning_efforts":
        return payload[field_name] in ([], ())
    if field_name == "default_reasoning_effort":
        return payload[field_name] is None
    return False


def _legacy_policy_field_has_fail_closed_default(
    payload: dict[str, Any],
    field_name: str,
) -> bool:
    policy = payload[field_name]
    return (
        "allow_filesystem_list" not in policy
        or policy["allow_filesystem_list"] is False
    )


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


def _reasoning_contract(
    efforts: tuple[str, ...],
    default_effort: str | None,
) -> tuple[tuple[str, ...], str | None]:
    normalized = tuple(str(value or "").strip() for value in efforts)
    if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError("Runtime execution binding certified reasoning efforts are invalid.")
    normalized_default = str(default_effort or "").strip() or None
    if normalized_default is not None and normalized_default not in normalized:
        raise ValueError("Runtime execution binding default reasoning effort is not certified.")
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
