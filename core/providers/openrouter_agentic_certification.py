"""Expiring certification for the exact OpenRouter agentic combination."""

from __future__ import annotations

from datetime import timedelta

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.errors import ProviderNotFoundError
from core.providers.store import ProviderStore
from core.runtime.execution_binding import canonical_digest


OPENROUTER_CERTIFICATION_SUITE_ID = "maverick-openrouter-agentic-contract"
OPENROUTER_CERTIFICATION_SUITE_VERSION = "1"
OPENROUTER_CERTIFICATION_VALIDITY_DAYS = 30


def ensure_openrouter_preview_certificate(
    store: ProviderStore,
    *,
    definition: AgenticProfileDefinition,
    adapter: object,
) -> CapabilityCertificate:
    """Publish fixture-backed evidence for one exact model/upstream bundle."""
    try:
        return store.get_capability_certificate(definition.capability_certificate_id)
    except ProviderNotFoundError:
        pass
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    test_run_id = (
        f"packaged:{definition.definition_id}:{definition.revision}:{artifact_digest[:16]}"
    )
    evidence_refs = (
        "platform-evidence:repository:tests/unit/providers/test_openrouter_agentic_codec.py",
        "platform-evidence:repository:tests/unit/providers/test_openrouter_agentic_transport.py",
        "platform-evidence:repository:tests/unit/runtime_state/test_hosted_agentic_loop.py",
        "platform-evidence:documentation:openrouter-agentic-certification-matrix-2026-08-17",
    )
    result_summary_digest = canonical_digest(
        {
            "suite_id": OPENROUTER_CERTIFICATION_SUITE_ID,
            "suite_version": OPENROUTER_CERTIFICATION_SUITE_VERSION,
            "test_run_id": test_run_id,
            "contract": (
                "stream-tool-call-private-reasoning-exact-upstream-zdr-"
                "no-fallback-no-eligible-endpoint-cancel-recover"
            ),
            "evidence_kind": "deterministic-protocol-fixtures",
        }
    )
    evidence = build_capability_evidence(
        suite_id=OPENROUTER_CERTIFICATION_SUITE_ID,
        suite_version=OPENROUTER_CERTIFICATION_SUITE_VERSION,
        test_run_id=test_run_id,
        adapter_artifact_digest=artifact_digest,
        result_summary_digest=result_summary_digest,
        evidence_refs=evidence_refs,
        recorded_at=definition.created_at,
    )
    certificate = CapabilityCertificate(
        certificate_id=definition.capability_certificate_id,
        schema_version="1",
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=str(getattr(adapter, "adapter_id", definition.adapter_id)),
        adapter_version=str(getattr(adapter, "adapter_version", "")),
        adapter_artifact_digest=artifact_digest,
        model_provider_id=definition.model_provider_id,
        model_id=definition.model_id,
        model_revision="openrouter-catalog-2026-08-17",
        provider_protocol=definition.provider_protocol,
        provider_api_version=definition.provider_api_version,
        certified_upstream_ids=definition.routing_constraint.allowed_upstream_ids,
        routing_constraint_digest=canonical_digest(definition.routing_constraint),
        certified_capabilities=RuntimeCapabilitySet(
            streaming=True,
            tool_orchestration=True,
            cli=False,
            mcp=False,
            skill_catalog=False,
            filesystem_read=True,
            filesystem_write=False,
            shell=False,
            interrupt=True,
            same_turn_steering=False,
            recovery=True,
            confirmation_resume=True,
            provider_private_state=True,
            attachment_modalities=(),
        ),
        suite_id=evidence.suite_id,
        suite_version=evidence.suite_version,
        test_run_id=evidence.test_run_id,
        evidence_digest=evidence.evidence_digest,
        evidence_refs=evidence.evidence_refs,
        issued_at=evidence.recorded_at,
        expires_at=evidence.recorded_at + timedelta(days=OPENROUTER_CERTIFICATION_VALIDITY_DAYS),
    )
    return publish_capability_certificate(store, certificate=certificate, evidence=evidence)
