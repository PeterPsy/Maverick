"""Core-only access service for bounded provider-private continuation state."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Literal

from core.egress.classification import (
    KNOWN_DATA_CLASSES,
    KNOWN_TRUST_LEVELS,
    join_data_classes,
    join_trust_levels,
)
from core.providers.agentic_protocol import AgenticSourceMetadata
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
MAX_PROVIDER_FINAL_OUTPUT_BYTES = 2 * 1_048_576
MAX_PROVIDER_FINAL_OUTPUT_SESSION_BYTES = 8 * 1_048_576
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

    def stage_state(
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
        turn_generation: str,
        source_metadata: tuple[AgenticSourceMetadata, ...] = (),
        provider_request_id: str | None,
        now: datetime | None = None,
    ) -> ProviderPrivateEnvelope:
        """Encrypt provider state without attaching it to authoritative state."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        if session.status not in {"created", "running", "stopping"}:
            raise ProviderPrivateStateError("provider_private_session_not_writable")
        if not turn_generation:
            raise ProviderPrivateStateError("provider_private_generation_required")
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
        deterministic_ref = (
            _staged_provider_private_ref(
                session_id=session.session_id,
                provider_request_id=provider_request_id,
            )
            if provider_request_id
            else None
        )
        if deterministic_ref is not None:
            try:
                existing_payload = self.payload_store.read(
                    context=context,
                    locator_prefix="provider-private",
                    private_ref=deterministic_ref,
                )
            except RuntimePrivatePayloadError:
                existing_payload = None
            if existing_payload is not None:
                if not hmac.compare_digest(existing_payload, normalized_payload):
                    raise ProviderPrivateStateError(
                        "provider_staged_state_identity_conflict"
                    )
                return _provider_private_envelope(
                    opaque_state_ref=deterministic_ref,
                    payload=existing_payload,
                    codec_id=codec_id,
                    codec_version=codec_version,
                    schema_version=schema_version,
                    content_type=content_type,
                    source_metadata=source_metadata,
                    provider_request_id=provider_request_id,
                    turn_generation=turn_generation,
                    now=now,
                )
        try:
            opaque_state_ref = self.payload_store.put(
                context=context,
                locator_prefix="provider-private",
                payload=normalized_payload,
                max_blob_bytes=MAX_PROVIDER_PRIVATE_BLOB_BYTES,
                max_session_bytes=MAX_PROVIDER_PRIVATE_SESSION_BYTES,
                replace_ref=deterministic_ref,
                private_ref=deterministic_ref,
                idempotent_ref=deterministic_ref is not None,
            )
        except RuntimePrivatePayloadError as error:
            if error.reason_code == "private_payload_identity_conflict":
                raise ProviderPrivateStateError(
                    "provider_staged_state_identity_conflict"
                ) from error
            raise ProviderPrivateStateError(_provider_reason(error.reason_code)) from error
        return _provider_private_envelope(
            opaque_state_ref=opaque_state_ref,
            payload=normalized_payload,
            codec_id=codec_id,
            codec_version=codec_version,
            schema_version=schema_version,
            content_type=content_type,
            source_metadata=source_metadata,
            provider_request_id=provider_request_id,
            turn_generation=turn_generation,
            now=now,
        )

    def recover_staged_state_for_request(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        content_type: str,
        provider_request_id: str,
        turn_generation: str,
    ) -> ProviderPrivateEnvelope | None:
        """Recover the deterministic blob written just before its WAL attachment."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        _validate_codec(codec_id, codec_version, schema_version, content_type)
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
        private_ref = _staged_provider_private_ref(
            session_id=session.session_id,
            provider_request_id=provider_request_id,
        )
        try:
            payload = self.payload_store.read(
                context=context,
                locator_prefix="provider-private",
                private_ref=private_ref,
            )
        except RuntimePrivatePayloadError:
            return None
        return _provider_private_envelope(
            opaque_state_ref=private_ref,
            payload=payload,
            codec_id=codec_id,
            codec_version=codec_version,
            schema_version=schema_version,
            content_type=content_type,
            source_metadata=(),
            provider_request_id=provider_request_id,
            turn_generation=turn_generation,
            now=None,
        )

    def promote_staged_state(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        envelope: ProviderPrivateEnvelope,
        expected_revision: int,
        now: datetime | None = None,
    ) -> RuntimeProviderState:
        """CAS-promote one staged envelope; a matching replay is idempotent."""
        session, binding, current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        if current.provider_private_envelope is not None and (
            current.provider_private_envelope.opaque_state_ref == envelope.opaque_state_ref
        ):
            return current
        if session.status not in {"created", "running", "stopping", "failed"}:
            raise ProviderPrivateStateError("provider_private_session_not_writable")
        if current.revision != expected_revision:
            raise ProviderPrivateStateError("provider_private_revision_stale")
        self.read_staged_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            envelope=envelope,
        )
        previous = current.provider_private_envelope
        timestamp = now or datetime.now(tz=UTC)
        updated = replace(
            current,
            provider_request_id=envelope.provider_request_id,
            provider_private_envelope=envelope,
            turn_generation=envelope.turn_generation,
            revision=current.revision + 1,
            updated_at=timestamp,
        )
        try:
            persisted = self.store.update_provider_state(
                updated,
                expected_revision=expected_revision,
            )
        except RuntimeProviderStateError as error:
            latest = self.store.get_provider_state(session_id)
            if latest.provider_private_envelope is not None and (
                latest.provider_private_envelope.opaque_state_ref == envelope.opaque_state_ref
            ):
                return latest
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

    def read_staged_state(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        envelope: ProviderPrivateEnvelope,
    ) -> bytes:
        """Read one exact staged blob through its pinned binding and codec."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        context = _private_context(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            codec_id=envelope.codec_id,
            codec_version=envelope.codec_version,
            schema_version=envelope.schema_version,
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

    def discard_staged_state(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        envelope: ProviderPrivateEnvelope,
    ) -> bool:
        """Delete a non-authoritative staged blob after a proven rollback."""
        session, binding, current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        committed = current.provider_private_envelope
        if committed is not None and committed.opaque_state_ref == envelope.opaque_state_ref:
            return False
        context = _private_context(
            workspace_id=session.workspace_id,
            session_id=session.session_id,
            runtime_engine_id=binding.runtime_engine_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            codec_id=envelope.codec_id,
            codec_version=envelope.codec_version,
            schema_version=envelope.schema_version,
        )
        try:
            return self.payload_store.delete(
                context=context,
                locator_prefix="provider-private",
                private_ref=envelope.opaque_state_ref,
            )
        except RuntimePrivatePayloadError:
            return False

    def store_recovery_detail(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        detail: dict[str, object],
    ) -> str | None:
        """Persist bounded Core-only recovery evidence and return only its ref."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        try:
            payload = json.dumps(
                detail,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(payload) > 64 * 1024:
                return None
            return self.payload_store.put(
                context=_private_context(
                    workspace_id=session.workspace_id,
                    session_id=session.session_id,
                    runtime_engine_id=binding.runtime_engine_id,
                    adapter_id=adapter_id,
                    adapter_version=adapter_version,
                    codec_id=codec_id,
                    codec_version=codec_version,
                    schema_version=schema_version,
                ),
                locator_prefix="provider-recovery",
                payload=payload,
                max_blob_bytes=64 * 1024,
                max_session_bytes=512 * 1024,
            )
        except (RuntimePrivatePayloadError, TypeError, ValueError):
            return None

    def store_final_output(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        journal_id: str,
        provider_request_id: str,
        output_text: str,
    ) -> tuple[str, str, int]:
        """Durably encrypt one deterministic final-output outbox payload."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        if not journal_id or not provider_request_id or not isinstance(output_text, str):
            raise ProviderPrivateStateError("provider_final_output_invalid")
        try:
            payload = json.dumps(
                {"text": output_text},
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ProviderPrivateStateError("provider_final_output_invalid") from error
        private_ref = _final_output_private_ref(
            session_id=session.session_id,
            journal_id=journal_id,
            provider_request_id=provider_request_id,
        )
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
            stored_ref = self.payload_store.put(
                context=context,
                locator_prefix="provider-final-output",
                payload=payload,
                max_blob_bytes=MAX_PROVIDER_FINAL_OUTPUT_BYTES,
                max_session_bytes=MAX_PROVIDER_FINAL_OUTPUT_SESSION_BYTES,
                private_ref=private_ref,
                idempotent_ref=True,
            )
        except RuntimePrivatePayloadError as error:
            reason = (
                "provider_final_output_identity_conflict"
                if error.reason_code == "private_payload_identity_conflict"
                else "provider_final_output_unavailable"
            )
            raise ProviderPrivateStateError(reason) from error
        return stored_ref, hashlib.sha256(payload).hexdigest(), len(payload)

    def read_final_output(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        private_ref: str,
        content_sha256: str,
        size_bytes: int,
    ) -> str:
        """Read and verify one exact Core-private final-output outbox payload."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
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
                locator_prefix="provider-final-output",
                private_ref=private_ref,
            )
        except RuntimePrivatePayloadError as error:
            raise ProviderPrivateStateError("provider_final_output_unavailable") from error
        if (
            not isinstance(size_bytes, int)
            or size_bytes < 1
            or len(payload) != size_bytes
            or len(content_sha256) != 64
            or not hmac.compare_digest(
                hashlib.sha256(payload).hexdigest(),
                content_sha256,
            )
        ):
            raise ProviderPrivateStateError("provider_final_output_integrity_failed")
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderPrivateStateError("provider_final_output_integrity_failed") from error
        if (
            not isinstance(document, dict)
            or set(document) != {"text"}
            or not isinstance(document["text"], str)
        ):
            raise ProviderPrivateStateError("provider_final_output_integrity_failed")
        return document["text"]

    def recover_final_output_for_request(
        self,
        *,
        session_id: str,
        adapter_id: str,
        adapter_version: str,
        codec_id: str,
        codec_version: str,
        schema_version: str,
        journal_id: str,
        provider_request_id: str,
    ) -> tuple[str, str, int] | None:
        """Recover a deterministic outbox write interrupted before WAL attachment."""
        session, binding, _current = self._bound_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
        )
        private_ref = _final_output_private_ref(
            session_id=session.session_id,
            journal_id=journal_id,
            provider_request_id=provider_request_id,
        )
        try:
            payload = self.payload_store.read(
                context=_private_context(
                    workspace_id=session.workspace_id,
                    session_id=session.session_id,
                    runtime_engine_id=binding.runtime_engine_id,
                    adapter_id=adapter_id,
                    adapter_version=adapter_version,
                    codec_id=codec_id,
                    codec_version=codec_version,
                    schema_version=schema_version,
                ),
                locator_prefix="provider-final-output",
                private_ref=private_ref,
            )
            document = json.loads(payload.decode("utf-8"))
        except (
            RuntimePrivatePayloadError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return None
        if (
            not isinstance(document, dict)
            or set(document) != {"text"}
            or not isinstance(document["text"], str)
        ):
            return None
        return private_ref, hashlib.sha256(payload).hexdigest(), len(payload)

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
        source_metadata: tuple[AgenticSourceMetadata, ...] = (),
        provider_request_id: str | None = None,
        now: datetime | None = None,
    ) -> RuntimeProviderState:
        """Compatibility facade: stage, then CAS-promote through the same saga primitive."""
        current = self.store.get_provider_state(session_id)
        if current.revision != expected_revision:
            raise ProviderPrivateStateError("provider_private_revision_stale")
        if (
            current.turn_generation is not None
            and turn_generation is not None
            and current.turn_generation != turn_generation
        ):
            raise ProviderPrivateStateError("provider_private_generation_stale")
        envelope = self.stage_state(
            session_id=session_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            codec_id=codec_id,
            codec_version=codec_version,
            schema_version=schema_version,
            content_type=content_type,
            payload=payload,
            turn_generation=str(turn_generation or ""),
            source_metadata=source_metadata,
            provider_request_id=provider_request_id,
            now=now,
        )
        try:
            return self.promote_staged_state(
                session_id=session_id,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                envelope=envelope,
                expected_revision=expected_revision,
                now=now,
            )
        except Exception:
            self.discard_staged_state(
                session_id=session_id,
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                envelope=envelope,
            )
            raise

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


def _provider_private_envelope(
    *,
    opaque_state_ref: str,
    payload: bytes,
    codec_id: str,
    codec_version: str,
    schema_version: str,
    content_type: str,
    source_metadata: tuple[AgenticSourceMetadata, ...],
    provider_request_id: str | None,
    turn_generation: str,
    now: datetime | None,
) -> ProviderPrivateEnvelope:
    """Build redaction-safe taint metadata for a staged or committed blob."""
    source_block_digests = tuple(
        metadata.source_block_digest.lower()
        for metadata in source_metadata
        if _is_sha256(metadata.source_block_digest)
    )
    complete_metadata = (
        bool(source_metadata)
        and len(source_block_digests) == len(source_metadata)
        and all(
            metadata.source_data_class in KNOWN_DATA_CLASSES
            and metadata.source_trust_level in KNOWN_TRUST_LEVELS
            for metadata in source_metadata
        )
    )
    source_data_classes = (
        tuple(metadata.source_data_class for metadata in source_metadata)
        if complete_metadata
        else ("unclassified",)
    )
    source_trust_levels = (
        tuple(metadata.source_trust_level for metadata in source_metadata)
        if complete_metadata
        else ("untrusted_external",)
    )
    if not complete_metadata:
        source_block_digests = ()
    authority_ids = tuple(
        metadata.classification_authority_id for metadata in source_metadata
    ) if complete_metadata else ()
    authority_kinds = tuple(
        metadata.classification_authority_kind for metadata in source_metadata
    ) if complete_metadata else ()
    authority_refs = tuple(
        metadata.classification_authority_ref for metadata in source_metadata
    ) if complete_metadata else ()
    authority_revisions = tuple(
        metadata.classification_authority_revision for metadata in source_metadata
    ) if complete_metadata else ()
    authority_digests = tuple(
        metadata.classification_authority_digest for metadata in source_metadata
    ) if complete_metadata else ()
    authority_policy_revisions = tuple(
        metadata.classification_authority_policy_revision
        for metadata in source_metadata
    ) if complete_metadata else ()
    authority_bounds = tuple(
        metadata.classification_authority_bound for metadata in source_metadata
    ) if complete_metadata else ()
    source_provenances = tuple(
        metadata.provenance for metadata in source_metadata
    ) if complete_metadata else ()
    source_refs = tuple(
        metadata.source_ref for metadata in source_metadata
    ) if complete_metadata else ()
    source_revisions = tuple(
        metadata.source_revision for metadata in source_metadata
    ) if complete_metadata else ()
    source_resource_identities = tuple(
        metadata.resource_identity for metadata in source_metadata
    ) if complete_metadata else ()
    source_classification_revisions = tuple(
        metadata.classification_revision for metadata in source_metadata
    ) if complete_metadata else ()
    return ProviderPrivateEnvelope(
        schema_version=schema_version,
        codec_id=codec_id,
        codec_version=codec_version,
        content_type=content_type,
        opaque_state_ref=opaque_state_ref,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        encryption_profile=PRIVATE_PAYLOAD_ENCRYPTION_PROFILE,
        created_at=now or datetime.now(tz=UTC),
        source_block_digests=source_block_digests,
        source_data_classes=source_data_classes,
        source_trust_levels=source_trust_levels,
        source_provenances=source_provenances,
        source_refs=source_refs,
        source_revisions=source_revisions,
        source_resource_identities=source_resource_identities,
        source_classification_revisions=source_classification_revisions,
        source_classification_authority_ids=authority_ids,
        source_classification_authority_kinds=authority_kinds,
        source_classification_authority_refs=authority_refs,
        source_classification_authority_revisions=authority_revisions,
        source_classification_authority_digests=authority_digests,
        source_classification_authority_policy_revisions=(
            authority_policy_revisions
        ),
        source_classification_authority_bounds=authority_bounds,
        effective_data_class=join_data_classes(source_data_classes),
        effective_trust_level=join_trust_levels(source_trust_levels),
        codec_identity=":".join((codec_id, codec_version, schema_version)),
        provider_request_id=provider_request_id,
        turn_generation=turn_generation,
    )


def _staged_provider_private_ref(
    *,
    session_id: str,
    provider_request_id: str,
) -> str:
    token = hashlib.sha256(
        b"maverick.provider-stage.v1\x00"
        + session_id.encode("utf-8")
        + b"\x00"
        + provider_request_id.encode("utf-8")
    ).hexdigest()[:32]
    return f"provider-private:v1:{token}"


def _final_output_private_ref(
    *,
    session_id: str,
    journal_id: str,
    provider_request_id: str,
) -> str:
    token = hashlib.sha256(
        b"maverick.provider-final-output.v1\x00"
        + session_id.encode("utf-8")
        + b"\x00"
        + journal_id.encode("utf-8")
        + b"\x00"
        + provider_request_id.encode("utf-8")
    ).hexdigest()[:32]
    return f"provider-final-output:v1:{token}"


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


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)
