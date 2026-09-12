"""Publish Antigravity connection authority from a complete trusted run."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.providers.antigravity_agentic_profile import (
    ANTIGRAVITY_CAPABILITY_CATALOG_DIGEST,
    ANTIGRAVITY_CONTEXT_POLICY,
    ANTIGRAVITY_SEMANTIC_PROJECTION_REVISION,
    antigravity_native_capabilities,
    antigravity_native_policy,
    antigravity_native_routing_constraint,
)
from core.providers.capability_models import CapabilityCertificate
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.certification_pipeline import (
    SignedCertificationRun,
    validate_run_against_manifest,
    verify_certification_run,
)
from core.providers.certification_target import native_connection_target_digest
from core.providers.errors import CapabilityCertificateError
from core.providers.execution_families import NATIVE_AGENT_EXECUTION_FAMILY
from core.providers.native_agent_certificates import (
    native_connection_identity_digest,
    native_connection_reference,
    validate_native_connection_certificate,
)
from core.providers.native_runtime_certificates import ensure_native_runtime_certificate
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    inspect_full_workspace_contract,
    validate_full_workspace_contract_claim,
)


ANTIGRAVITY_CERTIFICATION_SUITE_ID = (
    "maverick-antigravity-native-agentic-contract"
)
ANTIGRAVITY_CERTIFICATION_SUITE_VERSION = "64"
ANTIGRAVITY_CERTIFICATION_MATRIX_REVISION = (
    "2026-09-12-r64-openrouter-glm-full-workspace-relace-tcb54"
)
ANTIGRAVITY_CERTIFICATION_VALIDITY_DAYS = 45


def publish_antigravity_connection_certificate(
    store,
    *,
    adapter,
    signed_run: SignedCertificationRun,
    trusted_keys: Mapping[str, Ed25519PublicKey],
) -> CapabilityCertificate:
    """Verify and publish the exact runtime/provider connection, never a slug."""
    installation = getattr(adapter, "installation", None)
    if (
        installation is None
        or installation.manifest.runtime_engine_id != "antigravity-cli"
    ):
        raise CapabilityCertificateError("certification_native_target_incomplete")
    run = verify_certification_run(signed_run, trusted_keys=trusted_keys)
    target_digest = native_connection_target_digest(
        installation,
        model_provider_id="google",
    )
    if run.target_digest != target_digest:
        raise CapabilityCertificateError("certification_target_mismatch")
    validate_run_against_manifest(
        run,
        cwd=Path(__file__).resolve().parents[2],
    )
    if (run.suite_id, run.suite_version) != (
        ANTIGRAVITY_CERTIFICATION_SUITE_ID,
        ANTIGRAVITY_CERTIFICATION_SUITE_VERSION,
    ):
        raise CapabilityCertificateError(
            "certification_suite_identity_mismatch"
        )
    if run.matrix_revision != ANTIGRAVITY_CERTIFICATION_MATRIX_REVISION:
        raise CapabilityCertificateError(
            "certification_matrix_revision_mismatch"
        )
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    if run.adapter_artifact_digest != artifact_digest:
        raise CapabilityCertificateError("adapter_artifact_mismatch")
    observed_runtime = installation.inspector.artifact()
    if (
        installation.runtime_artifact is None
        or observed_runtime != installation.runtime_artifact
    ):
        raise CapabilityCertificateError("native_runtime_artifact_mismatch")
    capabilities = antigravity_native_capabilities()
    if not inspect_full_workspace_contract(
        capabilities=capabilities,
        policy=antigravity_native_policy(),
    ).complete:
        raise CapabilityCertificateError("full_workspace_contract_incomplete")
    evidence = build_capability_evidence(
        suite_id=run.suite_id,
        suite_version=run.suite_version,
        test_run_id=run.test_run_id,
        adapter_artifact_digest=run.adapter_artifact_digest,
        result_summary_digest=run.result_summary_digest,
        evidence_refs=run.evidence_refs,
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
    manifest = installation.manifest
    recipe = installation.recipe
    routing = antigravity_native_routing_constraint()
    certificate = CapabilityCertificate(
        certificate_id=native_connection_reference(installation, "google"),
        schema_version="7",
        certificate_scope="native_connection",
        native_connection_identity_digest=native_connection_identity_digest(
            installation,
            model_provider_id="google",
            artifact_digest=artifact_digest,
        ),
        runtime_engine_id=manifest.runtime_engine_id,
        adapter_id=manifest.adapter_id,
        adapter_version=manifest.adapter_version,
        adapter_artifact_digest=artifact_digest,
        model_provider_id="google",
        model_id="*",
        model_revision=None,
        model_revision_policy="provider_alias",
        provider_protocol=manifest.protocol_id,
        provider_api_version=manifest.protocol_version,
        certified_upstream_ids=routing.allowed_upstream_ids,
        routing_constraint_digest=canonical_digest(routing),
        certified_capabilities=capabilities,
        certified_reasoning_efforts=(),
        default_reasoning_effort=None,
        suite_id=evidence.suite_id,
        suite_version=evidence.suite_version,
        test_run_id=evidence.test_run_id,
        evidence_digest=evidence.evidence_digest,
        evidence_refs=evidence.evidence_refs,
        issued_at=run.certification_completed_at,
        expires_at=(
            run.certification_completed_at
            + timedelta(days=ANTIGRAVITY_CERTIFICATION_VALIDITY_DAYS)
        ),
        tcb_manifest_id=run.tcb_manifest_id,
        tcb_manifest_version=run.tcb_manifest_version,
        tcb_structure_digest=run.tcb_structure_digest,
        tcb_live_digest=run.tcb_live_digest,
        certification_target_digest=run.target_digest,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family=NATIVE_AGENT_EXECUTION_FAMILY,
        harness_recipe_id=recipe.recipe_id,
        harness_recipe_revision=recipe.revision,
        harness_recipe_digest=recipe.digest,
        provider_capability_catalog_digest=(
            ANTIGRAVITY_CAPABILITY_CATALOG_DIGEST
        ),
        semantic_projection_compiler_revision=(
            ANTIGRAVITY_SEMANTIC_PROJECTION_REVISION
        ),
        tool_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        context_policy_revision=ANTIGRAVITY_CONTEXT_POLICY.revision,
    )
    stored = publish_capability_certificate(
        store,
        certificate=certificate,
        evidence=evidence,
    )
    ensure_native_runtime_certificate(store, stored, installation)
    validate_native_connection_certificate(
        store,
        stored,
        installation=installation,
    )
    return stored


def publish_antigravity_model_certificate(
    store,
    *,
    profile,
    adapter,
    now=None,
) -> CapabilityCertificate:
    """Project current catalog metadata without renewing connection evidence."""
    installation = getattr(adapter, "installation", None)
    if (
        installation is None
        or installation.manifest.runtime_engine_id != "antigravity-cli"
    ):
        raise CapabilityCertificateError("certification_native_target_incomplete")
    root = store.get_capability_certificate(
        native_connection_reference(installation, profile.model_provider_id)
    )
    validate_native_connection_certificate(
        store,
        root,
        now=now,
        installation=installation,
    )
    evidence = store.get_capability_evidence(root.evidence_digest)
    certificate = replace(
        root,
        certificate_id=profile.capability_certificate_id,
        certificate_scope="model",
        native_connection_certificate_id=root.certificate_id,
        legacy_projection_certificate_ids=(),
        model_id=profile.model_id,
        model_revision=profile.model_revision,
        model_revision_policy=profile.model_revision_policy,
        native_model_catalog_digest=profile.native_model_catalog_digest,
        certified_reasoning_efforts=(),
        default_reasoning_effort=None,
    )
    validate_full_workspace_contract_claim(
        profile=profile,
        certificate=certificate,
    )
    return publish_capability_certificate(
        store,
        certificate=certificate,
        evidence=evidence,
    )


__all__ = [
    "ANTIGRAVITY_CERTIFICATION_MATRIX_REVISION",
    "ANTIGRAVITY_CERTIFICATION_SUITE_ID",
    "ANTIGRAVITY_CERTIFICATION_SUITE_VERSION",
    "publish_antigravity_connection_certificate",
    "publish_antigravity_model_certificate",
]
