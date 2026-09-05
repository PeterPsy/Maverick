"""Trusted production composition for data-driven Maverick Agent runtimes."""

from __future__ import annotations

from datetime import datetime

from core.providers.google_interactions_client import (
    GoogleInteractionsAgenticClient,
)
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_CONTENT_TYPE,
    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
)
from core.providers.google_interactions_state import inspect_google_interaction_state
from core.providers.google_interactions_transport import (
    GoogleInteractionsHttpTransport,
)
from core.providers.hosted_context_compactors import (
    compact_google_stateless_history,
    compact_openrouter_history,
)
from core.providers.hosted_endpoint_preflight import (
    OpenRouterCompletionRequestPreflight,
    preflight_google_interactions_request,
)
from core.providers.maverick_agent_builtins import (
    builtin_maverick_agent_publications,
    builtin_maverick_protocol_adapters,
    builtin_maverick_provider_configs,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentOnboardingCatalog,
    MaverickProtocolRuntimeRegistration,
    MaverickProviderConfig,
)
from core.providers.openrouter_agentic_client import (
    OpenRouterAgenticClient,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
)
from core.providers.openrouter_agentic_state import inspect_openrouter_chat_state
from core.providers.openrouter_agentic_transport import (
    OpenRouterAgenticHttpTransport,
)
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.hosted_harness_recipes import HostedHarnessRecipeManifest
from core.runtime.hosted_provider_runtime import (
    GOOGLE_HOSTED_FINALIZATION_POLICY,
    OPENROUTER_HOSTED_FINALIZATION_POLICY,
    HostedProviderRuntime,
    HostedProviderRuntimeRegistry,
)


def build_builtin_maverick_agent_onboarding_catalog(
    *,
    now: datetime | None = None,
) -> MaverickAgentOnboardingCatalog:
    """Assemble the production catalog from trusted adapters and data records."""
    catalog = MaverickAgentOnboardingCatalog()
    for manifest in builtin_maverick_protocol_adapters():
        try:
            runtime_factory = _PROTOCOL_RUNTIME_FACTORIES[
                manifest.protocol_adapter_id
            ]
        except KeyError as error:
            raise RuntimeError("maverick_protocol_factory_missing") from error
        catalog.register_protocol_adapter(
            MaverickProtocolRuntimeRegistration(
                manifest=manifest,
                runtime_factory=runtime_factory,
            )
        )
    for config in builtin_maverick_provider_configs():
        catalog.register_provider_config(config)
    for publication in builtin_maverick_agent_publications(now=now):
        catalog.register_profile(publication)
    return catalog


def build_hosted_provider_runtime_registry(
    *,
    onboarding_catalog: MaverickAgentOnboardingCatalog | None = None,
) -> HostedProviderRuntimeRegistry:
    """Build the runtime registry exclusively through production onboarding."""
    catalog = onboarding_catalog or build_builtin_maverick_agent_onboarding_catalog()
    return catalog.build_runtime_registry()


def _google_interactions_runtime(
    config: MaverickProviderConfig,
    recipe: HostedHarnessRecipeManifest,
) -> HostedProviderRuntime:
    return HostedProviderRuntime(
        model_provider_id=config.model_provider_id,
        provider_protocol=config.provider_protocol,
        provider_api_version=config.provider_api_version,
        client=GoogleInteractionsAgenticClient(
            model_id=recipe.model_id,
            state_mode="stateless",
            transport=GoogleInteractionsHttpTransport(
                endpoint=config.endpoint_url,
            ),
            token_cost_policy=config.token_cost_policy,
            routing_constraint=config.routing_constraint,
            allowed_upstream_ids=config.routing_constraint.allowed_upstream_ids,
            upstream_provider_names=config.upstream_provider_names,
            resolved_model_ids=config.resolved_model_ids,
        ),
        private_codec=HostedProviderPrivateCodec(
            codec_id=GOOGLE_INTERACTIONS_CODEC_ID,
            codec_version=GOOGLE_INTERACTIONS_CODEC_VERSION,
            schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
            content_type=GOOGLE_INTERACTIONS_CONTENT_TYPE,
        ),
        cost_estimator=config.token_cost_policy.request_ceiling_microusd,
        finalization_policy=GOOGLE_HOSTED_FINALIZATION_POLICY,
        private_state_inspector=lambda content: inspect_google_interaction_state(
            content,
            mode="stateless",
        ),
        recipe=recipe,
        context_compactor=compact_google_stateless_history,
        request_preflight=preflight_google_interactions_request,
    )


def _openrouter_chat_runtime(
    config: MaverickProviderConfig,
    recipe: HostedHarnessRecipeManifest,
) -> HostedProviderRuntime:
    return HostedProviderRuntime(
        model_provider_id=config.model_provider_id,
        provider_protocol=config.provider_protocol,
        provider_api_version=config.provider_api_version,
        client=OpenRouterAgenticClient(
            model_id=recipe.model_id,
            transport=OpenRouterAgenticHttpTransport(
                endpoint=config.endpoint_url,
            ),
            token_cost_policy=config.token_cost_policy,
            routing_constraint=config.routing_constraint,
            allowed_upstream_ids=config.routing_constraint.allowed_upstream_ids,
            upstream_provider_names=config.upstream_provider_names,
            resolved_model_ids=config.resolved_model_ids,
        ),
        private_codec=HostedProviderPrivateCodec(
            codec_id=OPENROUTER_AGENTIC_CODEC_ID,
            codec_version=OPENROUTER_AGENTIC_CODEC_VERSION,
            schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
            content_type=OPENROUTER_AGENTIC_CONTENT_TYPE,
        ),
        cost_estimator=config.token_cost_policy.request_ceiling_microusd,
        finalization_policy=OPENROUTER_HOSTED_FINALIZATION_POLICY,
        private_state_inspector=inspect_openrouter_chat_state,
        recipe=recipe,
        context_compactor=compact_openrouter_history,
        request_preflight=OpenRouterCompletionRequestPreflight(
            upstream_provider_names=config.upstream_provider_names,
        ),
    )


_PROTOCOL_RUNTIME_FACTORIES = {
    "google-interactions-protocol": _google_interactions_runtime,
    "openrouter-chat-completions-protocol": _openrouter_chat_runtime,
}


__all__ = [
    "build_builtin_maverick_agent_onboarding_catalog",
    "build_hosted_provider_runtime_registry",
]
