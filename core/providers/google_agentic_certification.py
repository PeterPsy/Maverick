"""Issue Google preview certificates from verified certification runs only."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.certification_pipeline import (
    SignedCertificationRun, validate_run_against_manifest,
)
from core.providers.certification_publication import CertificationPublicationAuthority, CertificationReview
from core.providers.errors import CapabilityCertificateError
from core.providers.certification_target import api_profile_target_digest
from core.providers.google_agentic_profile import (
    GOOGLE_CERTIFIED_REASONING_EFFORTS,
    GOOGLE_DEFAULT_REASONING_EFFORT,
)
from core.providers.store import ProviderStore
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import validate_full_workspace_contract_claim


GOOGLE_CERTIFICATION_SUITE_ID = "maverick-google-interactions-agentic-contract"
GOOGLE_CERTIFICATION_SUITE_VERSION = "46"
GOOGLE_CERTIFICATION_MATRIX_REVISION = (
    "2026-09-06-r46-p6-isolated-lab-tcb36"
)
GOOGLE_CERTIFICATION_VALIDITY_DAYS = 45


def publish_google_preview_certificate(
    store: ProviderStore,
    *,
    definition: AgenticProfileDefinition,
    adapter: object,
    signed_run: SignedCertificationRun,
    publisher: CertificationPublicationAuthority,
    review: CertificationReview,
) -> CapabilityCertificate:
    """Verify a completed run and publish its exact Google combination."""
    run, evidence_refs = publisher.verify(signed_run, review, cwd=Path(__file__).resolve().parents[2])
    if run.target_digest != api_profile_target_digest(definition):
        raise CapabilityCertificateError("certification_target_mismatch")
    _validate_run(run, adapter)
    evidence = build_capability_evidence(
        suite_id=run.suite_id,
        suite_version=run.suite_version,
        test_run_id=run.test_run_id,
        adapter_artifact_digest=run.adapter_artifact_digest,
        result_summary_digest=run.result_summary_digest,
        evidence_refs=evidence_refs,
        recorded_at=run.certification_completed_at,
        source_commit=run.source_commit,
        artifact_bundle_digest=run.artifact_bundle_digest,
        matrix_revision=run.matrix_revision,
        matrix_digest=run.matrix_digest,
        signer_key_id=signed_run.signer_key_id,
        run_signature=signed_run.signature,
        certification_started_at=run.started_at,
        certification_outcome=run.outcome,
        tcb_manifest_id=run.tcb_manifest_id,
        tcb_manifest_version=run.tcb_manifest_version,
        tcb_structure_digest=run.tcb_structure_digest,
        tcb_live_digest=run.tcb_live_digest,
        certification_target_digest=run.target_digest,
    )
    certificate = CapabilityCertificate(
        certificate_id=definition.capability_certificate_id,
        schema_version="7",
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=str(getattr(adapter, "adapter_id", definition.adapter_id)),
        adapter_version=str(getattr(adapter, "adapter_version", "")),
        adapter_artifact_digest=run.adapter_artifact_digest,
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
        model_revision=definition.model_revision,
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        certified_upstream_ids=(),
        routing_constraint_digest=canonical_digest(definition.routing_constraint),
        certified_capabilities=_capabilities(),
        certified_reasoning_efforts=GOOGLE_CERTIFIED_REASONING_EFFORTS,
        default_reasoning_effort=GOOGLE_DEFAULT_REASONING_EFFORT,
        suite_id=evidence.suite_id,
        suite_version=evidence.suite_version,
        test_run_id=evidence.test_run_id,
        evidence_digest=evidence.evidence_digest,
        evidence_refs=evidence.evidence_refs,
        issued_at=run.certification_completed_at,
        expires_at=run.certification_completed_at + timedelta(days=GOOGLE_CERTIFICATION_VALIDITY_DAYS),
        tcb_manifest_id=run.tcb_manifest_id,
        tcb_manifest_version=run.tcb_manifest_version,
        tcb_structure_digest=run.tcb_structure_digest,
        tcb_live_digest=run.tcb_live_digest,
        certification_target_digest=run.target_digest,
        full_workspace_contract_revision=(
            definition.full_workspace_contract_revision
        ),
        execution_family=definition.execution_family,
        harness_recipe_id=definition.harness_recipe_id,
        harness_recipe_revision=definition.harness_recipe_revision,
        harness_recipe_digest=definition.harness_recipe_digest,
        provider_capability_catalog_digest=(
            definition.provider_capability_catalog_digest
        ),
        semantic_projection_compiler_revision=(
            definition.semantic_projection_compiler_revision
        ),
        tool_contract_revision=definition.tool_contract_revision,
        context_policy_revision=(
            "" if definition.context_policy is None else definition.context_policy.revision
        ),
        model_revision_policy=definition.model_revision_policy,
        provider_config_id=definition.provider_config_id,
        provider_config_revision=definition.provider_config_revision,
        provider_config_digest=definition.provider_config_digest,
        protocol_adapter_id=definition.protocol_adapter_id,
        protocol_adapter_version=definition.protocol_adapter_version,
    )
    validate_full_workspace_contract_claim(
        profile=definition,
        certificate=certificate,
    )
    return publish_capability_certificate(
        store,
        certificate=certificate,
        evidence=evidence,
    )


def _validate_run(run, adapter: object) -> None:
    validate_run_against_manifest(run, cwd=Path(__file__).resolve().parents[2])
    if (run.suite_id, run.suite_version) != (
        GOOGLE_CERTIFICATION_SUITE_ID,
        GOOGLE_CERTIFICATION_SUITE_VERSION,
    ):
        raise CapabilityCertificateError("certification_suite_identity_mismatch")
    if run.matrix_revision != GOOGLE_CERTIFICATION_MATRIX_REVISION:
        raise CapabilityCertificateError("certification_matrix_revision_mismatch")
    if run.adapter_artifact_digest != runtime_adapter_artifact_digest(adapter):
        raise CapabilityCertificateError("adapter_artifact_mismatch")


def _capabilities() -> RuntimeCapabilitySet:
    return RuntimeCapabilitySet(
        streaming=True, tool_orchestration=True, cli=True, mcp=True,
        skill_catalog=True, filesystem_list=True, filesystem_read=True, filesystem_write=True,
        shell=True, interrupt=True, same_turn_steering=False, recovery=True,
        confirmation_resume=True, provider_private_state=True,
        attachment_modalities=("file",),
        app_references=True,
        confirmations=True,
    )
