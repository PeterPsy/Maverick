"""Trusted composition of data-driven hosted harness recipe runtimes."""

from __future__ import annotations

from core.providers.google_interactions_client import (
    GoogleInteractionsAgenticClient,
    google_36_flash_request_ceiling_microusd,
)
from core.providers.google_interactions_models import (
    GOOGLE_INTERACTIONS_CODEC_ID,
    GOOGLE_INTERACTIONS_CODEC_VERSION,
    GOOGLE_INTERACTIONS_CONTENT_TYPE,
    GOOGLE_INTERACTIONS_SCHEMA_VERSION,
)
from core.providers.google_interactions_state import inspect_google_interaction_state
from core.providers.hosted_context_compactors import (
    compact_google_stateless_history,
    compact_openrouter_history,
)
from core.providers.hosted_endpoint_preflight import (
    preflight_google_interactions_request,
    preflight_openrouter_completion_request,
)
from core.providers.openrouter_agentic_client import (
    OpenRouterAgenticClient,
    openrouter_deepinfra_v4_flash_request_ceiling_microusd,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_CODEC_ID,
    OPENROUTER_AGENTIC_CODEC_VERSION,
    OPENROUTER_AGENTIC_CONTENT_TYPE,
    OPENROUTER_AGENTIC_SCHEMA_VERSION,
)
from core.providers.openrouter_agentic_state import inspect_openrouter_chat_state
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.hosted_harness_recipes import (
    GOOGLE_GOVERNED_WORKSPACE_RECIPE,
    OPENROUTER_GOVERNED_WORKSPACE_RECIPE,
)
from core.runtime.hosted_provider_runtime import (
    GOOGLE_HOSTED_FINALIZATION_POLICY,
    OPENROUTER_HOSTED_FINALIZATION_POLICY,
    HostedProviderRuntime,
    HostedProviderRuntimeRegistry,
)


def build_hosted_provider_runtime_registry() -> HostedProviderRuntimeRegistry:
    """Build runtimes entirely from exact registered recipe identities."""
    registry = HostedProviderRuntimeRegistry()
    registry.register(
        HostedProviderRuntime(
            model_provider_id=GOOGLE_GOVERNED_WORKSPACE_RECIPE.model_provider_id,
            provider_protocol=GOOGLE_GOVERNED_WORKSPACE_RECIPE.provider_protocol,
            provider_api_version=GOOGLE_GOVERNED_WORKSPACE_RECIPE.provider_api_version,
            client=GoogleInteractionsAgenticClient(
                model_id=GOOGLE_GOVERNED_WORKSPACE_RECIPE.model_id,
                state_mode="stateless",
            ),
            private_codec=HostedProviderPrivateCodec(
                codec_id=GOOGLE_INTERACTIONS_CODEC_ID,
                codec_version=GOOGLE_INTERACTIONS_CODEC_VERSION,
                schema_version=GOOGLE_INTERACTIONS_SCHEMA_VERSION,
                content_type=GOOGLE_INTERACTIONS_CONTENT_TYPE,
            ),
            cost_estimator=google_36_flash_request_ceiling_microusd,
            finalization_policy=GOOGLE_HOSTED_FINALIZATION_POLICY,
            private_state_inspector=lambda content: inspect_google_interaction_state(
                content,
                mode="stateless",
            ),
            recipe=GOOGLE_GOVERNED_WORKSPACE_RECIPE,
            context_compactor=compact_google_stateless_history,
            request_preflight=preflight_google_interactions_request,
        )
    )
    registry.register(
        HostedProviderRuntime(
            model_provider_id=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.model_provider_id,
            provider_protocol=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.provider_protocol,
            provider_api_version=(
                OPENROUTER_GOVERNED_WORKSPACE_RECIPE.provider_api_version
            ),
            client=OpenRouterAgenticClient(
                model_id=OPENROUTER_GOVERNED_WORKSPACE_RECIPE.model_id,
            ),
            private_codec=HostedProviderPrivateCodec(
                codec_id=OPENROUTER_AGENTIC_CODEC_ID,
                codec_version=OPENROUTER_AGENTIC_CODEC_VERSION,
                schema_version=OPENROUTER_AGENTIC_SCHEMA_VERSION,
                content_type=OPENROUTER_AGENTIC_CONTENT_TYPE,
            ),
            cost_estimator=(
                openrouter_deepinfra_v4_flash_request_ceiling_microusd
            ),
            finalization_policy=OPENROUTER_HOSTED_FINALIZATION_POLICY,
            private_state_inspector=inspect_openrouter_chat_state,
            recipe=OPENROUTER_GOVERNED_WORKSPACE_RECIPE,
            context_compactor=compact_openrouter_history,
            request_preflight=preflight_openrouter_completion_request,
        )
    )
    return registry


__all__ = ["build_hosted_provider_runtime_registry"]
