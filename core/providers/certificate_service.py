"""Capability evidence, issuance, revocation, and exact runtime verification."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import inspect
from pathlib import Path

from core.observability.service import record_platform_audit
from core.providers.capability_models import (
    CapabilityCertificate,
    CapabilityCertificateStatus,
    CapabilityEvidenceRecord,
)
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest


def runtime_adapter_artifact_digest(adapter: object) -> str:
    """Hash the concrete adapter class bundle, unwrapping compatibility bridges."""
    concrete = getattr(adapter, "legacy_adapter", adapter)
    digest = hashlib.sha256()
    source_count = 0
    seen_paths: set[Path] = set()
    components = (concrete, *tuple(getattr(concrete, "artifact_components", ())))
    for component in components:
        component_type = component if inspect.isclass(component) else type(component)
        for adapter_type in component_type.__mro__:
            try:
                source_path = inspect.getsourcefile(adapter_type)
            except TypeError:
                source_path = None
            if not source_path:
                continue
            path = Path(source_path)
            digest.update(f"{adapter_type.__module__}:{adapter_type.__qualname__}\0".encode())
            if path in seen_paths:
                continue
            seen_paths.add(path)
            digest.update(path.read_bytes())
            digest.update(b"\0")
            source_count += 1
    if not source_count:
        raise CapabilityCertificateError("adapter_artifact_unavailable")
    return digest.hexdigest()


def build_capability_evidence(
    *,
    suite_id: str,
    suite_version: str,
    test_run_id: str,
    adapter_artifact_digest: str,
    result_summary_digest: str,
    evidence_refs: tuple[str, ...],
    recorded_at: datetime,
    source_commit: str = "",
    artifact_bundle_digest: str = "",
    matrix_revision: str = "",
    matrix_digest: str = "",
    signer_key_id: str = "",
    run_signature: str = "",
    certification_started_at: datetime | None = None,
    certification_outcome: str = "",
) -> CapabilityEvidenceRecord:
    """Build one self-identifying evidence record from platform-owned references."""
    _require_aware(recorded_at, "certificate_evidence_time_invalid")
    normalized_refs = _evidence_refs(evidence_refs)
    payload = {
        "suite_id": _required(suite_id, "certificate_evidence_invalid"),
        "suite_version": _required(suite_version, "certificate_evidence_invalid"),
        "test_run_id": _required(test_run_id, "certificate_evidence_invalid"),
        "adapter_artifact_digest": _sha256(adapter_artifact_digest, "adapter_artifact_digest_invalid"),
        "result_summary_digest": _sha256(result_summary_digest, "certificate_evidence_digest_invalid"),
        "evidence_refs": normalized_refs,
        "recorded_at": recorded_at,
        "source_commit": source_commit,
        "artifact_bundle_digest": artifact_bundle_digest,
        "matrix_revision": matrix_revision,
        "matrix_digest": matrix_digest,
        "signer_key_id": signer_key_id,
        "run_signature": run_signature,
        "certification_started_at": certification_started_at,
        "certification_outcome": certification_outcome,
    }
    return CapabilityEvidenceRecord(evidence_digest=canonical_digest(payload), **payload)


def publish_capability_certificate(
    store: ProviderStore,
    *,
    certificate: CapabilityCertificate,
    evidence: CapabilityEvidenceRecord,
    observability_store=None,
) -> CapabilityCertificate:
    """Persist matching immutable evidence/certificate and initialize active status."""
    _validate_certificate_shape(certificate)
    if certificate.evidence_digest != evidence.evidence_digest:
        raise CapabilityCertificateError("certificate_evidence_mismatch")
    for field_name in ("suite_id", "suite_version", "test_run_id", "adapter_artifact_digest"):
        if getattr(certificate, field_name) != getattr(evidence, field_name):
            raise CapabilityCertificateError("certificate_evidence_identity_mismatch")
    if certificate.evidence_refs != evidence.evidence_refs:
        raise CapabilityCertificateError("certificate_evidence_refs_mismatch")
    store.save_capability_evidence(evidence)
    stored = store.save_capability_certificate(certificate)
    status = store.get_capability_certificate_status(certificate.certificate_id)
    if status is None:
        store.save_capability_certificate_status(
            CapabilityCertificateStatus(
                certificate_id=certificate.certificate_id,
                status="active",
                revision=0,
                updated_at=certificate.issued_at,
            ),
            expected_revision=None,
        )
    if observability_store is not None:
        record_platform_audit(
            observability_store,
            action="provider.capability_certificate.publish",
            status="succeeded",
            source_domain="providers",
            detail="Published immutable agentic capability certificate.",
            provider_id=certificate.model_provider_id,
            payload={
                "certificate_id": certificate.certificate_id,
                "runtime_engine_id": certificate.runtime_engine_id,
                "adapter_id": certificate.adapter_id,
                "adapter_version": certificate.adapter_version,
                "evidence_digest": certificate.evidence_digest,
                "expires_at": certificate.expires_at,
            },
        )
    return stored


def revoke_capability_certificate(
    store: ProviderStore,
    *,
    certificate_id: str,
    expected_revision: int,
    reason: str,
    now: datetime | None = None,
    observability_store=None,
) -> CapabilityCertificateStatus:
    """Revoke a certificate exactly once through status CAS."""
    store.get_capability_certificate(certificate_id)
    status = store.get_capability_certificate_status(certificate_id)
    if status is None:
        raise CapabilityCertificateError("certificate_status_missing")
    if status.status == "revoked":
        if status.revision != expected_revision:
            raise CapabilityCertificateError("certificate_status_revision_conflict")
        return status
    timestamp = now or datetime.now(tz=UTC)
    revoked = replace(
        status,
        status="revoked",
        revision=status.revision + 1,
        updated_at=timestamp,
        revoked_at=timestamp,
        revocation_reason=_reason_code(reason),
    )
    saved = store.save_capability_certificate_status(revoked, expected_revision=expected_revision)
    if observability_store is not None:
        certificate = store.get_capability_certificate(certificate_id)
        record_platform_audit(
            observability_store,
            action="provider.capability_certificate.revoke",
            status="succeeded",
            source_domain="providers",
            detail="Revoked agentic capability certificate.",
            provider_id=certificate.model_provider_id,
            payload={
                "certificate_id": certificate_id,
                "status_revision": saved.revision,
                "revocation_reason": saved.revocation_reason,
            },
        )
    return saved


def validate_certificate_for_binding(
    store: ProviderStore,
    *,
    binding: RuntimeExecutionBinding,
    adapter: object,
    observed_upstream_id: str | None = None,
    now: datetime | None = None,
) -> CapabilityCertificate:
    """Fail closed unless live certification exactly matches the pinned combination."""
    try:
        certificate = store.get_capability_certificate(binding.capability_certificate_id)
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("certificate_missing") from error
    status = store.get_capability_certificate_status(certificate.certificate_id)
    if status is None:
        raise CapabilityCertificateError("certificate_status_missing")
    if status.status == "revoked":
        raise CapabilityCertificateError("certificate_revoked")
    try:
        evidence = store.get_capability_evidence(certificate.evidence_digest)
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("certificate_evidence_missing") from error
    evidence_payload = {
        key: value
        for key, value in evidence.__dict__.items()
        if key != "evidence_digest"
    }
    if canonical_digest(evidence_payload) != evidence.evidence_digest:
        raise CapabilityCertificateError("certificate_evidence_corrupt")
    for field_name in ("suite_id", "suite_version", "test_run_id", "adapter_artifact_digest"):
        if getattr(certificate, field_name) != getattr(evidence, field_name):
            raise CapabilityCertificateError("certificate_evidence_identity_mismatch")
    timestamp = now or datetime.now(tz=UTC)
    if timestamp >= certificate.expires_at:
        raise CapabilityCertificateError("certificate_expired")
    expected = {
        "runtime_engine_id": binding.runtime_engine_id,
        "adapter_id": binding.adapter_id,
        "adapter_version": binding.adapter_version,
        "adapter_artifact_digest": binding.adapter_artifact_digest,
        "model_provider_id": binding.model_provider_id,
        "model_id": binding.model_id,
        "provider_protocol": binding.provider_protocol,
        "provider_api_version": binding.provider_api_version,
        "evidence_digest": binding.certificate_evidence_digest,
    }
    for field_name, value in expected.items():
        if getattr(certificate, field_name) != value:
            raise CapabilityCertificateError(f"certificate_{field_name}_mismatch")
    if certificate.routing_constraint_digest != canonical_digest(binding.routing_constraint_snapshot):
        raise CapabilityCertificateError("certificate_routing_constraint_mismatch")
    if tuple(certificate.certified_upstream_ids) != tuple(
        binding.routing_constraint_snapshot.allowed_upstream_ids
    ):
        raise CapabilityCertificateError("certificate_upstream_constraint_mismatch")
    if observed_upstream_id and observed_upstream_id not in certificate.certified_upstream_ids:
        raise CapabilityCertificateError("provider_upstream_not_certified")
    adapter_id = str(getattr(adapter, "adapter_id", ""))
    adapter_version = str(getattr(adapter, "adapter_version", ""))
    if adapter_id != binding.adapter_id or adapter_version != binding.adapter_version:
        raise CapabilityCertificateError("adapter_version_mismatch")
    if runtime_adapter_artifact_digest(adapter) != binding.adapter_artifact_digest:
        raise CapabilityCertificateError("adapter_artifact_mismatch")
    return certificate


def _validate_certificate_shape(certificate: CapabilityCertificate) -> None:
    for field_name in (
        "certificate_id",
        "schema_version",
        "runtime_engine_id",
        "adapter_id",
        "adapter_version",
        "model_provider_id",
        "model_id",
        "provider_protocol",
        "suite_id",
        "suite_version",
        "test_run_id",
    ):
        _required(str(getattr(certificate, field_name)), "certificate_identity_invalid")
    _sha256(certificate.adapter_artifact_digest, "adapter_artifact_digest_invalid")
    _sha256(certificate.routing_constraint_digest, "certificate_routing_digest_invalid")
    _sha256(certificate.evidence_digest, "certificate_evidence_digest_invalid")
    _require_aware(certificate.issued_at, "certificate_time_invalid")
    _require_aware(certificate.expires_at, "certificate_time_invalid")
    if certificate.expires_at <= certificate.issued_at:
        raise CapabilityCertificateError("certificate_expiry_invalid")
    if len(set(certificate.certified_upstream_ids)) != len(certificate.certified_upstream_ids):
        raise CapabilityCertificateError("certificate_upstream_duplicate")
    _evidence_refs(certificate.evidence_refs)


def _evidence_refs(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(_required(value, "certificate_evidence_ref_invalid") for value in values)
    if not normalized or len(set(normalized)) != len(normalized):
        raise CapabilityCertificateError("certificate_evidence_ref_invalid")
    if any(not value.startswith("platform-evidence:") for value in normalized):
        raise CapabilityCertificateError("certificate_evidence_ref_not_platform_owned")
    return normalized


def _required(value: str, reason: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CapabilityCertificateError(reason)
    return normalized


def _sha256(value: str, reason: str) -> str:
    normalized = _required(value, reason).lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise CapabilityCertificateError(reason)
    return normalized


def _require_aware(value: datetime, reason: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CapabilityCertificateError(reason)


def _reason_code(value: str) -> str:
    normalized = _required(value, "certificate_revocation_reason_missing").lower()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_.:-")
    if len(normalized) > 128 or any(character not in allowed for character in normalized):
        raise CapabilityCertificateError("certificate_revocation_reason_invalid")
    return normalized
