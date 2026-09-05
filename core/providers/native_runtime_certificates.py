"""Immutable runtime-artifact component of a shared native connection certificate."""

from dataclasses import replace

from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.runtime.execution_binding import canonical_digest


def runtime_certificate_id(connection) -> str:
    return f"{connection.certificate_id}:runtime-artifact"


def ensure_native_runtime_certificate(store, connection, installation) -> None:
    """Adopt the explicitly approved runtime without renewing connection evidence."""
    from core.providers.certificate_service import publish_capability_certificate

    try:
        store.get_capability_certificate(runtime_certificate_id(connection))
        return
    except ProviderNotFoundError:
        pass
    approved = installation.runtime_artifact
    if approved is None:
        return
    try:
        if installation.inspector.artifact() != approved:
            return
    except CapabilityCertificateError:
        return
    certificate = replace(
        connection, certificate_id=runtime_certificate_id(connection),
        certificate_scope="native_runtime_artifact",
        native_connection_certificate_id=connection.certificate_id,
        native_runtime_artifact_digest=approved.digest,
        native_connection_identity_digest=canonical_digest((
            connection.native_connection_identity_digest, approved.digest,
        )),
        legacy_projection_certificate_ids=(), native_model_catalog_digest="",
    )
    publish_capability_certificate(
        store, certificate=certificate, evidence=store.get_capability_evidence(connection.evidence_digest),
    )


def validate_native_runtime_certificate(store, connection, installation, *, now) -> None:
    if installation is None or installation.runtime_artifact is None:
        raise CapabilityCertificateError("native_runtime_artifact_unverified")
    try:
        certificate = store.get_capability_certificate(runtime_certificate_id(connection))
    except ProviderNotFoundError as error:
        raise CapabilityCertificateError("native_runtime_certificate_missing") from error
    status = store.get_capability_certificate_status(certificate.certificate_id)
    if status is None or status.status != "active" or now >= certificate.expires_at:
        raise CapabilityCertificateError("native_runtime_certificate_inactive")
    observed = installation.inspector.artifact()
    if observed != installation.runtime_artifact or observed.digest != certificate.native_runtime_artifact_digest:
        raise CapabilityCertificateError("native_runtime_artifact_mismatch")
    if (
        certificate.certificate_scope != "native_runtime_artifact"
        or certificate.native_connection_certificate_id != connection.certificate_id
        or certificate.native_connection_identity_digest != canonical_digest((
            connection.native_connection_identity_digest, observed.digest,
        ))
        or any(getattr(certificate, field) != getattr(connection, field) for field in (
            "runtime_engine_id", "adapter_id", "adapter_version", "adapter_artifact_digest",
            "model_provider_id", "provider_protocol", "provider_api_version", "suite_id",
            "suite_version", "test_run_id", "evidence_digest", "evidence_refs", "issued_at", "expires_at",
        ))
    ):
        raise CapabilityCertificateError("native_runtime_certificate_identity_mismatch")


__all__ = ["ensure_native_runtime_certificate", "runtime_certificate_id", "validate_native_runtime_certificate"]
