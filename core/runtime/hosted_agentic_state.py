"""Provider-private state bridge for the shared hosted loop."""

from __future__ import annotations

from core.providers.agentic_protocol import (
    AgenticModelEvent,
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticSourceMetadata,
)
from core.runtime.agentic_runtime_service import update_runtime_provider_state
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedProviderPrivateCodec,
)
from core.runtime.provider_private_state import (
    ProviderPrivateStateError,
    ProviderPrivateStateService,
    public_provider_private_reason,
)
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
        current = self.service.store.get_provider_state(context.session.session_id)
        if current.turn_generation == context.correlation_id:
            return
        try:
            update_runtime_provider_state(
                self.service.store,
                session_id=context.session.session_id,
                updates={"turn_generation": context.correlation_id},
            )
        except Exception as error:
            raise HostedAgenticLoopError("provider_private_state_invalid") from error

    def persist_request_identity(self, context, request: AgenticModelRequest) -> None:
        """Journal the provider request id before the transport can accept it."""
        self._request_id = request.request_id
        self._request_source_metadata = request.source_metadata
        try:
            update_runtime_provider_state(
                self.service.store,
                session_id=context.session.session_id,
                updates={
                    "provider_request_id": request.request_id,
                    "turn_generation": context.correlation_id,
                },
            )
        except Exception as error:
            raise HostedAgenticLoopError("provider_private_state_invalid") from error

    def read(self, context, authority) -> AgenticProviderPrivateState | None:
        state = self.service.store.get_provider_state(context.session.session_id)
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

    def store(self, context, authority, provider_event: AgenticModelEvent) -> None:
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
        current = self.service.store.get_provider_state(context.session.session_id)
        if self._request_id is None or current.provider_request_id != self._request_id:
            raise HostedAgenticLoopError("provider_private_state_invalid")
        try:
            self.service.store_state(
                session_id=context.session.session_id,
                adapter_id=context.binding.adapter_id,
                adapter_version=context.binding.adapter_version,
                codec_id=state.codec_id,
                codec_version=state.codec_version,
                schema_version=state.schema_version,
                content_type=state.content_type,
                payload=state.content,
                expected_revision=current.revision,
                turn_generation=context.correlation_id,
                source_metadata=self._request_source_metadata,
                provider_request_id=self._request_id,
            )
        except ProviderPrivateStateError as error:
            raise HostedAgenticLoopError(public_provider_private_reason(error)) from error
