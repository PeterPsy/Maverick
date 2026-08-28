"""Redaction-safe derived certification status for profile presentation."""

from __future__ import annotations

from datetime import UTC, datetime

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.capability_models import CapabilityCertificate, CapabilityCertificateStatus
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certified_execution_tcb import (
    is_exact_codex_identity,
    validate_remote_tcb_identity,
)
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import validate_full_workspace_contract_claim


def certificate_profile_status(
    certificate: CapabilityCertificate,
    status: CapabilityCertificateStatus | None,
    *,
    definition: AgenticProfileDefinition,
    adapter: object,
    now: datetime | None = None,
    adapter_artifact_digest: str | None = None,
) -> str:
    """Derive active/blocked state without trusting an editable certified flag."""
    if status is None:
        return "missing_status"
    if status.status == "revoked":
        return "revoked"
    if (now or datetime.now(tz=UTC)) >= certificate.expires_at:
        return "expired"
    expected = {
        "certificate_id": definition.capability_certificate_id,
        "runtime_engine_id": definition.runtime_engine_id,
        "adapter_id": definition.adapter_id,
        "model_provider_id": definition.model_provider_id,
        "model_id": definition.model_id,
        "provider_protocol": definition.provider_protocol,
        "provider_api_version": definition.provider_api_version,
        "routing_constraint_digest": canonical_digest(definition.routing_constraint),
    }
    if any(getattr(certificate, field_name) != value for field_name, value in expected.items()):
        return "identity_mismatch"
    try:
        validate_full_workspace_contract_claim(
            profile=definition,
            certificate=certificate,
        )
    except CapabilityCertificateError as error:
        return error.reason_code
    adapter_version = str(getattr(adapter, "adapter_version", ""))
    if (
        certificate.adapter_version != adapter_version
        or definition.adapter_version_constraint != f"=={adapter_version}"
    ):
        return "adapter_version_mismatch"
    live_adapter_digest = (
        adapter_artifact_digest
        if adapter_artifact_digest is not None
        else runtime_adapter_artifact_digest(adapter)
    )
    if certificate.adapter_artifact_digest != live_adapter_digest:
        return "adapter_artifact_mismatch"
    if not is_exact_codex_identity(
        runtime_engine_id=certificate.runtime_engine_id,
        adapter_id=certificate.adapter_id,
        model_provider_id=certificate.model_provider_id,
        provider_protocol=certificate.provider_protocol,
    ):
        try:
            validate_remote_tcb_identity(
                manifest_id=certificate.tcb_manifest_id,
                manifest_version=certificate.tcb_manifest_version,
                structure_digest=certificate.tcb_structure_digest,
                live_digest=certificate.tcb_live_digest,
            )
        except CapabilityCertificateError as error:
            return error.reason_code.removeprefix("certificate_")
    return "active"
