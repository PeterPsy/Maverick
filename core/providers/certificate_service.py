"""Capability evidence, issuance, revocation, and exact runtime verification."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import inspect
from pathlib import Path
from types import ModuleType

from core.observability.service import record_platform_audit
from core.providers.capability_models import (
    CapabilityCertificate,
    CapabilityCertificateStatus,
    CapabilityEvidenceRecord,
)
from core.providers.certified_execution_tcb import (
    is_exact_codex_identity,
    validate_remote_tcb_identity_with_revision_fence,
)
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.store import ProviderStore
from core.runtime.execution_binding import RuntimeExecutionBinding, canonical_digest
from core.runtime.full_workspace_contract import validate_full_workspace_binding


_LEGACY_EVIDENCE_FIELDS = (
    "suite_id",
    "suite_version",
    "test_run_id",
    "adapter_artifact_digest",
    "result_summary_digest",
    "evidence_refs",
    "recorded_at",
)
_EXECUTED_EVIDENCE_FIELDS = (
    "source_commit",
    "artifact_bundle_digest",
    "matrix_revision",
    "matrix_digest",
    "signer_key_id",
    "run_signature",
    "certification_started_at",
    "certification_outcome",
    "tcb_manifest_id",
    "tcb_manifest_version",
    "tcb_structure_digest",
    "tcb_live_digest",
)


def runtime_adapter_artifact_digest(adapter: object) -> str:
    """Hash every declared class, function, and module in the adapter bundle."""
    concrete = getattr(adapter, "legacy_adapter", adapter)
    digest = hashlib.sha256()
    source_count = 0
    seen_paths: set[Path] = set()
    components = (concrete, *tuple(getattr(concrete, "artifact_components", ())))
    for component in components:
        for source_component in _artifact_source_components(component):
            try:
                source_path = inspect.getsourcefile(source_component)
            except TypeError:
                source_path = None
            if not source_path:
                continue
            path = Path(source_path).resolve()
            digest.update(_artifact_component_identity(source_component))
            if path in seen_paths:
                continue
            seen_paths.add(path)
            digest.update(path.read_bytes())
            digest.update(b"\0")
            source_count += 1
    if not source_count:
        raise CapabilityCertificateError("adapter_artifact_unavailable")
    return digest.hexdigest()


def _artifact_source_components(component: object) -> tuple[object, ...]:
    if isinstance(component, ModuleType) or inspect.isfunction(component):
        return (component,)
    if inspect.ismethod(component):
        return (component.__func__,)
    component_type = component if inspect.isclass(component) else type(component)
    return tuple(component_type.__mro__)


def _artifact_component_identity(component: object) -> bytes:
    if isinstance(component, ModuleType):
        identity = f"module:{component.__name__}"
    else:
        module_name = str(getattr(component, "__module__", ""))
        qualified_name = str(
            getattr(component, "__qualname__", getattr(component, "__name__", ""))
        )
        identity = f"{type(component).__name__}:{module_name}:{qualified_name}"
    return f"{identity}\0".encode("utf-8")


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
    tcb_manifest_id: str = "",
    tcb_manifest_version: str = "",
    tcb_structure_digest: str = "",
    tcb_live_digest: str = "",
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
        "tcb_manifest_id": tcb_manifest_id,
        "tcb_manifest_version": tcb_manifest_version,
        "tcb_structure_digest": tcb_structure_digest,
        "tcb_live_digest": tcb_live_digest,
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
    _validate_certificate_tcb(certificate)
    if certificate.evidence_digest != evidence.evidence_digest:
        raise CapabilityCertificateError("certificate_evidence_mismatch")
    for field_name in ("suite_id", "suite_version", "test_run_id", "adapter_artifact_digest"):
        if getattr(certificate, field_name) != getattr(evidence, field_name):
            raise CapabilityCertificateError("certificate_evidence_identity_mismatch")
    if certificate.evidence_refs != evidence.evidence_refs:
        raise CapabilityCertificateError("certificate_evidence_refs_mismatch")
    for field_name in (
        "tcb_manifest_id",
        "tcb_manifest_version",
        "tcb_structure_digest",
        "tcb_live_digest",
    ):
        if getattr(certificate, field_name) != getattr(evidence, field_name):
            raise CapabilityCertificateError("certificate_tcb_evidence_mismatch")
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
    adapter_artifact_digest: str | None = None,
) -> CapabilityCertificate:
    """Fail closed unless live certification exactly matches the pinned combination."""
    certificate, _revision_fence = (
        validate_certificate_for_binding_with_revision_fence(
            store,
            binding=binding,
            adapter=adapter,
            observed_upstream_id=observed_upstream_id,
            now=now,
            adapter_artifact_digest=adapter_artifact_digest,
        )
    )
    return certificate


def validate_certificate_for_binding_with_revision_fence(
    store: ProviderStore,
    *,
    binding: RuntimeExecutionBinding,
    adapter: object,
    observed_upstream_id: str | None = None,
    now: datetime | None = None,
    adapter_artifact_digest: str | None = None,
) -> tuple[CapabilityCertificate, str]:
    """Validate a certificate and return its content-bound cheap TCB fence."""
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
    if not _evidence_digest_is_valid(evidence):
        raise CapabilityCertificateError("certificate_evidence_corrupt")
    for field_name in ("suite_id", "suite_version", "test_run_id", "adapter_artifact_digest"):
        if getattr(certificate, field_name) != getattr(evidence, field_name):
            raise CapabilityCertificateError("certificate_evidence_identity_mismatch")
    tcb_revision_fence = _validate_binding_tcb(certificate, binding)
    validate_full_workspace_binding(certificate=certificate, binding=binding)
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
        "model_revision": binding.model_revision,
        "model_revision_policy": binding.model_revision_policy,
        "provider_protocol": binding.provider_protocol,
        "provider_api_version": binding.provider_api_version,
        "evidence_digest": binding.certificate_evidence_digest,
        "certified_reasoning_efforts": binding.certified_reasoning_efforts,
        "default_reasoning_effort": binding.default_reasoning_effort,
        "execution_family": binding.execution_family,
        "harness_recipe_id": binding.harness_recipe_id,
        "harness_recipe_revision": binding.harness_recipe_revision,
        "harness_recipe_digest": binding.harness_recipe_digest,
        "provider_capability_catalog_digest": (
            binding.provider_capability_catalog_digest
        ),
        "semantic_projection_compiler_revision": (
            binding.semantic_projection_compiler_revision
        ),
        "tool_contract_revision": binding.tool_contract_revision,
        "context_policy_revision": (
            ""
            if binding.context_policy_snapshot is None
            else binding.context_policy_snapshot.revision
        ),
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
    if (
        binding.reasoning_effort is not None
        and binding.reasoning_effort not in certificate.certified_reasoning_efforts
    ):
        raise CapabilityCertificateError("certificate_reasoning_effort_mismatch")
    adapter_id = str(getattr(adapter, "adapter_id", ""))
    adapter_version = str(getattr(adapter, "adapter_version", ""))
    if adapter_id != binding.adapter_id or adapter_version != binding.adapter_version:
        raise CapabilityCertificateError("adapter_version_mismatch")
    live_adapter_digest = (
        adapter_artifact_digest
        if adapter_artifact_digest is not None
        else runtime_adapter_artifact_digest(adapter)
    )
    if live_adapter_digest != binding.adapter_artifact_digest:
        raise CapabilityCertificateError("adapter_artifact_mismatch")
    return certificate, tcb_revision_fence


def validate_profile_certificate_execution_contract(*, profile, certificate) -> None:
    """Pin recipe, context, semantic, tool, and provider-catalog identities."""
    expected = {
        "model_revision": str(getattr(profile, "model_revision", "") or ""),
        "model_revision_policy": str(
            getattr(profile, "model_revision_policy", "provider_alias")
            or "provider_alias"
        ),
        "execution_family": str(getattr(profile, "execution_family", "") or ""),
        "harness_recipe_id": str(getattr(profile, "harness_recipe_id", "") or ""),
        "harness_recipe_revision": str(
            getattr(profile, "harness_recipe_revision", "") or ""
        ),
        "harness_recipe_digest": str(
            getattr(profile, "harness_recipe_digest", "") or ""
        ),
        "provider_capability_catalog_digest": str(
            getattr(profile, "provider_capability_catalog_digest", "") or ""
        ),
        "semantic_projection_compiler_revision": str(
            getattr(profile, "semantic_projection_compiler_revision", "") or ""
        ),
        "tool_contract_revision": str(
            getattr(profile, "tool_contract_revision", "") or ""
        ),
        "context_policy_revision": (
            ""
            if getattr(profile, "context_policy", None) is None
            else str(profile.context_policy.revision or "")
        ),
    }
    for field_name, value in expected.items():
        default = "provider_alias" if field_name == "model_revision_policy" else ""
        if str(getattr(certificate, field_name, default) or default) != value:
            raise CapabilityCertificateError(
                f"certificate_{field_name}_mismatch"
            )


def _evidence_digest_is_valid(evidence: CapabilityEvidenceRecord) -> bool:
    """Validate current evidence and pre-executed-certification records."""
    current_payload = {
        key: value
        for key, value in evidence.__dict__.items()
        if key != "evidence_digest"
    }
    if canonical_digest(current_payload) == evidence.evidence_digest:
        return True
    if any(getattr(evidence, field) not in {"", None} for field in _EXECUTED_EVIDENCE_FIELDS):
        return False
    legacy_payload = {field: getattr(evidence, field) for field in _LEGACY_EVIDENCE_FIELDS}
    return canonical_digest(legacy_payload) == evidence.evidence_digest


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
    normalized_model_revision = str(certificate.model_revision or "").strip() or None
    if normalized_model_revision != certificate.model_revision or (
        certificate.model_revision_policy not in {"exact", "provider_alias"}
    ) or (
        certificate.model_revision_policy == "exact"
        and normalized_model_revision is None
    ):
        raise CapabilityCertificateError("certificate_model_revision_invalid")
    if len(set(certificate.certified_upstream_ids)) != len(certificate.certified_upstream_ids):
        raise CapabilityCertificateError("certificate_upstream_duplicate")
    efforts = tuple(str(value or "").strip() for value in certificate.certified_reasoning_efforts)
    if (
        any(not value for value in efforts)
        or len(set(efforts)) != len(efforts)
        or efforts != certificate.certified_reasoning_efforts
    ):
        raise CapabilityCertificateError("certificate_reasoning_efforts_invalid")
    default_effort = str(certificate.default_reasoning_effort or "").strip() or None
    if default_effort != certificate.default_reasoning_effort or (
        default_effort is not None and default_effort not in efforts
    ):
        raise CapabilityCertificateError("certificate_default_reasoning_effort_invalid")
    recipe_identity = (
        certificate.execution_family,
        certificate.harness_recipe_id,
        certificate.harness_recipe_revision,
        certificate.harness_recipe_digest,
        certificate.provider_capability_catalog_digest,
        certificate.semantic_projection_compiler_revision,
        certificate.tool_contract_revision,
        certificate.context_policy_revision,
    )
    if any(recipe_identity):
        if not all(str(value or "").strip() for value in recipe_identity):
            raise CapabilityCertificateError("certificate_recipe_identity_invalid")
        _sha256(
            certificate.harness_recipe_digest,
            "certificate_recipe_digest_invalid",
        )
        _sha256(
            certificate.provider_capability_catalog_digest,
            "certificate_provider_catalog_digest_invalid",
        )
    _evidence_refs(certificate.evidence_refs)


def _validate_certificate_tcb(certificate: CapabilityCertificate) -> str:
    if is_exact_codex_identity(
        runtime_engine_id=certificate.runtime_engine_id,
        adapter_id=certificate.adapter_id,
        model_provider_id=certificate.model_provider_id,
        provider_protocol=certificate.provider_protocol,
    ):
        return ""
    _identity, revision_fence = (
        validate_remote_tcb_identity_with_revision_fence(
            manifest_id=certificate.tcb_manifest_id,
            manifest_version=certificate.tcb_manifest_version,
            structure_digest=certificate.tcb_structure_digest,
            live_digest=certificate.tcb_live_digest,
        )
    )
    return revision_fence


def _validate_binding_tcb(
    certificate: CapabilityCertificate,
    binding: RuntimeExecutionBinding,
) -> str:
    if is_exact_codex_identity(
        runtime_engine_id=certificate.runtime_engine_id,
        adapter_id=certificate.adapter_id,
        model_provider_id=certificate.model_provider_id,
        provider_protocol=certificate.provider_protocol,
    ):
        return ""
    revision_fence = _validate_certificate_tcb(certificate)
    if not all(
        (
            binding.tcb_manifest_id,
            binding.tcb_manifest_version,
            binding.tcb_structure_digest,
            binding.tcb_live_digest,
        )
    ):
        raise CapabilityCertificateError("certificate_tcb_binding_missing")
    for field_name in (
        "tcb_manifest_id",
        "tcb_manifest_version",
        "tcb_structure_digest",
        "tcb_live_digest",
    ):
        if getattr(binding, field_name) != getattr(certificate, field_name):
            raise CapabilityCertificateError("certificate_tcb_binding_mismatch")
    return revision_fence


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
