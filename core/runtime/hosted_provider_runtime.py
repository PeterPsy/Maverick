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
from core.runtime.hosted_harness_recipes import HostedHarnessRecipeManifest
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
    recipe: HostedHarnessRecipeManifest | None = None
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
        recipe = runtime.recipe
        if recipe is not None:
            if identity != (
                recipe.model_provider_id,
                recipe.provider_protocol,
                recipe.provider_api_version,
            ):
                raise ValueError("Hosted harness recipe provider identity is invalid.")
        candidates = self._runtimes.setdefault(identity, [])
        if recipe is None and any(item.recipe is None for item in candidates):
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
            if item.recipe is None or item.recipe.model_id == binding.model_id
        ]
        runtime = matching[0] if len(matching) == 1 else None
        if runtime is None:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        if self._identity(runtime) != identity:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        self._validate_recipe_binding(runtime, binding)
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
                    "" if item.recipe is None else item.recipe.model_id,
                ),
            )
        )

    @staticmethod
    def _validate_recipe_binding(runtime: HostedProviderRuntime, binding) -> None:
        recipe = runtime.recipe
        if recipe is None:
            return
        if (
            binding.model_provider_id != recipe.model_provider_id
            or binding.model_id != recipe.model_id
            or binding.model_revision != recipe.model_revision
            or binding.model_revision_policy != recipe.model_revision_policy
            or binding.provider_protocol != recipe.provider_protocol
            or binding.provider_api_version != recipe.provider_api_version
            or binding.routing_constraint_snapshot.endpoint_id != recipe.endpoint_id
            or tuple(binding.routing_constraint_snapshot.allowed_upstream_ids)
            != recipe.upstream_ids
            or runtime.endpoint_id != recipe.endpoint_id
            or runtime.allowed_upstream_ids != recipe.upstream_ids
            or binding.context_policy_snapshot != recipe.context_policy
            or binding.reasoning_effort
            not in recipe.support_flags.reasoning_efforts
            or recipe.context_policy.max_request_input_tokens
            > recipe.support_flags.input_token_limit
        ):
            raise HostedAgenticLoopError("runtime_configuration_mismatch")

    @staticmethod
    def _identity(runtime: HostedProviderRuntime) -> tuple[str, str, str | None]:
        provider_id = str(runtime.model_provider_id or "").strip()
        protocol = str(runtime.provider_protocol or "").strip()
        if not provider_id or not protocol:
            raise ValueError("Hosted provider runtime identity is incomplete.")
        return provider_id, protocol, runtime.provider_api_version
