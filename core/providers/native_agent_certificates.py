"""Shared, revocable connection authority behind immutable native model pins."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.providers.capability_models import CapabilityCertificate
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.runtime.execution_binding import canonical_digest

if TYPE_CHECKING:
    from core.providers.native_agent_contract import NativeAgentInstallation
    from core.providers.store import ProviderStore


def native_installation_for_adapter(adapter):
    installation = getattr(adapter, "installation", None)
    if installation is None and getattr(adapter, "adapter_id", None) == "codex-app-server":
        from core.providers.native_agent_builtins import build_codex_native_installation

        installation = build_codex_native_installation(getattr(adapter, "legacy_adapter", adapter))
    return installation


def native_connection_identity_digest(
    installation: NativeAgentInstallation, *, model_provider_id: str, artifact_digest: str,
) -> str:
    connection = next(
        item for item in installation.model_provider_connections
        if item.model_provider_id == model_provider_id
    )
    return canonical_digest((
        installation.manifest, installation.recipe, installation.effects,
        connection, artifact_digest, installation.certificate.full_workspace_contract_revision,
    ))


def native_connection_reference(installation: NativeAgentInstallation, model_provider_id: str) -> str:
    references = dict(installation.certificate.connection_certificate_ids)
    reference = references.get(model_provider_id)
    if not reference:
        raise CapabilityCertificateError("native_agent_connection_certificate_missing")
    return reference


def connection_certificate_for_projection(
    store: ProviderStore, certificate: CapabilityCertificate,
) -> CapabilityCertificate:
    """Resolve old immutable Codex pins without rewriting their evidence or bytes."""
    if certificate.certificate_scope == "native_connection":
        return certificate
    if certificate.native_connection_certificate_id:
        try:
            return store.get_capability_certificate(certificate.native_connection_certificate_id)
        except ProviderNotFoundError as error:
            raise CapabilityCertificateError("native_agent_connection_certificate_missing") from error
    roots = [
        item for item in store.list_capability_certificates()
        if item.certificate_scope == "native_connection"
        and certificate.certificate_id in item.legacy_projection_certificate_ids
    ]
    if len(roots) != 1:
        raise CapabilityCertificateError("native_agent_connection_certificate_missing")
    return roots[0]


def validate_native_connection_certificate(
    store: ProviderStore,
    certificate: CapabilityCertificate,
    *,
    now: datetime | None = None,
    installation: NativeAgentInstallation | None = None,
) -> CapabilityCertificate:
    """Every projection shares the root's evidence, expiry, and permanent revocation."""
    from core.providers.certificate_service import _evidence_digest_is_valid

    root = connection_certificate_for_projection(store, certificate)
    if root.certificate_scope != "native_connection" or root.native_connection_certificate_id:
        raise CapabilityCertificateError("native_agent_connection_certificate_invalid")
    for field in (
        "runtime_engine_id", "model_provider_id", "adapter_id", "adapter_version",
        "adapter_artifact_digest", "provider_protocol", "provider_api_version",
        "routing_constraint_digest", "certified_upstream_ids", "certified_capabilities",
    ):
        if getattr(root, field) != getattr(certificate, field):
            raise CapabilityCertificateError("native_agent_connection_identity_mismatch")
    if installation is not None and (
        root.certificate_id != native_connection_reference(installation, certificate.model_provider_id)
        or root.native_connection_identity_digest != native_connection_identity_digest(
            installation, model_provider_id=certificate.model_provider_id,
            artifact_digest=certificate.adapter_artifact_digest,
        )
    ):
        raise CapabilityCertificateError("native_agent_connection_identity_mismatch")
    timestamp = now or datetime.now(tz=UTC)
    status = store.get_capability_certificate_status(root.certificate_id)
    if status is None or status.status != "active":
        raise CapabilityCertificateError(
            "native_agent_connection_certificate_revoked" if status
            else "native_agent_connection_certificate_status_missing"
        )
    if timestamp >= root.expires_at:
        raise CapabilityCertificateError("native_agent_connection_certificate_expired")
    from core.providers.native_runtime_certificates import validate_native_runtime_certificate

    validate_native_runtime_certificate(store, root, installation, now=timestamp)
    try:
        evidence = store.get_capability_evidence(root.evidence_digest)
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("native_agent_connection_evidence_missing") from error
    if not _evidence_digest_is_valid(evidence) or any(
        getattr(root, field) != getattr(evidence, field)
        for field in ("suite_id", "suite_version", "test_run_id", "adapter_artifact_digest", "evidence_refs")
    ):
        raise CapabilityCertificateError("native_agent_connection_evidence_mismatch")
    if certificate.native_connection_certificate_id and any(
        getattr(root, field) != getattr(certificate, field)
        for field in (
            "suite_id", "suite_version", "test_run_id", "evidence_digest",
            "evidence_refs", "issued_at", "expires_at",
        )
    ):
        raise CapabilityCertificateError("native_agent_connection_evidence_mismatch")
    # Pre-connection model certificates remain immutable kill switches. An old
    # revocation must still fence new slugs, including after migration/restart.
    for legacy_id in root.legacy_projection_certificate_ids:
        legacy_status = store.get_capability_certificate_status(legacy_id)
        if legacy_status is None or legacy_status.status != "active":
            raise CapabilityCertificateError("native_agent_connection_certificate_revoked")
        legacy = store.get_capability_certificate(legacy_id)
        if timestamp >= legacy.expires_at:
            raise CapabilityCertificateError("native_agent_connection_certificate_expired")
    return root


__all__ = [
    "connection_certificate_for_projection",
    "native_connection_identity_digest",
    "native_connection_reference",
    "native_installation_for_adapter",
    "validate_native_connection_certificate",
]
