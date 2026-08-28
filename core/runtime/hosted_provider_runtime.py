"""Exact provider client and private-codec routing for the hosted tool loop."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.agentic_protocol import AgenticModelProviderClient
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedCostEstimator,
    HostedFinalizationPolicy,
    HostedProviderPrivateCodec,
    HostedProviderStateInspector,
)
from core.runtime.remote_agentic_admission import require_remote_agentic_dispatch


# These reserves exceed each pinned estimator for a 262,144-byte tool result,
# the 2,048-token terminal output ceiling, and ordinary request framing.
GOOGLE_HOSTED_FINALIZATION_POLICY = HostedFinalizationPolicy(
    exploration_max_output_tokens=2_048,
    finalization_max_output_tokens=2_048,
    finalization_cost_reserve_microusd_per_attempt=200_000,
    finalization_time_reserve_seconds_per_attempt=20.0,
    max_recovery_attempts=1,
)
OPENROUTER_HOSTED_FINALIZATION_POLICY = HostedFinalizationPolicy(
    exploration_max_output_tokens=2_048,
    finalization_max_output_tokens=2_048,
    finalization_cost_reserve_microusd_per_attempt=20_000,
    finalization_time_reserve_seconds_per_attempt=20.0,
    max_recovery_attempts=1,
)


@dataclass(frozen=True)
class HostedProviderRuntime:
    """One certified model-provider protocol implementation."""

    model_provider_id: str
    provider_protocol: str
    provider_api_version: str | None
    client: AgenticModelProviderClient
    private_codec: HostedProviderPrivateCodec
    cost_estimator: HostedCostEstimator
    finalization_policy: HostedFinalizationPolicy
    credential_required: bool = True
    private_state_inspector: HostedProviderStateInspector | None = None


class HostedProviderRuntimeRegistry:
    """Resolve provider implementations by every pinned protocol identity field."""

    def __init__(self) -> None:
        self._runtimes: dict[tuple[str, str, str | None], HostedProviderRuntime] = {}

    def register(self, runtime: HostedProviderRuntime) -> HostedProviderRuntime:
        identity = self._identity(runtime)
        if identity in self._runtimes:
            raise ValueError("Hosted provider runtime identity is already registered.")
        self._runtimes[identity] = runtime
        return runtime

    def resolve(self, binding) -> HostedProviderRuntime:
        require_remote_agentic_dispatch(binding)
        identity = (
            binding.model_provider_id,
            binding.provider_protocol,
            binding.provider_api_version,
        )
        runtime = self._runtimes.get(identity)
        if runtime is None:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        return runtime

    def artifact_components(self) -> tuple[object, ...]:
        """Return deterministic provider client components for certification hashing."""
        components = []
        for identity in sorted(self._runtimes, key=lambda item: tuple(str(value) for value in item)):
            client = self._runtimes[identity].client
            components.append(client)
            components.extend(tuple(getattr(client, "artifact_components", ())))
        return tuple(components)

    @staticmethod
    def _identity(runtime: HostedProviderRuntime) -> tuple[str, str, str | None]:
        provider_id = str(runtime.model_provider_id or "").strip()
        protocol = str(runtime.provider_protocol or "").strip()
        if not provider_id or not protocol:
            raise ValueError("Hosted provider runtime identity is incomplete.")
        return provider_id, protocol, runtime.provider_api_version
