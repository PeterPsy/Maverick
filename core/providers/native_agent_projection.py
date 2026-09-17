"""Project native catalog model metadata into direct runtime configs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.errors import AgenticProfileError
from core.providers.models import ProviderDefinition
from core.providers.native_agent_catalog import NativeAgentCatalogModel

if TYPE_CHECKING:
    from core.providers.store import ProviderStore


def codex_model_profile_projection(
    store: ProviderStore,
    profile: AgenticProfileDefinition,
    provider_definition: ProviderDefinition,
) -> AgenticProfileDefinition:
    option = next(
        (item for item in provider_definition.model_options if item.model_id == profile.model_id),
        None,
    )
    if option is None:
        raise AgenticProfileError("native_agent_model_unavailable")
    revision = option.metadata.get("model_revision")
    policy = option.metadata.get(
        "model_revision_policy", "exact" if revision is not None else "provider_alias",
    )
    if policy not in {"exact", "provider_alias"} or (policy == "exact" and not revision):
        raise AgenticProfileError("native_agent_catalog_revision_invalid")
    model = NativeAgentCatalogModel(
        model_provider_id=profile.model_provider_id, model_id=profile.model_id,
        model_revision=revision, revision_policy=policy,
        reasoning_efforts=tuple(item.effort for item in option.supported_reasoning_efforts),
        default_reasoning_effort=option.default_reasoning_effort,
    )
    return replace(
        profile,
        model_revision=model.model_revision, model_revision_policy=model.revision_policy,
        reasoning_efforts=model.reasoning_efforts,
        default_reasoning_effort=model.default_reasoning_effort,
    )


__all__ = ["codex_model_profile_projection"]
