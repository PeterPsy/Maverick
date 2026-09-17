"""Exact provider client and private-codec routing for the hosted tool loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from core.providers.agentic_protocol import AgenticModelProviderClient
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedCostEstimator,
    HostedFinalizationPolicy,
    HostedProviderPrivateCodec,
    HostedProviderStateInspector,
)
from core.runtime.hosted_context_management import HostedProviderStateCompactor
from core.runtime.hosted_provider_model_config import HostedProviderModelConfig
from core.runtime.remote_agentic_admission import (
    require_remote_agentic_runtime_availability,
)

if TYPE_CHECKING:
    from core.providers.maverick_agent_onboarding import MaverickProtocolAdapterManifest


@dataclass(frozen=True)
class HostedProviderRuntime:
    """One configured model-provider protocol implementation."""

    model_provider_id: str
    provider_protocol: str
    provider_api_version: str | None
    client: AgenticModelProviderClient
    private_codec: HostedProviderPrivateCodec
    cost_estimator: HostedCostEstimator
    finalization_policy: HostedFinalizationPolicy
    credential_required: bool = True
    private_state_inspector: HostedProviderStateInspector | None = None
    model_config: HostedProviderModelConfig | None = None
    context_compactor: HostedProviderStateCompactor | None = None
    request_preflight: Callable[[object, object], object] | None = None
    endpoint_id: str = ""
    endpoint_url: str = ""
    allowed_upstream_ids: tuple[str, ...] = ()
    # Supplied by the executable factory, never copied from publication data.
    implementation_manifest: MaverickProtocolAdapterManifest | None = None


class HostedProviderRuntimeRegistry:
    """Resolve provider implementations by every pinned protocol identity field."""

    def __init__(self) -> None:
        self._runtimes: dict[
            tuple[str, str, str | None], list[HostedProviderRuntime]
        ] = {}

    def register(self, runtime: HostedProviderRuntime) -> HostedProviderRuntime:
        identity = self._identity(runtime)
        model_config = runtime.model_config
        if model_config is not None:
            if identity != (
                model_config.model_provider_id,
                model_config.provider_protocol,
                model_config.provider_api_version,
            ):
                raise ValueError("Hosted model config provider identity is invalid.")
        candidates = self._runtimes.setdefault(identity, [])
        if model_config is None and any(item.model_config is None for item in candidates):
            raise ValueError("Hosted provider runtime identity is already registered.")
        candidates.append(runtime)
        return runtime

    def resolve(self, binding) -> HostedProviderRuntime:
        require_remote_agentic_runtime_availability(binding)
        identity = (
            binding.model_provider_id,
            binding.provider_protocol,
            binding.provider_api_version,
        )
        candidates = self._runtimes.get(identity, [])
        matching = [
            item
            for item in candidates
            if item.model_config is None or item.model_config.model_id == binding.model_id
        ]
        runtime = matching[0] if len(matching) == 1 else None
        if runtime is None:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        if self._identity(runtime) != identity:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        self._validate_model_config_binding(runtime, binding)
        return runtime


    def runtimes(self) -> tuple[HostedProviderRuntime, ...]:
        """Return the registered runtimes in the same deterministic order."""
        return tuple(
            runtime
            for identity in sorted(
                self._runtimes,
                key=lambda item: tuple(str(value) for value in item),
            )
            for runtime in sorted(
                self._runtimes[identity],
                key=lambda item: (
                    "" if item.model_config is None else item.model_config.model_id,
                ),
            )
        )

    @staticmethod
    def _validate_model_config_binding(runtime: HostedProviderRuntime, binding) -> None:
        model_config = runtime.model_config
        if model_config is None:
            return
        if (
            binding.model_provider_id != model_config.model_provider_id
            or binding.model_id != model_config.model_id
            or binding.model_revision != model_config.model_revision
            or binding.model_revision_policy != model_config.model_revision_policy
            or binding.provider_protocol != model_config.provider_protocol
            or binding.provider_api_version != model_config.provider_api_version
            or binding.routing_constraint_snapshot.endpoint_id != model_config.endpoint_id
            or tuple(binding.routing_constraint_snapshot.allowed_upstream_ids)
            != model_config.upstream_ids
            or runtime.endpoint_id != model_config.endpoint_id
            or runtime.allowed_upstream_ids != model_config.upstream_ids
            or binding.context_policy_snapshot != model_config.context_policy
            or binding.reasoning_effort
            not in model_config.support_flags.reasoning_efforts
            or model_config.context_policy.max_request_input_tokens
            > model_config.support_flags.input_token_limit
        ):
            raise HostedAgenticLoopError("runtime_configuration_mismatch")

    @staticmethod
    def _identity(runtime: HostedProviderRuntime) -> tuple[str, str, str | None]:
        provider_id = str(runtime.model_provider_id or "").strip()
        protocol = str(runtime.provider_protocol or "").strip()
        if not provider_id or not protocol:
            raise ValueError("Hosted provider runtime identity is incomplete.")
        return provider_id, protocol, runtime.provider_api_version
