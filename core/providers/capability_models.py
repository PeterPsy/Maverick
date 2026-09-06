"""Immutable capability certification records owned by the provider control plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.providers.agentic_models import ModelRevisionPolicy


@dataclass(frozen=True)
class RuntimeCapabilitySet:
    """Capability lattice values, not proof without a validated authority base."""

    streaming: bool
    tool_orchestration: bool
    cli: bool
    mcp: bool
    skill_catalog: bool
    filesystem_list: bool
    filesystem_read: bool
    filesystem_write: bool
    shell: bool
    interrupt: bool
    same_turn_steering: bool
    recovery: bool
    confirmation_resume: bool
    provider_private_state: bool
    attachment_modalities: tuple[str, ...]
    app_references: bool = False
    confirmations: bool = False


@dataclass(frozen=True)
class CapabilityEvidenceRecord:
    """Platform-owned identity and references for one certification suite run."""

    evidence_digest: str
    suite_id: str
    suite_version: str
    test_run_id: str
    adapter_artifact_digest: str
    result_summary_digest: str
    evidence_refs: tuple[str, ...]
    recorded_at: datetime
    source_commit: str = ""
    artifact_bundle_digest: str = ""
    matrix_revision: str = ""
    matrix_digest: str = ""
    signer_key_id: str = ""
    run_signature: str = ""
    certification_started_at: datetime | None = None
    certification_outcome: str = ""
    tcb_manifest_id: str = ""
    tcb_manifest_version: str = ""
    tcb_structure_digest: str = ""
    tcb_live_digest: str = ""
    certification_target_digest: str = ""


@dataclass(frozen=True)
class CapabilityCertificate:
    """Immutable attestation for one engine/adapter/model/protocol combination."""

    certificate_id: str
    schema_version: str
    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    adapter_artifact_digest: str
    model_provider_id: str
    model_id: str
    model_revision: str | None
    provider_protocol: str
    provider_api_version: str | None
    certified_upstream_ids: tuple[str, ...]
    routing_constraint_digest: str
    certified_capabilities: RuntimeCapabilitySet
    certified_reasoning_efforts: tuple[str, ...]
    default_reasoning_effort: str | None
    suite_id: str
    suite_version: str
    test_run_id: str
    evidence_digest: str
    evidence_refs: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    tcb_manifest_id: str = ""
    tcb_manifest_version: str = ""
    tcb_structure_digest: str = ""
    tcb_live_digest: str = ""
    certification_target_digest: str = ""
    full_workspace_contract_revision: str = ""
    execution_family: str = ""
    harness_recipe_id: str = ""
    harness_recipe_revision: str = ""
    harness_recipe_digest: str = ""
    provider_capability_catalog_digest: str = ""
    semantic_projection_compiler_revision: str = ""
    tool_contract_revision: str = ""
    context_policy_revision: str = ""
    model_revision_policy: ModelRevisionPolicy = "provider_alias"
    provider_config_id: str = ""
    provider_config_revision: str = ""
    provider_config_digest: str = ""
    protocol_adapter_id: str = ""
    protocol_adapter_version: str = ""
    certificate_scope: Literal["model", "native_connection", "native_runtime_artifact"] = "model"
    native_connection_certificate_id: str = ""
    native_connection_identity_digest: str = ""
    native_model_catalog_digest: str = ""
    legacy_projection_certificate_ids: tuple[str, ...] = ()
    native_runtime_artifact_digest: str = ""


@dataclass(frozen=True)
class CapabilityCertificateStatus:
    """CAS-governed live revocation state separated from a certificate."""

    certificate_id: str
    status: Literal["active", "revoked"]
    revision: int
    updated_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
