"""Data-driven onboarding boundary for Maverick-owned API agent loops."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.errors import AgenticProfileError
from core.providers.maverick_agent_provider_config import (
    MaverickProviderConfig,
    MaverickTokenCostPolicy,
    validate_maverick_provider_config,
)
from core.providers.maverick_agent_runtime_contract import (
    validate_composed_maverick_runtime,
)
from core.providers.store import ProviderStore
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
    """Direct model config plus its executable implementation components."""

    adapter: MaverickProtocolAdapterManifest
    provider_config: MaverickProviderConfig
    recipe: HostedHarnessRecipeManifest
    profile: AgenticProfileDefinition


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
            str, MaverickAgentProfilePublication
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
        key = publication.profile.definition_id
        if key in self._publications:
            raise AgenticProfileError("maverick_profile_publication_duplicate")
        self._publications[key] = publication

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
        """Publish every registered current model config."""
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
    """Upsert one current direct model configuration."""
    _validate_publication(publication)
    expected = publication.profile
    return store.save_agentic_profile_definition(expected)


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
    from core.runtime.hosted_finalization_policy import provider_finalization_policy, validate_finalization_resources

    validate_finalization_resources(profile.policy_ceiling, provider_finalization_policy(config, recipe))
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
        or profile.context_policy != recipe.context_policy
        or recipe.endpoint_id != config.routing_constraint.endpoint_id
        or recipe.upstream_ids != config.routing_constraint.allowed_upstream_ids
    ):
        raise AgenticProfileError("maverick_profile_composition_mismatch")
    flags = recipe.support_flags
    if (
        profile.reasoning_efforts != flags.reasoning_efforts
        or profile.default_reasoning_effort not in profile.reasoning_efforts
        or profile.capabilities.streaming != flags.streaming
        or profile.capabilities.tool_orchestration != flags.tool_calling
        or profile.capabilities.interrupt != flags.cooperative_cancellation
        or profile.capabilities.attachment_modalities != flags.attachment_modalities
    ):
        raise AgenticProfileError("maverick_profile_composition_mismatch")


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
    "MaverickProtocolAdapterManifest",
    "MaverickProtocolRuntimeRegistration",
    "MaverickProviderConfig",
    "MaverickTokenCostPolicy",
    "publish_maverick_agent_profile",
    "validate_maverick_runtime_adapter",
]
