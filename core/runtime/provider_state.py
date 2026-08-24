"""Mutable provider-private continuation metadata for runtime sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from core.runtime.private_payload_models import PRIVATE_PAYLOAD_ENCRYPTION_PROFILE


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
