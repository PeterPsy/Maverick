"""Packaged preview certification for the migrated Codex runtime."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.agentic_profiles import CODEX_PROFILE_ARTIFACT_DIGEST
from core.providers.capability_models import CapabilityCertificate, RuntimeCapabilitySet
from core.providers.certificate_service import (
    build_capability_evidence,
    publish_capability_certificate,
    revoke_capability_certificate,
    runtime_adapter_artifact_digest,
)
from core.providers.errors import CapabilityCertificateError, ProviderNotFoundError
from core.providers.models import ProviderDefinition
from core.providers.native_agent_certificates import (
    native_connection_identity_digest,
    native_connection_reference,
    native_installation_for_adapter,
    validate_native_connection_certificate,
)
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
    now: datetime | None = None,
) -> CapabilityCertificate:
    """Project the certified Codex connection onto one immutable model profile."""
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    if artifact_digest != CODEX_PROFILE_ARTIFACT_DIGEST:
        raise CapabilityCertificateError("profile_revision_artifact_mismatch")
    connection = ensure_codex_connection_certificate(store, definition=definition, adapter=adapter)
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
            "model_revision": definition.model_revision,
            "model_revision_policy": definition.model_revision_policy,
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
    validate_native_connection_certificate(
        store, connection, now=now, installation=native_installation_for_adapter(adapter),
    )
    evidence = store.get_capability_evidence(connection.evidence_digest)
    certificate = replace(
        connection,
        certificate_id=definition.capability_certificate_id,
        certificate_scope="model",
        native_connection_certificate_id=connection.certificate_id,
        legacy_projection_certificate_ids=(),
        model_id=definition.model_id,
        model_revision=definition.model_revision,
        model_revision_policy=definition.model_revision_policy,
        native_model_catalog_digest=definition.native_model_catalog_digest,
        certified_reasoning_efforts=reasoning_efforts,
        default_reasoning_effort=default_reasoning_effort,
    )
    return publish_capability_certificate(store, certificate=certificate, evidence=evidence)


def ensure_codex_connection_certificate(
    store: ProviderStore,
    *,
    definition: AgenticProfileDefinition,
    adapter: object,
) -> CapabilityCertificate:
    """Adopt the existing Codex release once; catalog changes never renew it."""
    from core.providers.native_agent_builtins import build_codex_native_installation
    from core.providers.native_runtime_certificates import ensure_native_runtime_certificate

    installation = getattr(adapter, "installation", None) or build_codex_native_installation(adapter)
    artifact_digest = runtime_adapter_artifact_digest(adapter)
    if artifact_digest != CODEX_PROFILE_ARTIFACT_DIGEST:
        raise CapabilityCertificateError("profile_revision_artifact_mismatch")
    certificate_id = native_connection_reference(installation, definition.model_provider_id)
    identity_digest = native_connection_identity_digest(
        installation, model_provider_id=definition.model_provider_id, artifact_digest=artifact_digest,
    )
    try:
        existing = store.get_capability_certificate(certificate_id)
    except ProviderNotFoundError:
        existing = None
    if existing is not None:
        if (
            existing.certificate_scope != "native_connection"
            or existing.native_connection_identity_digest != identity_digest
        ):
            raise CapabilityCertificateError("native_agent_connection_identity_mismatch")
        ensure_native_runtime_certificate(store, existing, installation)
        return existing
    legacy = sorted(
        (item for item in store.list_capability_certificates()
         if item.certificate_scope == "model" and not item.native_connection_certificate_id
         and item.runtime_engine_id == definition.runtime_engine_id
         and item.model_provider_id == definition.model_provider_id
         and item.adapter_artifact_digest == artifact_digest),
        key=lambda item: (item.issued_at, item.certificate_id),
    )
    if legacy:
        source = legacy[0]
        certificate = replace(
            source, certificate_id=certificate_id, certificate_scope="native_connection",
            model_id="*", model_revision=None, model_revision_policy="provider_alias",
            certified_reasoning_efforts=(), default_reasoning_effort=None,
            native_connection_identity_digest=identity_digest,
            native_model_catalog_digest="",
            legacy_projection_certificate_ids=tuple(item.certificate_id for item in legacy),
            expires_at=min(item.expires_at for item in legacy),
        )
        stored = publish_capability_certificate(
            store, certificate=certificate,
            evidence=store.get_capability_evidence(source.evidence_digest),
        )
        if any(
            (status := store.get_capability_certificate_status(item.certificate_id)) is None
            or status.status != "active" for item in legacy
        ):
            status = store.get_capability_certificate_status(stored.certificate_id)
            revoke_capability_certificate(
                store, certificate_id=stored.certificate_id,
                expected_revision=status.revision, reason="legacy_projection_revoked",
            )
        ensure_native_runtime_certificate(store, stored, installation)
        return stored
    test_run_id = (
        f"packaged:{certificate_id}:"
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
            "native_connection_identity_digest": identity_digest,
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
        certificate_id=certificate_id,
        schema_version="3",
        certificate_scope="native_connection",
        native_connection_identity_digest=identity_digest,
        runtime_engine_id=definition.runtime_engine_id,
        adapter_id=str(getattr(adapter, "adapter_id", definition.adapter_id)),
        adapter_version=str(getattr(adapter, "adapter_version", "")),
        adapter_artifact_digest=artifact_digest,
        model_provider_id=definition.model_provider_id,
        model_id="*",
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
            attachment_modalities=("file",),
            app_references=True,
            confirmations=False,
        ),
        certified_reasoning_efforts=(),
        default_reasoning_effort=None,
        suite_id=evidence.suite_id,
        suite_version=evidence.suite_version,
        test_run_id=evidence.test_run_id,
        evidence_digest=evidence.evidence_digest,
        evidence_refs=evidence.evidence_refs,
        issued_at=evidence.recorded_at,
        expires_at=evidence.recorded_at + timedelta(days=CODEX_CERTIFICATION_VALIDITY_DAYS),
    )
    stored = publish_capability_certificate(store, certificate=certificate, evidence=evidence)
    ensure_native_runtime_certificate(store, stored, installation)
    return stored
