"""Mutable provider-private continuation metadata for runtime sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from core.runtime.private_payload_models import PRIVATE_PAYLOAD_ENCRYPTION_PROFILE
from core.egress.classification import (
    KNOWN_DATA_CLASSES,
    KNOWN_PROVENANCE,
    KNOWN_TRUST_LEVELS,
    join_data_classes,
    join_trust_levels,
)


@dataclass(frozen=True)
class ProviderPrivateEnvelope:
    """Redaction-safe metadata for one Core-owned opaque provider blob."""

    schema_version: str
    codec_id: str
    codec_version: str
    content_type: str
    opaque_state_ref: str
    content_sha256: str
    size_bytes: int
    encryption_profile: str
    created_at: datetime
    source_block_digests: tuple[str, ...] = ()
    source_data_classes: tuple[str, ...] = ("unclassified",)
    source_trust_levels: tuple[str, ...] = ("untrusted_external",)
    source_provenances: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_revisions: tuple[str, ...] = ()
    source_resource_identities: tuple[str, ...] = ()
    source_classification_revisions: tuple[int | None, ...] = ()
    source_classification_authority_ids: tuple[str, ...] = ()
    source_classification_authority_kinds: tuple[str, ...] = ()
    source_classification_authority_refs: tuple[str, ...] = ()
    source_classification_authority_revisions: tuple[int | None, ...] = ()
    source_classification_authority_digests: tuple[str, ...] = ()
    source_classification_authority_policy_revisions: tuple[str, ...] = ()
    source_classification_authority_bounds: tuple[bool | None, ...] = ()
    effective_data_class: str = "unclassified"
    effective_trust_level: str = "untrusted_external"
    codec_identity: str = ""
    provider_request_id: str | None = None
    turn_generation: str | None = None


@dataclass(frozen=True)
class RuntimeProviderState:
    """Revisioned mutable provider state separated from the session binding."""

    session_id: str
    workspace_id: str
    runtime_engine_id: str
    model_provider_id: str
    continuation_id: str | None
    provider_thread_id: str | None
    provider_request_id: str | None
    provider_private_envelope: ProviderPrivateEnvelope | None
    revision: int
    turn_generation: str | None
    updated_at: datetime
    continuation_handoff_id: str | None = None
    continuation_successor_session_id: str | None = None


def provider_private_envelope_from_document(
    document: Mapping[str, object],
) -> ProviderPrivateEnvelope:
    """Hydrate and minimally validate persisted private-envelope metadata."""
    payload = dict(document)
    payload["source_block_digests"] = tuple(payload.get("source_block_digests", ()))
    payload["source_data_classes"] = tuple(
        payload.get("source_data_classes", ("unclassified",)) or ("unclassified",)
    )
    payload["source_trust_levels"] = tuple(
        payload.get("source_trust_levels", ("untrusted_external",))
        or ("untrusted_external",)
    )
    source_count = len(payload["source_block_digests"])
    payload["source_provenances"] = tuple(
        payload.get("source_provenances", ("provider_state",) * source_count)
    )
    payload["source_refs"] = tuple(
        payload.get("source_refs", ("",) * source_count)
    )
    payload["source_revisions"] = tuple(
        payload.get("source_revisions", ("",) * source_count)
    )
    payload["source_resource_identities"] = tuple(
        payload.get("source_resource_identities", ("",) * source_count)
    )
    payload["source_classification_revisions"] = tuple(
        payload.get("source_classification_revisions", (None,) * source_count)
    )
    payload["source_classification_authority_ids"] = tuple(
        payload.get("source_classification_authority_ids", ("",) * source_count)
    )
    payload["source_classification_authority_kinds"] = tuple(
        payload.get("source_classification_authority_kinds", ("",) * source_count)
    )
    payload["source_classification_authority_refs"] = tuple(
        payload.get("source_classification_authority_refs", ("",) * source_count)
    )
    payload["source_classification_authority_revisions"] = tuple(
        payload.get(
            "source_classification_authority_revisions",
            (None,) * source_count,
        )
    )
    payload["source_classification_authority_digests"] = tuple(
        payload.get("source_classification_authority_digests", ("",) * source_count)
    )
    payload["source_classification_authority_policy_revisions"] = tuple(
        payload.get(
            "source_classification_authority_policy_revisions",
            ("",) * source_count,
        )
    )
    payload["source_classification_authority_bounds"] = tuple(
        payload.get(
            "source_classification_authority_bounds",
            (None,) * source_count,
        )
    )
    payload.setdefault("effective_data_class", "unclassified")
    payload.setdefault("effective_trust_level", "untrusted_external")
    payload.setdefault("codec_identity", "")
    payload.setdefault("provider_request_id", None)
    payload.setdefault("turn_generation", None)
    envelope = ProviderPrivateEnvelope(**payload)
    if not envelope.schema_version or not envelope.codec_id or not envelope.codec_version:
        raise ValueError("Provider private envelope identity is incomplete.")
    if not envelope.content_type or not envelope.opaque_state_ref.startswith("provider-private:v1:"):
        raise ValueError("Provider private envelope locator is invalid.")
    if len(envelope.content_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in envelope.content_sha256.lower()
    ):
        raise ValueError("Provider private envelope digest is invalid.")
    if envelope.size_bytes < 1:
        raise ValueError("Provider private envelope size is invalid.")
    if envelope.encryption_profile != PRIVATE_PAYLOAD_ENCRYPTION_PROFILE:
        raise ValueError("Provider private envelope encryption profile is unsupported.")
    if any(not _is_sha256(value) for value in envelope.source_block_digests):
        raise ValueError("Provider private envelope source digest is invalid.")
    if any(value not in KNOWN_DATA_CLASSES for value in envelope.source_data_classes):
        raise ValueError("Provider private envelope source data class is invalid.")
    if any(value not in KNOWN_TRUST_LEVELS for value in envelope.source_trust_levels):
        raise ValueError("Provider private envelope source trust is invalid.")
    source_identity_columns = (
        envelope.source_provenances,
        envelope.source_refs,
        envelope.source_revisions,
        envelope.source_resource_identities,
        envelope.source_classification_revisions,
    )
    if any(
        len(column) != len(envelope.source_block_digests)
        for column in source_identity_columns
    ):
        raise ValueError("Provider private envelope source lineage is incomplete.")
    if any(value not in KNOWN_PROVENANCE for value in envelope.source_provenances):
        raise ValueError("Provider private envelope source provenance is invalid.")
    authority_columns = (
        envelope.source_classification_authority_ids,
        envelope.source_classification_authority_kinds,
        envelope.source_classification_authority_refs,
        envelope.source_classification_authority_revisions,
        envelope.source_classification_authority_digests,
        envelope.source_classification_authority_policy_revisions,
        envelope.source_classification_authority_bounds,
    )
    if any(len(column) != len(envelope.source_block_digests) for column in authority_columns):
        raise ValueError("Provider private envelope authority lineage is incomplete.")
    for index, bound in enumerate(envelope.source_classification_authority_bounds):
        lineage = (
            envelope.source_classification_authority_ids[index],
            envelope.source_classification_authority_kinds[index],
            envelope.source_classification_authority_refs[index],
            envelope.source_classification_authority_revisions[index],
            envelope.source_classification_authority_digests[index],
            envelope.source_classification_authority_policy_revisions[index],
        )
        if bound is False and lineage != ("", "", "", None, "", ""):
            raise ValueError("Provider private envelope authority lineage is invalid.")
        if bound is True and not _authority_lineage_is_well_formed(lineage):
            raise ValueError("Provider private envelope authority lineage is invalid.")
        if bound is not True and bound is not False and bound is not None:
            raise ValueError("Provider private envelope authority lineage is invalid.")
    if envelope.effective_data_class != join_data_classes(envelope.source_data_classes):
        raise ValueError("Provider private envelope effective data class is invalid.")
    if envelope.effective_trust_level != join_trust_levels(envelope.source_trust_levels):
        raise ValueError("Provider private envelope effective trust is invalid.")
    expected_codec_identity = ":".join(
        (envelope.codec_id, envelope.codec_version, envelope.schema_version)
    )
    if envelope.codec_identity and envelope.codec_identity != expected_codec_identity:
        raise ValueError("Provider private envelope codec identity is invalid.")
    return envelope


def runtime_provider_state_from_document(document: Mapping[str, object]) -> RuntimeProviderState:
    """Hydrate nested provider-private metadata without exposing its content."""
    payload = dict(document)
    envelope = payload.get("provider_private_envelope")
    if isinstance(envelope, Mapping):
        payload["provider_private_envelope"] = provider_private_envelope_from_document(envelope)
    elif envelope is not None and not isinstance(envelope, ProviderPrivateEnvelope):
        raise ValueError("Provider private envelope must be an object.")
    return RuntimeProviderState(**payload)


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _authority_lineage_is_well_formed(lineage) -> bool:
    authority_id, kind, ref, revision, digest, policy_revision = lineage
    return bool(
        str(authority_id).strip()
        and str(kind).strip()
        and str(ref).strip()
        and isinstance(revision, int)
        and not isinstance(revision, bool)
        and revision >= 1
        and _is_sha256(digest)
        and str(policy_revision).strip()
    )
