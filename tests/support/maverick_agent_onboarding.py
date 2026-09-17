"""Shared fixtures for Maverick Agent onboarding contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.agentic_data_policies import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
)
from core.providers.google_agentic_profile import (
    GOOGLE_DEFAULT_REASONING_EFFORT,
    GOOGLE_REASONING_EFFORTS,
    google_agentic_capabilities,
    google_agentic_preview_policy,
)
from core.providers.google_interactions_client import GOOGLE_AGENTIC_MODEL_REVISION
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentProfilePublication,
)
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.hosted_provider_model_config import GOOGLE_HOSTED_MODEL_CONFIG
from tests.support.collections import FakeCollection


NOW = datetime(2026, 9, 4, tzinfo=UTC)


def provider_store() -> ProviderDocumentStore:
    return ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
        )
    )


def google_publication(
    *,
    model_id: str = "gemini-3.6-flash",
    profile_revision: str = "test-1",
) -> MaverickAgentProfilePublication:
    model_config = replace(
        GOOGLE_HOSTED_MODEL_CONFIG,
        model_id=model_id,
        model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
    )
    profile = AgenticProfileDefinition(
        definition_id=f"test-profile-{model_id}-{profile_revision}",
        display_name=f"Test {model_id}",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="google-ai-studio",
        model_id=model_id,
        model_revision=model_config.model_revision,
        model_revision_policy=model_config.model_revision_policy,
        provider_protocol=model_config.provider_protocol,
        provider_api_version=model_config.provider_api_version,
        adapter_id=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_id,
        adapter_version_constraint=(
            f"=={GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_version}"
        ),
        routing_constraint=GOOGLE_INTERACTIONS_PROVIDER_CONFIG.routing_constraint,
        policy_ceiling=google_agentic_preview_policy(),
        capabilities=google_agentic_capabilities(),
        reasoning_efforts=GOOGLE_REASONING_EFFORTS,
        default_reasoning_effort=GOOGLE_DEFAULT_REASONING_EFFORT,
        created_at=NOW,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        context_policy=model_config.context_policy,
    )
    return MaverickAgentProfilePublication(
        adapter=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
        provider_config=GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
        model_config=model_config,
        profile=profile,
    )


class RuntimeClient:
    """Minimal introspectable protocol client for composition tests."""

    def __init__(self, config, model_config) -> None:
        self.model_id = model_config.model_id
        self.endpoint_url = config.endpoint_url
        self.routing_constraint = config.routing_constraint
        self.allowed_upstream_ids = config.routing_constraint.allowed_upstream_ids
        self.upstream_provider_names = config.upstream_provider_names
        self.resolved_model_ids = config.resolved_model_ids
        self.token_cost_policy = config.token_cost_policy

    async def create_response(self, request, *, credential):
        from core.providers.agentic_protocol import AgenticModelEvent

        yield AgenticModelEvent(event_type="completed", request_id=request.request_id, ordinal=1)


__all__ = ["NOW", "RuntimeClient", "google_publication", "provider_store"]
