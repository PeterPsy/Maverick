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

    def fence_turn(self, context) -> None:
        """Compatibility no-op: a turn fence is now the REQUEST_READY journal row."""
        if not str(context.correlation_id or "").strip():
            raise HostedAgenticLoopError("provider_private_state_invalid")

    def persist_request_identity(self, context, request: AgenticModelRequest) -> None:
        """Remember identity locally; the provider-step WAL is authoritative."""
        self._request_id = request.request_id
        self._request_source_metadata = request.source_metadata

    def read(self, context, authority) -> AgenticProviderPrivateState | None:
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
        ):
            source_metadata = tuple(
                AgenticSourceMetadata(
                    source_block_digest=digest,
                    source_data_class=data_class,  # type: ignore[arg-type]
                    source_trust_level=trust_level,
                    provenance="provider_state",
                )
                for digest, data_class, trust_level in zip(
                    envelope.source_block_digests,
                    envelope.source_data_classes,
                    envelope.source_trust_levels,
                    strict=True,
                )
            )
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
                source_metadata=self._request_source_metadata,
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
