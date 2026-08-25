"""Exact provider client and private-codec routing for the hosted tool loop."""

from __future__ import annotations

from dataclasses import dataclass

from core.providers.agentic_protocol import AgenticModelProviderClient
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedCostEstimator,
    HostedProviderPrivateCodec,
)
from core.runtime.remote_agentic_admission import require_remote_agentic_dispatch


@dataclass(frozen=True)
class HostedProviderRuntime:
    """One certified model-provider protocol implementation."""

    model_provider_id: str
    provider_protocol: str
    provider_api_version: str | None
    client: AgenticModelProviderClient
    private_codec: HostedProviderPrivateCodec
    cost_estimator: HostedCostEstimator


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
