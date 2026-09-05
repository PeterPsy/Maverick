"""Content-addressed native model projections, independent of adapter revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.errors import AgenticProfileError, ProviderNotFoundError
from core.providers.models import ProviderDefinition
from core.providers.native_agent_catalog import NativeAgentCatalogModel
from core.runtime.execution_binding import canonical_digest

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
    # A bounded adoption of already-certified revision 14 keeps current Codex
    # sessions and bindings byte-for-byte unchanged. Changed metadata never
    # reuses that identity or mutates its certificate.
    try:
        legacy = store.get_agentic_profile_definition(profile.definition_id, profile.revision)
        certificate = store.get_capability_certificate(legacy.capability_certificate_id)
    except ProviderNotFoundError:
        pass
    else:
        if (
            not legacy.native_model_catalog_digest
            and certificate.model_revision == model.model_revision
            and certificate.model_revision_policy == model.revision_policy
            and certificate.certified_reasoning_efforts == model.reasoning_efforts
            and certificate.default_reasoning_effort == model.default_reasoning_effort
        ):
            return legacy
    revision = f"{profile.revision}.{canonical_digest((profile.revision, model.digest))}"
    return replace(
        profile, revision=revision,
        capability_certificate_id=f"capability-certificate:{profile.definition_id}:{revision}",
        model_revision=model.model_revision, model_revision_policy=model.revision_policy,
        native_model_catalog_digest=model.digest,
    )


__all__ = ["codex_model_profile_projection"]
