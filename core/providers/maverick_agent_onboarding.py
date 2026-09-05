"""Data-driven onboarding boundary for Maverick-owned API agent loops."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Literal

from core.providers.agentic_models import (
    AgenticProfileDefinition,
    AgenticProfileDefinitionStatus,
    ProfileRolloutStatus,
)
from core.providers.errors import AgenticProfileError, ProviderNotFoundError
from core.providers.execution_families import MAVERICK_AGENT_EXECUTION_FAMILY
from core.providers.models import ProviderDefinition
from core.providers.maverick_agent_provider_config import (
    MaverickProviderConfig,
    MaverickTokenCostPolicy,
    validate_maverick_provider_config,
)
from core.providers.maverick_agent_runtime_contract import (
    validate_composed_maverick_runtime,
)
from core.providers.store import ProviderStore
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    FULL_WORKSPACE_CORE_TOOL_HANDLES,
    MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY,
)
from core.runtime.hosted_harness_recipes import HostedHarnessRecipeManifest
from core.runtime.hosted_provider_runtime import (
    HostedProviderRuntime,
    HostedProviderRuntimeRegistry,
)


RuntimeFactory = Callable[
    ["MaverickProviderConfig", HostedHarnessRecipeManifest],
    HostedProviderRuntime,
]


@dataclass(frozen=True)
class MaverickProtocolAdapterManifest:
    """Trusted provider-protocol implementation, independent of any model."""

    protocol_adapter_id: str
    protocol_adapter_version: str
    runtime_adapter_id: str
    runtime_adapter_version: str
    provider_protocol: str
    provider_api_version: str | None
    transport_id: str
    request_codec_id: str
    response_codec_id: str
    private_state_codec_id: str
    usage_accounting_id: str
    cancellation_id: str
    recovery_id: str
    trusted_distribution: str


@dataclass(frozen=True)
class MaverickAgentProfilePublication:
    """Exact model profile plus separately versioned adapter/config/recipe."""

    adapter: MaverickProtocolAdapterManifest
    provider_config: MaverickProviderConfig
    recipe: HostedHarnessRecipeManifest
    profile: AgenticProfileDefinition
    rollout_status: ProfileRolloutStatus
    superseded_profile_revisions: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaverickModelCandidate:
    """Discovery observation that deliberately carries no runtime authority."""

    candidate_id: str
    model_provider_id: str
    model_id: str
    model_revision: str | None
    provider_config_id: str
    compatible_recipe_ids: tuple[str, ...]
    observed_metadata_digest: str
    authority_granted: Literal[False] = False
    execution_family: None = None


@dataclass(frozen=True)
class MaverickProtocolRuntimeRegistration:
    """Trusted factory plugged into the provider-neutral hosted registry."""

    manifest: MaverickProtocolAdapterManifest
    runtime_factory: RuntimeFactory


class MaverickAgentOnboardingCatalog:
    """Register data records and compose runtimes without changing Core loop code."""

    def __init__(self) -> None:
        self._runtime_adapters: dict[
            tuple[str, str | None], MaverickProtocolRuntimeRegistration
        ] = {}
        self._provider_configs: dict[
            tuple[str, str], MaverickProviderConfig
        ] = {}
        self._publications: dict[
            tuple[str, str], MaverickAgentProfilePublication
        ] = {}

    def register_protocol_adapter(
        self,
        registration: MaverickProtocolRuntimeRegistration,
    ) -> None:
        manifest = registration.manifest
        _validate_protocol_adapter(manifest)
        if not callable(registration.runtime_factory):
            raise AgenticProfileError("maverick_protocol_factory_invalid")
        key = (manifest.provider_protocol, manifest.provider_api_version)
        if key in self._runtime_adapters:
            raise AgenticProfileError("maverick_protocol_adapter_duplicate")
        self._runtime_adapters[key] = registration

    def register_provider_config(self, config: MaverickProviderConfig) -> None:
        validate_maverick_provider_config(config)
        key = (config.config_id, config.revision)
        if key in self._provider_configs:
            raise AgenticProfileError("maverick_provider_config_duplicate")
        self._provider_configs[key] = config

    def register_profile(
        self,
        publication: MaverickAgentProfilePublication,
    ) -> None:
        _validate_publication(publication)
        config = self._provider_configs.get(
            (
                publication.provider_config.config_id,
                publication.provider_config.revision,
            )
        )
        if config != publication.provider_config:
            raise AgenticProfileError("maverick_provider_config_unregistered")
        adapter_key = (
            publication.adapter.provider_protocol,
            publication.adapter.provider_api_version,
        )
        registration = self._runtime_adapters.get(adapter_key)
        if registration is None or registration.manifest != publication.adapter:
            raise AgenticProfileError("maverick_protocol_adapter_unregistered")
        key = (publication.profile.definition_id, publication.profile.revision)
        if key in self._publications:
            raise AgenticProfileError("maverick_profile_publication_duplicate")
        self._publications[key] = publication

    def discover_candidates(
        self,
        definition: ProviderDefinition,
    ) -> tuple[MaverickModelCandidate, ...]:
        """Observe models without treating mutable vendor flags as authority."""
        configs = tuple(
            config
            for config in self._provider_configs.values()
            if config.model_provider_id == definition.provider_id
        )
        candidates: list[MaverickModelCandidate] = []
        for config in sorted(configs, key=lambda item: item.config_id):
            recipes = tuple(
                publication.recipe
                for publication in self._publications.values()
                if publication.provider_config == config
            )
            for option in definition.model_options:
                compatible = tuple(
                    sorted(
                        recipe.recipe_id
                        for recipe in recipes
                        if recipe.model_id == option.model_id
                    )
                )
                candidates.append(
                    MaverickModelCandidate(
                        candidate_id=(
                            f"maverick-candidate:{definition.provider_id}:"
                            f"{option.model_id}:{config.revision}"
                        ),
                        model_provider_id=definition.provider_id,
                        model_id=option.model_id,
                        model_revision=str(option.metadata.get("model_revision") or "") or None,
                        provider_config_id=config.config_id,
                        compatible_recipe_ids=compatible,
                        observed_metadata_digest=canonical_digest(
                            {
                                "model_id": option.model_id,
                                "metadata": option.metadata,
                                "input_modalities": option.input_modalities,
                                "output_modalities": option.output_modalities,
                                "upstream_provider_options": option.upstream_provider_options,
                            }
                        ),
                    )
                )
        return tuple(candidates)

    def build_runtime_registry(self) -> HostedProviderRuntimeRegistry:
        """Compose trusted protocol factories from registered data only."""
        registry = HostedProviderRuntimeRegistry()
        for key in sorted(self._publications):
            publication = self._publications[key]
            adapter_key = (
                publication.adapter.provider_protocol,
                publication.adapter.provider_api_version,
            )
            registration = self._runtime_adapters[adapter_key]
            runtime = registration.runtime_factory(
                publication.provider_config,
                publication.recipe,
            )
            runtime = replace(
                runtime,
                provider_config_id=publication.provider_config.config_id,
                provider_config_revision=publication.provider_config.revision,
                provider_config_digest=publication.provider_config.digest,
                protocol_adapter_id=publication.adapter.protocol_adapter_id,
                protocol_adapter_version=(
                    publication.adapter.protocol_adapter_version
                ),
                endpoint_id=publication.provider_config.routing_constraint.endpoint_id,
                endpoint_url=publication.provider_config.endpoint_url,
                allowed_upstream_ids=(
                    publication.provider_config.routing_constraint.allowed_upstream_ids
                ),
            )
            validate_composed_maverick_runtime(publication, runtime)
            registry.register(runtime)
        return registry

    def publications(self) -> tuple[MaverickAgentProfilePublication, ...]:
        """Return immutable publications in deterministic profile order."""
        return tuple(self._publications[key] for key in sorted(self._publications))

    def validate_runtime_adapter(self, adapter: object) -> None:
        """Validate the production engine against every registered protocol."""
        checked: set[tuple[str, str]] = set()
        for registration in self._runtime_adapters.values():
            manifest = registration.manifest
            identity = (
                manifest.runtime_adapter_id,
                manifest.runtime_adapter_version,
            )
            if identity in checked:
                continue
            validate_maverick_runtime_adapter(manifest, adapter)
            checked.add(identity)

    def publish_profiles(
        self,
        store: ProviderStore,
        *,
        now: datetime,
    ) -> tuple[AgenticProfileDefinition, ...]:
        """Publish every registered immutable profile through one bootstrap path."""
        self.build_runtime_registry()
        return tuple(
            publish_maverick_agent_profile(
                store,
                publication=publication,
                now=now,
            )
            for publication in self.publications()
        )


def publish_maverick_agent_profile(
    store: ProviderStore,
    *,
    publication: MaverickAgentProfilePublication,
    now: datetime,
) -> AgenticProfileDefinition:
    """Publish one exact immutable profile and an independent rollout record."""
    _validate_publication(publication)
    expected = publication.profile
    try:
        stored = store.get_agentic_profile_definition(
            expected.definition_id,
            expected.revision,
        )
    except ProviderNotFoundError:
        stored = store.save_agentic_profile_definition(expected)
    else:
        if stored != replace(expected, created_at=stored.created_at):
            raise AgenticProfileError("maverick_profile_immutable_conflict")
    status = store.get_agentic_profile_definition_status(
        stored.definition_id,
        stored.revision,
    )
    if status is None:
        store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=stored.definition_id,
                definition_revision=stored.revision,
                rollout_status=publication.rollout_status,
                revision=0,
                updated_at=now,
            ),
            expected_revision=None,
        )
    _suspend_superseded_profile_revisions(store, publication=publication, now=now)
    return stored


def _suspend_superseded_profile_revisions(
    store: ProviderStore,
    *,
    publication: MaverickAgentProfilePublication,
    now: datetime,
) -> None:
    for revision in publication.superseded_profile_revisions:
        status = store.get_agentic_profile_definition_status(
            publication.profile.definition_id,
            revision,
        )
        if status is None or status.rollout_status in {"disabled", "suspended"}:
            continue
        store.save_agentic_profile_definition_status(
            replace(
                status,
                rollout_status="suspended",
                revision=status.revision + 1,
                updated_at=now,
            ),
            expected_revision=status.revision,
        )


def validate_maverick_runtime_adapter(
    manifest: MaverickProtocolAdapterManifest,
    adapter: object,
) -> None:
    """Require the executable engine to match the trusted adapter manifest."""
    if (
        str(getattr(adapter, "runtime_engine_id", "")) != "maverick-tool-loop"
        or str(getattr(adapter, "adapter_id", ""))
        != manifest.runtime_adapter_id
        or str(getattr(adapter, "adapter_version", ""))
        != manifest.runtime_adapter_version
    ):
        raise AgenticProfileError("maverick_runtime_adapter_identity_mismatch")


def _validate_publication(publication: MaverickAgentProfilePublication) -> None:
    adapter = publication.adapter
    config = publication.provider_config
    recipe = publication.recipe
    profile = publication.profile
    _validate_protocol_adapter(adapter)
    validate_maverick_provider_config(config)
    if profile.revision in publication.superseded_profile_revisions:
        raise AgenticProfileError("maverick_profile_supersedes_itself")
    if len(set(publication.superseded_profile_revisions)) != len(
        publication.superseded_profile_revisions
    ):
        raise AgenticProfileError("maverick_profile_superseded_revision_duplicate")
    if (
        profile.runtime_engine_id != "maverick-tool-loop"
        or profile.adapter_id != adapter.runtime_adapter_id
        or profile.adapter_version_constraint
        != f"=={adapter.runtime_adapter_version}"
        or profile.model_provider_id != config.model_provider_id
        or profile.provider_protocol != adapter.provider_protocol
        or profile.provider_api_version != adapter.provider_api_version
        or config.provider_protocol != adapter.provider_protocol
        or config.provider_api_version != adapter.provider_api_version
        or recipe.provider_protocol != config.provider_protocol
        or recipe.provider_api_version != config.provider_api_version
        or profile.routing_constraint != config.routing_constraint
        or profile.model_provider_id != recipe.model_provider_id
        or profile.model_id != recipe.model_id
        or profile.model_revision != recipe.model_revision
        or profile.model_revision_policy != recipe.model_revision_policy
        or profile.harness_recipe_id != recipe.recipe_id
        or profile.harness_recipe_revision != recipe.revision
        or profile.harness_recipe_digest != recipe.recipe_digest
        or profile.provider_capability_catalog_digest
        != recipe.capability_catalog_digest
        or profile.semantic_projection_compiler_revision
        != recipe.semantic_projection_compiler_revision
        or profile.tool_contract_revision != recipe.tool_contract_revision
        or profile.context_policy != recipe.context_policy
        or recipe.endpoint_id != config.routing_constraint.endpoint_id
        or recipe.upstream_ids != config.routing_constraint.allowed_upstream_ids
        or profile.provider_config_id != config.config_id
        or profile.provider_config_revision != config.revision
        or profile.provider_config_digest != config.digest
        or profile.protocol_adapter_id != adapter.protocol_adapter_id
        or profile.protocol_adapter_version != adapter.protocol_adapter_version
    ):
        raise AgenticProfileError("maverick_profile_composition_mismatch")
    _validate_maverick_family(profile, recipe, publication.rollout_status)


def _validate_maverick_family(
    profile: AgenticProfileDefinition,
    recipe: HostedHarnessRecipeManifest,
    rollout_status: ProfileRolloutStatus,
) -> None:
    if profile.execution_family == MAVERICK_AGENT_CANDIDATE_EXECUTION_FAMILY:
        if profile.full_workspace_contract_revision or rollout_status != "disabled":
            raise AgenticProfileError("maverick_candidate_must_remain_disabled")
        return
    if profile.execution_family != MAVERICK_AGENT_EXECUTION_FAMILY:
        raise AgenticProfileError("maverick_execution_family_invalid")
    policy = profile.policy_ceiling
    flags = recipe.support_flags
    if (
        profile.full_workspace_contract_revision
        != FULL_WORKSPACE_CONTRACT_REVISION
        or recipe.tool_contract_revision != FULL_WORKSPACE_CONTRACT_REVISION
        or recipe.context_policy.compaction_mode != "provider_history"
        or not flags.streaming
        or not flags.usage_accounting
        or not flags.tool_calling
        or not flags.cooperative_cancellation
        or policy.tool_handle_mode != "exact"
        or not set(FULL_WORKSPACE_CORE_TOOL_HANDLES).issubset(
            policy.allowed_tool_handles
        )
        or not policy.allow_filesystem_list
        or not policy.allow_filesystem_read
        or not policy.allow_filesystem_write
        or not policy.allow_shell
    ):
        raise AgenticProfileError("maverick_full_workspace_contract_required")


def _validate_protocol_adapter(adapter: MaverickProtocolAdapterManifest) -> None:
    fields = (
        adapter.protocol_adapter_id,
        adapter.protocol_adapter_version,
        adapter.runtime_adapter_id,
        adapter.runtime_adapter_version,
        adapter.provider_protocol,
        adapter.transport_id,
        adapter.request_codec_id,
        adapter.response_codec_id,
        adapter.private_state_codec_id,
        adapter.usage_accounting_id,
        adapter.cancellation_id,
        adapter.recovery_id,
    )
    if not all(str(value or "").strip() for value in fields):
        raise AgenticProfileError("maverick_protocol_adapter_incomplete")
    if adapter.trusted_distribution not in {"maverick_builtin", "operator_trusted"}:
        raise AgenticProfileError("maverick_protocol_adapter_untrusted")


__all__ = [
    "MaverickAgentOnboardingCatalog",
    "MaverickAgentProfilePublication",
    "MaverickModelCandidate",
    "MaverickProtocolAdapterManifest",
    "MaverickProtocolRuntimeRegistration",
    "MaverickProviderConfig",
    "MaverickTokenCostPolicy",
    "publish_maverick_agent_profile",
    "validate_maverick_runtime_adapter",
]
