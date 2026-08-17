"""Core-only access service for bounded provider-private continuation state."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import hmac
from typing import Literal

from core.runtime.errors import RuntimeProviderStateError
from core.runtime.private_payload_models import (
    PRIVATE_PAYLOAD_ENCRYPTION_PROFILE,
    RuntimePrivatePayloadContext,
    RuntimePrivatePayloadError,
)
from core.runtime.private_payload_store import EncryptedRuntimePrivatePayloadStore
from core.runtime.provider_state import ProviderPrivateEnvelope, RuntimeProviderState
from core.runtime.store import RuntimeStore


MAX_PROVIDER_PRIVATE_BLOB_BYTES = 2 * 1_048_576
MAX_PROVIDER_PRIVATE_SESSION_BYTES = 8 * 1_048_576
ProviderPrivateAccessPurpose = Literal["adapter", "recovery"]

_PUBLIC_PROVIDER_PRIVATE_REASONS = frozenset(
    {
        "provider_private_codec_mismatch",
        "provider_private_integrity_failed",
        "provider_private_quota_exceeded",
        "provider_private_size_invalid",
        "provider_private_state_unavailable",
    }
)


class ProviderPrivateStateError(RuntimeProviderStateError):
    """Fail-closed error carrying a stable recovery reason."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def public_provider_private_reason(error: ProviderPrivateStateError) -> str:
    """Expose only recovery-safe private-state failures outside the Core store."""
    if error.reason_code in _PUBLIC_PROVIDER_PRIVATE_REASONS:
        return error.reason_code
    return "provider_private_state_invalid"


