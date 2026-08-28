"""Issue OpenRouter preview certificates from verified certification runs only."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import build_capability_evidence, publish_capability_certificate, runtime_adapter_artifact_digest
from core.providers.certification_pipeline import SignedCertificationRun, validate_run_against_manifest, verify_certification_run
from core.providers.errors import CapabilityCertificateError
from core.providers.openrouter_agentic_profile import (
    OPENROUTER_CERTIFIED_REASONING_EFFORTS,
    OPENROUTER_DEFAULT_REASONING_EFFORT,
)
from core.providers.store import ProviderStore
from core.runtime.execution_binding import canonical_digest


OPENROUTER_CERTIFICATION_SUITE_ID = "maverick-openrouter-agentic-contract"
OPENROUTER_CERTIFICATION_SUITE_VERSION = "12"
OPENROUTER_CERTIFICATION_MATRIX_REVISION = "2026-08-27-r12-p3-tcb5"
OPENROUTER_CERTIFICATION_VALIDITY_DAYS = 30


def publish_openrouter_preview_certificate(
    store: ProviderStore,
    *,
    definition: AgenticProfileDefinition,
    adapter: object,
    signed_run: SignedCertificationRun,
    trusted_keys: Mapping[str, Ed25519PublicKey],
) -> CapabilityCertificate:
    """Verify a completed run and publish its exact OpenRouter combination."""
    run = verify_certification_run(signed_run, trusted_keys=trusted_keys)
    validate_run_against_manifest(run, cwd=Path(__file__).resolve().parents[2])
    if (run.suite_id, run.suite_version) != (
        OPENROUTER_CERTIFICATION_SUITE_ID,
        OPENROUTER_CERTIFICATION_SUITE_VERSION,
    ):
        raise CapabilityCertificateError("certification_suite_identity_mismatch")
    if run.matrix_revision != OPENROUTER_CERTIFICATION_MATRIX_REVISION:
        raise CapabilityCertificateError("certification_matrix_revision_mismatch")
    if run.adapter_artifact_digest != runtime_adapter_artifact_digest(adapter):
        raise CapabilityCertificateError("adapter_artifact_mismatch")
    evidence = build_capability_evidence(
        suite_id=run.suite_id, suite_version=run.suite_version,
        test_run_id=run.test_run_id, adapter_artifact_digest=run.adapter_artifact_digest,
        result_summary_digest=run.result_summary_digest, evidence_refs=run.evidence_refs,
        recorded_at=run.completed_at, source_commit=run.source_commit,
        artifact_bundle_digest=run.artifact_bundle_digest,
        matrix_revision=run.matrix_revision, matrix_digest=run.matrix_digest,
        signer_key_id=signed_run.signer_key_id, run_signature=signed_run.signature,
        certification_started_at=run.started_at, certification_outcome=run.outcome,
        tcb_manifest_id=run.tcb_manifest_id,
        tcb_manifest_version=run.tcb_manifest_version,
        tcb_structure_digest=run.tcb_structure_digest,
        tcb_live_digest=run.tcb_live_digest,
    )
    certificate = CapabilityCertificate(
        certificate_id=definition.capability_certificate_id, schema_version="3",
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=str(getattr(adapter, "adapter_id", definition.adapter_id)),
        adapter_version=str(getattr(adapter, "adapter_version", "")),
        adapter_artifact_digest=run.adapter_artifact_digest,
        model_provider_id=definition.model_provider_id, model_id=definition.model_id,
        model_revision="openrouter-catalog-2026-08-17",
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        certified_upstream_ids=definition.routing_constraint.allowed_upstream_ids,
        routing_constraint_digest=canonical_digest(definition.routing_constraint),
        certified_capabilities=RuntimeCapabilitySet(
            streaming=True, tool_orchestration=True, cli=False, mcp=False,
            skill_catalog=False, filesystem_list=True, filesystem_read=True, filesystem_write=False,
            shell=False, interrupt=True, same_turn_steering=False, recovery=False,
            confirmation_resume=True, provider_private_state=True,
            attachment_modalities=(),
            app_references=False,
            confirmations=True,
        ),
        certified_reasoning_efforts=OPENROUTER_CERTIFIED_REASONING_EFFORTS,
        default_reasoning_effort=OPENROUTER_DEFAULT_REASONING_EFFORT,
        suite_id=evidence.suite_id, suite_version=evidence.suite_version,
        test_run_id=evidence.test_run_id, evidence_digest=evidence.evidence_digest,
        evidence_refs=evidence.evidence_refs, issued_at=run.completed_at,
        expires_at=run.completed_at + timedelta(days=OPENROUTER_CERTIFICATION_VALIDITY_DAYS),
        tcb_manifest_id=run.tcb_manifest_id,
        tcb_manifest_version=run.tcb_manifest_version,
        tcb_structure_digest=run.tcb_structure_digest,
        tcb_live_digest=run.tcb_live_digest,
    )
    return publish_capability_certificate(store, certificate=certificate, evidence=evidence)
