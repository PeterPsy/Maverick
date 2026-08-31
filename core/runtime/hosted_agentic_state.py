"""Provider-private state bridge for the shared hosted loop."""

from __future__ import annotations

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticSourceMetadata,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedProviderPrivateCodec,
)
from core.runtime.provider_private_state import (
    ProviderPrivateStateError,
    ProviderPrivateStateService,
    public_provider_private_reason,
)
from core.runtime.provider_state import ProviderPrivateEnvelope
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    require_agentic_feature,
)


_MAX_PROVIDER_STATE_LINEAGE_SOURCES = 4096


class HostedAgenticStateBridge:
    def __init__(
        self,
        *,
        service: ProviderPrivateStateService,
        codec: HostedProviderPrivateCodec,
    ) -> None:
        self.service = service
        self.codec = codec
        self._request_id: str | None = None
        self._request_source_metadata: tuple[AgenticSourceMetadata, ...] = ()
        self._continuation_source_metadata: tuple[AgenticSourceMetadata, ...] = ()

    def fence_turn(self, context) -> None:
        """Compatibility no-op: a turn fence is now the REQUEST_READY journal row."""
        if not str(context.correlation_id or "").strip():
            raise HostedAgenticLoopError("provider_private_state_invalid")

    def persist_request_identity(self, context, request: AgenticModelRequest) -> None:
        """Remember identity locally; the provider-step WAL is authoritative."""
        self._request_id = request.request_id
        self._request_source_metadata = request.source_metadata

    def read(self, context, authority) -> AgenticProviderPrivateState | None:
        self._continuation_source_metadata = ()
        state = self.service.store.get_provider_state(context.session.session_id)
        journals = self.service.store.list_provider_step_journals(
            session_id=context.session.session_id
        )
        if any(
            item.commit_status not in {"committed", "rolled_back"}
            for item in journals
        ):
            # A provider-state CAS can precede the journal commit in the saga.
            # It is not continuation authority until recovery seals that WAL half.
            raise HostedAgenticLoopError("provider_state_ambiguous")
        if state.provider_private_envelope is None:
            return None
        require_agentic_feature(
            MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
            "provider_private_state_disabled",
        )
        if not authority.allowed_capabilities.provider_private_state:
            raise HostedAgenticLoopError("provider_private_state_invalid")
        try:
            content = self.service.read_state(
                session_id=context.session.session_id,
                adapter_id=context.binding.adapter_id,
                adapter_version=context.binding.adapter_version,
                codec_id=self.codec.codec_id,
                codec_version=self.codec.codec_version,
                schema_version=self.codec.schema_version,
            )
        except ProviderPrivateStateError as error:
            raise HostedAgenticLoopError(public_provider_private_reason(error)) from error
        if content is None:
            return None
        envelope = state.provider_private_envelope
        if (
            envelope.codec_id,
            envelope.codec_version,
            envelope.schema_version,
            envelope.content_type,
        ) != (
            self.codec.codec_id,
            self.codec.codec_version,
            self.codec.schema_version,
            self.codec.content_type,
        ):
            raise HostedAgenticLoopError("provider_private_state_invalid")
        source_metadata = ()
        if (
            len(envelope.source_block_digests)
            == len(envelope.source_data_classes)
            == len(envelope.source_trust_levels)
            == len(envelope.source_provenances)
            == len(envelope.source_refs)
            == len(envelope.source_revisions)
            == len(envelope.source_resource_identities)
            == len(envelope.source_classification_revisions)
            == len(envelope.source_classification_authority_ids)
            == len(envelope.source_classification_authority_kinds)
            == len(envelope.source_classification_authority_refs)
            == len(envelope.source_classification_authority_revisions)
            == len(envelope.source_classification_authority_digests)
            == len(envelope.source_classification_authority_policy_revisions)
            == len(envelope.source_classification_authority_bounds)
        ):
            source_metadata = tuple(
                AgenticSourceMetadata(
                    source_block_digest=digest,
                    source_data_class=data_class,  # type: ignore[arg-type]
                    source_trust_level=trust_level,
                    provenance=provenance,
                    source_ref=source_ref,
                    source_revision=source_revision,
                    resource_identity=resource_identity,
                    classification_revision=classification_revision,
                    classification_authority_id=authority_id,
                    classification_authority_kind=authority_kind,
                    classification_authority_ref=authority_ref,
                    classification_authority_revision=authority_revision,
                    classification_authority_digest=authority_digest,
                    classification_authority_policy_revision=(
                        authority_policy_revision
                    ),
                    classification_authority_bound=authority_bound,
                )
                for (
                    digest,
                    data_class,
                    trust_level,
                    provenance,
                    source_ref,
                    source_revision,
                    resource_identity,
                    classification_revision,
                    authority_id,
                    authority_kind,
                    authority_ref,
                    authority_revision,
                    authority_digest,
                    authority_policy_revision,
                    authority_bound,
                ) in zip(
                    envelope.source_block_digests,
                    envelope.source_data_classes,
                    envelope.source_trust_levels,
                    envelope.source_provenances,
                    envelope.source_refs,
                    envelope.source_revisions,
                    envelope.source_resource_identities,
                    envelope.source_classification_revisions,
                    envelope.source_classification_authority_ids,
                    envelope.source_classification_authority_kinds,
                    envelope.source_classification_authority_refs,
                    envelope.source_classification_authority_revisions,
                    envelope.source_classification_authority_digests,
                    envelope.source_classification_authority_policy_revisions,
                    envelope.source_classification_authority_bounds,
                    strict=True,
                )
            )
        self._continuation_source_metadata = source_metadata
        return AgenticProviderPrivateState(
            codec_id=self.codec.codec_id,
            codec_version=self.codec.codec_version,
            schema_version=self.codec.schema_version,
            content_type=self.codec.content_type,
            content=content,
            source_metadata=source_metadata,
            effective_data_class=envelope.effective_data_class,  # type: ignore[arg-type]
            effective_trust_level=envelope.effective_trust_level,
            provider_request_id=envelope.provider_request_id,
            turn_generation=envelope.turn_generation,
        )

    def store(
        self,
        context,
        authority,
        provider_event: AgenticModelEvent,
    ) -> ProviderPrivateEnvelope:
        """Stage response state without making it authoritative for continuation."""
        require_agentic_feature(
            MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
            "provider_private_state_disabled",
        )
        if not authority.allowed_capabilities.provider_private_state:
            raise HostedAgenticLoopError("provider_private_state_invalid")
        state = provider_event.provider_private_state
        if state is None or (
            state.codec_id,
            state.codec_version,
            state.schema_version,
            state.content_type,
        ) != (
            self.codec.codec_id,
            self.codec.codec_version,
            self.codec.schema_version,
            self.codec.content_type,
        ):
            raise HostedAgenticLoopError("provider_private_state_invalid")
        if self._request_id is None:
            raise HostedAgenticLoopError("provider_private_state_invalid")
        try:
            return self.service.stage_state(
                session_id=context.session.session_id,
                adapter_id=context.binding.adapter_id,
                adapter_version=context.binding.adapter_version,
                codec_id=state.codec_id,
                codec_version=state.codec_version,
                schema_version=state.schema_version,
                content_type=state.content_type,
                payload=state.content,
                turn_generation=context.correlation_id,
                source_metadata=_provider_state_lineage_metadata(
                    self._request_source_metadata,
                    self._continuation_source_metadata,
                ),
                provider_request_id=self._request_id,
            )
        except ProviderPrivateStateError as error:
            raise HostedAgenticLoopError(public_provider_private_reason(error)) from error

    def promote(
        self,
        context,
        envelope: ProviderPrivateEnvelope,
        *,
        expected_revision: int,
    ):
        """Commit one exact staged envelope through the authoritative CAS."""
        try:
            return self.service.promote_staged_state(
                session_id=context.session.session_id,
                adapter_id=context.binding.adapter_id,
                adapter_version=context.binding.adapter_version,
                envelope=envelope,
                expected_revision=expected_revision,
            )
        except ProviderPrivateStateError as error:
            raise HostedAgenticLoopError(public_provider_private_reason(error)) from error

    def discard(self, context, envelope: ProviderPrivateEnvelope) -> bool:
        return self.service.discard_staged_state(
            session_id=context.session.session_id,
            adapter_id=context.binding.adapter_id,
            adapter_version=context.binding.adapter_version,
            envelope=envelope,
        )