class ProviderPrivateStateService:
    """Validate adapter identity around encrypted provider-private state access."""

    def __init__(self, *, store: RuntimeStore, payload_store: EncryptedRuntimePrivatePayloadStore) -> None:
        self.store = store
        self.payload_store = payload_store

    def store_state(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        content_type: str,
        payload: bytes,
        expected_revision: int,
        turn_generation: str | None = None,
        now: datetime | None = None,
    ) -> RuntimeProviderState:
        """Encrypt a blob and atomically attach its metadata to provider state."""
        session, binding, current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        if session.status not in {"created", "running"}:
            raise ProviderPrivateStateError("provider_private_session_not_writable")
        if current.revision != expected_revision:
            raise ProviderPrivateStateError("provider_private_revision_stale")
        if not turn_generation:
            raise ProviderPrivateStateError("provider_private_generation_required")
        if current.turn_generation is not None and current.turn_generation != turn_generation:
            raise ProviderPrivateStateError("provider_private_generation_stale")
        if not isinstance(payload, (bytes, bytearray)):
            raise ProviderPrivateStateError("provider_private_size_invalid")
        _validate_codec(codec_id, codec_version, schema_version, content_type)
        normalized_payload = bytes(payload)
        context = _private_context(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            codec_id=codec_id,
            codec_version=codec_version,
            schema_version=schema_version,
        )
        previous = current.provider_private_envelope
        try:
            opaque_state_ref = self.payload_store.put(
                context=context,
                locator_prefix="provider-private",
                payload=normalized_payload,
                max_blob_bytes=MAX_PROVIDER_PRIVATE_BLOB_BYTES,
                max_session_bytes=MAX_PROVIDER_PRIVATE_SESSION_BYTES,
                replace_ref=previous.opaque_state_ref if previous is not None else None,
            )
        except RuntimePrivatePayloadError as error:
            raise ProviderPrivateStateError(_provider_reason(error.reason_code)) from error
        timestamp = now or datetime.now(tz=UTC)
        envelope = ProviderPrivateEnvelope(
            schema_version=schema_version,
            codec_id=codec_id,
            codec_version=codec_version,
            content_type=content_type,
            opaque_state_ref=opaque_state_ref,
            content_sha256=hashlib.sha256(normalized_payload).hexdigest(),
            size_bytes=len(normalized_payload),
            encryption_profile=PRIVATE_PAYLOAD_ENCRYPTION_PROFILE,
            created_at=timestamp,
        )
        updated = replace(
            current,
            provider_private_envelope=envelope,
            turn_generation=turn_generation if turn_generation is not None else current.turn_generation,
            revision=current.revision + 1,
            updated_at=timestamp,
        )
        try:
            persisted = self.store.update_provider_state(updated, expected_revision=expected_revision)
        except RuntimeProviderStateError as error:
            self._delete(context, opaque_state_ref)
            raise ProviderPrivateStateError("provider_private_revision_stale") from error
        if previous is not None:
            previous_context = _private_context(
                workspace_id=session.workspace_id,
                session_id=session.session_id,
                runtime_engine_id=binding.runtime_engine_id,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                codec_id=previous.codec_id,
                codec_version=previous.codec_version,
                schema_version=previous.schema_version,
            )
            self._delete(previous_context, previous.opaque_state_ref)
        return persisted

    def read_state(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        purpose: ProviderPrivateAccessPurpose = "adapter",
    ) -> bytes | None:
        """Return plaintext only to the exact pinned adapter/codec or recovery caller."""
        if purpose not in {"adapter", "recovery"}:
            raise ProviderPrivateStateError("provider_private_access_denied")
        session, binding, state = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        envelope = state.provider_private_envelope
        if envelope is None:
            return None
        if (
            envelope.codec_id != codec_id
            or envelope.codec_version != codec_version
            or envelope.schema_version != schema_version
        ):
            raise ProviderPrivateStateError("provider_private_codec_mismatch")
        context = _private_context(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            codec_id=codec_id,
            codec_version=codec_version,
            schema_version=schema_version,
        )
        try:
            payload = self.payload_store.read(
                context=context,
                locator_prefix="provider-private",
                private_ref=envelope.opaque_state_ref,
            )
        except RuntimePrivatePayloadError as error:
            raise ProviderPrivateStateError(_provider_reason(error.reason_code)) from error
        if len(payload) != envelope.size_bytes or not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(), envelope.content_sha256
        ):
            raise ProviderPrivateStateError("provider_private_integrity_failed")
        return payload

    def _bound_state(self, *, session_id: str, adapter_id: str, adapter_version: str):
        session = self.store.get_session(session_id)
        binding = session.execution_binding
        if binding is None:
            raise ProviderPrivateStateError("provider_private_binding_missing")
        if binding.adapter_id != adapter_id or binding.adapter_version != adapter_version:
            raise ProviderPrivateStateError("provider_private_adapter_mismatch")
        state = self.store.get_provider_state(session_id)
        if (
            state.workspace_id != session.workspace_id
            or state.runtime_engine_id != binding.runtime_engine_id
            or state.model_provider_id != binding.model_provider_id
        ):
            raise ProviderPrivateStateError("provider_private_binding_mismatch")
        return session, binding, state

    def _delete(self, context: RuntimePrivatePayloadContext, private_ref: str) -> None:
        try:
            self.payload_store.delete(
                context=context,
                locator_prefix="provider-private",
                private_ref=private_ref,
            )
        except RuntimePrivatePayloadError:
            pass


def _private_context(
    *,
    workspace_id: str,
    session_id: str,
    runtime_engine_id: str,
    adapter_id: str,
    adapter_version: str,
    codec_id: str,
    codec_version: str,
    schema_version: str,
) -> RuntimePrivatePayloadContext:
    return RuntimePrivatePayloadContext(
        namespace="provider-state",
        workspace_id=workspace_id,
        session_id=session_id,
        binding_fields=(
            ("runtime_engine_id", runtime_engine_id),
            ("adapter_id", adapter_id),
            ("adapter_version", adapter_version),
            ("codec_id", codec_id),
            ("codec_version", codec_version),
            ("schema_version", schema_version),
        ),
    )


def _validate_codec(codec_id: str, codec_version: str, schema_version: str, content_type: str) -> None:
    values = (codec_id, codec_version, schema_version, content_type)
    if any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in values):
        raise ProviderPrivateStateError("provider_private_codec_invalid")


def _provider_reason(reason_code: str) -> str:
    if reason_code.endswith("quota_exceeded"):
        return "provider_private_quota_exceeded"
    if reason_code.endswith("size_invalid"):
        return "provider_private_size_invalid"
    if reason_code.endswith("integrity_failed"):
        return "provider_private_integrity_failed"
    return "provider_private_state_unavailable"
