"""Exact provider client and private-codec routing for the hosted tool loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.providers.agentic_protocol import AgenticModelProviderClient
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedCostEstimator,
    HostedFinalizationPolicy,
    HostedProviderPrivateCodec,
    HostedProviderStateInspector,
)
from core.runtime.hosted_context_management import HostedProviderStateCompactor
from core.runtime.full_workspace_contract import MAVERICK_AGENT_EXECUTION_FAMILY
from core.runtime.hosted_harness_recipes import HostedHarnessRecipeManifest
from core.runtime.remote_agentic_admission import require_remote_agentic_dispatch


# These reserves exceed each pinned estimator for every terminal request whose
# complete byte projection remains within the 262,144-token input ceiling.
GOOGLE_HOSTED_FINALIZATION_POLICY = HostedFinalizationPolicy(
    exploration_max_output_tokens=2_048,
    finalization_max_output_tokens=2_048,
    finalization_cost_reserve_microusd_per_attempt=550_000,
    finalization_time_reserve_seconds_per_attempt=20.0,
    max_recovery_attempts=1,
)
OPENROUTER_HOSTED_FINALIZATION_POLICY = HostedFinalizationPolicy(
    exploration_max_output_tokens=2_048,
    finalization_max_output_tokens=2_048,
    finalization_cost_reserve_microusd_per_attempt=35_000,
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
    recipe: HostedHarnessRecipeManifest | None = None
    context_compactor: HostedProviderStateCompactor | None = None
    request_preflight: Callable[[object, object], object] | None = None


class HostedProviderRuntimeRegistry:
    """Resolve provider implementations by every pinned protocol identity field."""

    def __init__(self) -> None:
        self._runtimes: dict[
            tuple[str, str, str | None], list[HostedProviderRuntime]
        ] = {}
        self._recipes: dict[tuple[str, str], HostedProviderRuntime] = {}

    def register(self, runtime: HostedProviderRuntime) -> HostedProviderRuntime:
        identity = self._identity(runtime)
        recipe = runtime.recipe
        if recipe is not None:
            recipe_identity = (recipe.recipe_id, recipe.revision)
            if recipe_identity in self._recipes:
                raise ValueError("Hosted harness recipe identity is already registered.")
            if identity != (
                recipe.model_provider_id,
                recipe.provider_protocol,
                recipe.provider_api_version,
            ):
                raise ValueError("Hosted harness recipe provider identity is invalid.")
            self._recipes[recipe_identity] = runtime
        candidates = self._runtimes.setdefault(identity, [])
        if recipe is None and any(item.recipe is None for item in candidates):
            raise ValueError("Hosted provider runtime identity is already registered.")
        candidates.append(runtime)
        return runtime

    def resolve(self, binding) -> HostedProviderRuntime:
        require_remote_agentic_dispatch(binding)
        identity = (
            binding.model_provider_id,
            binding.provider_protocol,
            binding.provider_api_version,
        )
        recipe_id = str(getattr(binding, "harness_recipe_id", "") or "")
        recipe_revision = str(
            getattr(binding, "harness_recipe_revision", "") or ""
        )
        if recipe_id or recipe_revision:
            if not recipe_id or not recipe_revision:
                raise HostedAgenticLoopError("harness_recipe_mismatch")
            runtime = self._recipes.get((recipe_id, recipe_revision))
        else:
            candidates = self._runtimes.get(identity, [])
            legacy = [item for item in candidates if item.recipe is None]
            runtime = legacy[0] if len(legacy) == 1 else None
        if runtime is None:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        if self._identity(runtime) != identity:
            raise HostedAgenticLoopError("provider_protocol_unavailable")
        self._validate_recipe_binding(runtime, binding)
        return runtime

    def artifact_components(self) -> tuple[object, ...]:
        """Return deterministic provider client components for certification hashing."""
        components = []
        for identity in sorted(
            self._runtimes,
            key=lambda item: tuple(str(value) for value in item),
        ):
            for runtime in sorted(
                self._runtimes[identity],
                key=lambda item: (
                    "" if item.recipe is None else item.recipe.recipe_id,
                    "" if item.recipe is None else item.recipe.revision,
                ),
            ):
                client = runtime.client
                components.append(client)
                components.extend(tuple(getattr(client, "artifact_components", ())))
                if runtime.context_compactor is not None:
                    components.append(runtime.context_compactor)
                if runtime.request_preflight is not None:
                    components.append(runtime.request_preflight)
        return tuple(components)

    @staticmethod
    def _validate_recipe_binding(runtime: HostedProviderRuntime, binding) -> None:
        recipe = runtime.recipe
        if recipe is None:
            if any(
                str(getattr(binding, field_name, "") or "")
                for field_name in (
                    "harness_recipe_id",
                    "harness_recipe_revision",
                    "harness_recipe_digest",
                    "provider_capability_catalog_digest",
                    "semantic_projection_compiler_revision",
                    "tool_contract_revision",
                )
            ) or getattr(binding, "context_policy_snapshot", None) is not None:
                raise HostedAgenticLoopError("harness_recipe_mismatch")
            return
        expected = {
            "harness_recipe_id": recipe.recipe_id,
            "harness_recipe_revision": recipe.revision,
            "harness_recipe_digest": recipe.recipe_digest,
            "provider_capability_catalog_digest": (
                recipe.capability_catalog_digest
            ),
            "semantic_projection_compiler_revision": (
                recipe.semantic_projection_compiler_revision
            ),
            "tool_contract_revision": recipe.tool_contract_revision,
        }
        if any(
            str(getattr(binding, field_name, "") or "") != value
            for field_name, value in expected.items()
        ):
            reason = (
                "provider_capability_catalog_mismatch"
                if str(
                    getattr(binding, "provider_capability_catalog_digest", "")
                    or ""
                )
                != recipe.capability_catalog_digest
                else "harness_recipe_mismatch"
            )
            raise HostedAgenticLoopError(reason)
        if (
            str(getattr(binding, "execution_family", "") or "")
            != MAVERICK_AGENT_EXECUTION_FAMILY
            or binding.model_provider_id != recipe.model_provider_id
            or binding.model_id != recipe.model_id
            or binding.provider_protocol != recipe.provider_protocol
            or binding.provider_api_version != recipe.provider_api_version
            or binding.routing_constraint_snapshot.endpoint_id != recipe.endpoint_id
            or tuple(binding.routing_constraint_snapshot.allowed_upstream_ids)
            != recipe.upstream_ids
            or binding.context_policy_snapshot != recipe.context_policy
            or binding.reasoning_effort
            not in recipe.support_flags.reasoning_efforts
            or recipe.context_policy.max_request_input_tokens
            > recipe.support_flags.input_token_limit
        ):
            raise HostedAgenticLoopError("harness_recipe_mismatch")

    @staticmethod
    def _identity(runtime: HostedProviderRuntime) -> tuple[str, str, str | None]:
        provider_id = str(runtime.model_provider_id or "").strip()
        protocol = str(runtime.provider_protocol or "").strip()
        if not provider_id or not protocol:
            raise ValueError("Hosted provider runtime identity is incomplete.")
        return provider_id, protocol, runtime.provider_api_version
