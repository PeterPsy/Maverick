"""Conservative authority-compatibility proof for continuation forks."""

from __future__ import annotations

from dataclasses import asdict

from core.providers.agentic_models import RuntimeCapabilitySet
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest


def prove_compatible_runtime_upgrade(
    provider_store: ProviderStore,
    *,
    source: RuntimeExecutionBinding,
    target: RuntimeExecutionBinding,
    source_reason: str,
) -> tuple[tuple[str, ...], str]:
    """Return the capability intersection and immutable proof digest."""
    exact_fields = (
        "profile_definition_id",
        "runtime_engine_id",
        "adapter_id",
        "adapter_version",
        "model_provider_id",
        "model_id",
        "provider_protocol",
        "provider_api_version",
        "routing_constraint_snapshot",
        "credential_binding_id",
        "reasoning_effort",
        "reasoning_efforts",
        "default_reasoning_effort",
        "execution_mode",
        "profile_policy_ceiling_snapshot",
        "workspace_policy_ceiling_snapshot",
        "egress_policy_id",
        "egress_policy_revision",
    )
    mismatches = [
        field_name
        for field_name in exact_fields
        if getattr(source, field_name) != getattr(target, field_name)
    ]
    if mismatches:
        raise ValueError(f"runtime_profile_upgrade_incompatible_{mismatches[0]}")
    source_capabilities = _capability_names(source.capabilities_snapshot)
    target_capabilities = _capability_names(target.capabilities_snapshot)
    if not target_capabilities.issubset(source_capabilities):
        raise ValueError("runtime_profile_upgrade_capability_expansion")
    intersection = tuple(sorted(source_capabilities.intersection(target_capabilities)))
    proof = {
        "schema_version": "1",
        "source_binding_digest": source.binding_digest,
        "target_binding_digest": target.binding_digest,
        "source_reason": source_reason,
        "exact_fields": exact_fields,
        "compatible_capabilities": intersection,
    }
    return intersection, canonical_digest(proof)


def _capability_names(capabilities: RuntimeCapabilitySet) -> set[str]:
    names = {
        name
        for name, value in asdict(capabilities).items()
        if isinstance(value, bool) and value
    }
    names.update(
        f"attachment:{modality}"
        for modality in capabilities.attachment_modalities
    )
    return names
