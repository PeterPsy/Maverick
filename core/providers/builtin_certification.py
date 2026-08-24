"""Packaged preview certification for the migrated Codex runtime."""

from __future__ import annotations

from datetime import timedelta

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.agentic_profiles import (
    CODEX_PROFILE_ARTIFACT_DIGEST,
    CODEX_PROFILE_REVISION,
)
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.models import ProviderDefinition
from core.providers.store import ProviderStore
from core.runtime.execution_binding import canonical_digest


CODEX_CERTIFICATION_SUITE_ID = "maverick-codex-agentic-contract"
CODEX_CERTIFICATION_SUITE_VERSION = "2"
CODEX_CERTIFICATION_VALIDITY_DAYS = 90


def ensure_codex_preview_certificate(
    store: ProviderStore,
    *,
    definition: AgenticProfileDefinition,
    provider_definition: ProviderDefinition,
    adapter: object,
) -> CapabilityCertificate:
    """Publish an expiring certificate backed by the packaged Codex contract suite."""
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    if (
        definition.revision == CODEX_PROFILE_REVISION
        and artifact_digest != CODEX_PROFILE_ARTIFACT_DIGEST
    ):
        raise CapabilityCertificateError("profile_revision_artifact_mismatch")
    model = next(
        (
            item
            for item in provider_definition.model_options
            if item.model_id == definition.model_id
        ),
        None,
    )
    reasoning_efforts = tuple(
        item.effort for item in (() if model is None else model.supported_reasoning_efforts)
    )
    default_reasoning_effort = None if model is None else model.default_reasoning_effort
    try:
        existing = store.get_capability_certificate(definition.capability_certificate_id)
    except ProviderNotFoundError:
        existing = None
    if existing is not None:
        expected_identity = {
            "runtime_engine_id": definition.runtime_engine_id,
            "adapter_id": str(getattr(adapter, "adapter_id", definition.adapter_id)),
            "adapter_version": str(getattr(adapter, "adapter_version", "")),
            "adapter_artifact_digest": artifact_digest,
            "model_provider_id": definition.model_provider_id,
            "model_id": definition.model_id,
            "provider_protocol": definition.provider_protocol,
            "provider_api_version": definition.provider_api_version,
            "certified_reasoning_efforts": reasoning_efforts,
            "default_reasoning_effort": default_reasoning_effort,
        }
        if any(
            getattr(existing, field_name) != expected
            for field_name, expected in expected_identity.items()
        ):
            raise CapabilityCertificateError("profile_revision_artifact_mismatch")
        return existing
    test_run_id = (
        f"packaged:{definition.definition_id}:{definition.revision}:"
        f"{artifact_digest[:16]}"
    )
    evidence_refs = (
        "platform-evidence:repository:tests/unit/providers",
        "platform-evidence:repository:tests/e2e/provider_process",
    )
    result_summary_digest = canonical_digest(
        {
            "suite_id": CODEX_CERTIFICATION_SUITE_ID,
            "suite_version": CODEX_CERTIFICATION_SUITE_VERSION,
            "test_run_id": test_run_id,
            "contract": "validate-prepare-stream-cancel-recover-close",
            "certified_reasoning_efforts": reasoning_efforts,
            "default_reasoning_effort": default_reasoning_effort,
        }
    )
    evidence = build_capability_evidence(
        suite_id=CODEX_CERTIFICATION_SUITE_ID,
        suite_version=CODEX_CERTIFICATION_SUITE_VERSION,
        test_run_id=test_run_id,
        adapter_artifact_digest=artifact_digest,
        result_summary_digest=result_summary_digest,
        evidence_refs=evidence_refs,
        recorded_at=definition.created_at,
    )
    certificate = CapabilityCertificate(
        certificate_id=definition.capability_certificate_id,
        schema_version="2",
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=str(getattr(adapter, "adapter_id", definition.adapter_id)),
        adapter_version=str(getattr(adapter, "adapter_version", "")),
        adapter_artifact_digest=artifact_digest,
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
        model_revision=None,
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        certified_upstream_ids=definition.routing_constraint.allowed_upstream_ids,
        routing_constraint_digest=canonical_digest(definition.routing_constraint),
        certified_capabilities=RuntimeCapabilitySet(
            streaming=True,
            tool_orchestration=True,
            cli=True,
            mcp=True,
            skill_catalog=True,
            filesystem_list=False,
            filesystem_read=True,
            filesystem_write=True,
            shell=True,
            interrupt=True,
            same_turn_steering=True,
            recovery=True,
            confirmation_resume=False,
            provider_private_state=False,
            attachment_modalities=(),
        ),
        certified_reasoning_efforts=reasoning_efforts,
        default_reasoning_effort=default_reasoning_effort,
        suite_id=evidence.suite_id,
        suite_version=evidence.suite_version,
        test_run_id=evidence.test_run_id,
        evidence_digest=evidence.evidence_digest,
        evidence_refs=evidence.evidence_refs,
        issued_at=evidence.recorded_at,
        expires_at=evidence.recorded_at + timedelta(days=CODEX_CERTIFICATION_VALIDITY_DAYS),
    )
    return publish_capability_certificate(store, certificate=certificate, evidence=evidence)