def _provider_state_lineage_metadata(
    request_metadata: tuple[AgenticSourceMetadata, ...],
    continuation_metadata: tuple[AgenticSourceMetadata, ...],
) -> tuple[AgenticSourceMetadata, ...]:
    """Carry each mutable authority snapshot across provider-state generations."""
    merged = list(request_metadata)
    seen = {
        _classification_authority_identity(metadata)
        for metadata in request_metadata
        if metadata.classification_authority_bound is not False
    }
    for metadata in continuation_metadata:
        if metadata.classification_authority_bound is False:
            continue
        identity = _classification_authority_identity(metadata)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(metadata)
    if len(merged) > _MAX_PROVIDER_STATE_LINEAGE_SOURCES:
        raise HostedAgenticLoopError("provider_private_state_invalid")
    return tuple(merged)


def _classification_authority_identity(
    metadata: AgenticSourceMetadata,
) -> tuple[object, ...]:
    if metadata.classification_authority_bound is True:
        return (
            True,
            metadata.classification_authority_id,
            metadata.classification_authority_kind,
            metadata.classification_authority_ref,
            metadata.classification_authority_revision,
            metadata.classification_authority_digest,
            metadata.classification_authority_policy_revision,
        )
    return (
        None,
        metadata.source_block_digest,
        metadata.provenance,
        metadata.source_ref,
        metadata.source_revision,
        metadata.resource_identity,
    )
