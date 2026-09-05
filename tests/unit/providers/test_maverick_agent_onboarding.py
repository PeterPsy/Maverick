from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest

from core.providers.agentic_models import AgenticProfileDefinition
from core.providers.agentic_workspace_policy import (
    REMOTE_PREVIEW_EGRESS_POLICY_ID,
    REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
)
from core.providers.errors import AgenticProfileError
from core.providers.google_agentic_profile import google_agentic_preview_policy
from core.providers.google_interactions_client import GOOGLE_AGENTIC_MODEL_REVISION
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentOnboardingCatalog,
    MaverickAgentProfilePublication,
    MaverickProtocolRuntimeRegistration,
    publish_maverick_agent_profile,
)
from core.providers.models import ProviderModelOption
from core.providers.service import builtin_provider_registry
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.runtime.full_workspace_contract import (
    FULL_WORKSPACE_CONTRACT_REVISION,
    MAVERICK_AGENT_EXECUTION_FAMILY,
)
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE
from core.runtime.hosted_provider_runtime import HostedProviderRuntime
from core.runtime.hosted_runtime_registry_builder import (
    build_builtin_maverick_agent_onboarding_catalog,
    build_hosted_provider_runtime_registry,
)
from tests.support.collections import FakeCollection


NOW = datetime(2026, 9, 4, tzinfo=UTC)


def _provider_store() -> ProviderDocumentStore:
    return ProviderDocumentStore(
        ProviderCollections(
            definitions=FakeCollection(),
            bindings=FakeCollection(),
            selections=FakeCollection(),
            agentic_profile_definitions=FakeCollection(),
            agentic_profile_definition_statuses=FakeCollection(),
            workspace_agentic_profile_bindings=FakeCollection(),
            agentic_migrations=FakeCollection(),
        )
    )


def _publication(
    *,
    model_id: str = "gemini-3.6-flash",
    profile_revision: str = "test-1",
) -> MaverickAgentProfilePublication:
    recipe = replace(
        GOOGLE_GOVERNED_WORKSPACE_RECIPE,
        recipe_id=f"test-google-recipe-{model_id}",
        revision=profile_revision,
        model_id=model_id,
        model_revision=GOOGLE_AGENTIC_MODEL_REVISION,
    )
    profile = AgenticProfileDefinition(
        definition_id=f"test-profile-{model_id}",
        revision=profile_revision,
        display_name=f"Test {model_id}",
        runtime_engine_id="maverick-tool-loop",
        model_provider_id="google-ai-studio",
        model_id=model_id,
        model_revision=recipe.model_revision,
        model_revision_policy=recipe.model_revision_policy,
        provider_protocol=recipe.provider_protocol,
        provider_api_version=recipe.provider_api_version,
        adapter_id=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_id,
        adapter_version_constraint=(
            f"=={GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER.runtime_adapter_version}"
        ),
        routing_constraint=GOOGLE_INTERACTIONS_PROVIDER_CONFIG.routing_constraint,
        policy_ceiling=google_agentic_preview_policy(),
        capability_certificate_id=f"certificate:{model_id}:{profile_revision}",
        created_at=NOW,
        egress_policy_id=REMOTE_PREVIEW_EGRESS_POLICY_ID,
        egress_policy_revision=REMOTE_PREVIEW_EGRESS_POLICY_REVISION,
        full_workspace_contract_revision=FULL_WORKSPACE_CONTRACT_REVISION,
        execution_family=MAVERICK_AGENT_EXECUTION_FAMILY,
        harness_recipe_id=recipe.recipe_id,
        harness_recipe_revision=recipe.revision,
        harness_recipe_digest=recipe.recipe_digest,
        provider_capability_catalog_digest=recipe.capability_catalog_digest,
        semantic_projection_compiler_revision=(
            recipe.semantic_projection_compiler_revision
        ),
        tool_contract_revision=recipe.tool_contract_revision,
        context_policy=recipe.context_policy,
    )
    return MaverickAgentProfilePublication(
        adapter=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
        provider_config=GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
        recipe=recipe,
        profile=profile,
        rollout_status="preview",
    )


class MaverickAgentOnboardingTest(unittest.TestCase):
    def test_production_registry_is_composed_by_the_onboarding_catalog(self) -> None:
        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)
        publications = catalog.publications()

        registry = build_hosted_provider_runtime_registry(
            onboarding_catalog=catalog,
        )

        self.assertEqual(len(publications), 2)
        self.assertEqual(
            {publication.profile.model_id for publication in publications},
            {"gemini-3.6-flash", "deepseek/deepseek-v4-flash"},
        )
        for publication in publications:
            with self.subTest(profile=publication.profile.definition_id):
                runtime = registry._recipes[
                    (publication.recipe.recipe_id, publication.recipe.revision)
                ]
                self.assertEqual(runtime.recipe, publication.recipe)

    def test_catalog_publishes_all_registered_profiles_through_one_path(self) -> None:
        store = _provider_store()
        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)

        published = catalog.publish_profiles(store, now=NOW)

        self.assertEqual(
            {(item.definition_id, item.revision) for item in published},
            {
                (publication.profile.definition_id, publication.profile.revision)
                for publication in catalog.publications()
            },
        )

    def test_same_adapter_accepts_another_model_as_data_only(self) -> None:
        built: list[str] = []

        def runtime_factory(config, recipe):
            built.append(recipe.model_id)
            return HostedProviderRuntime(
                model_provider_id=config.model_provider_id,
                provider_protocol=config.provider_protocol,
                provider_api_version=config.provider_api_version,
                client=object(),
                private_codec=object(),
                cost_estimator=lambda *_args: 0,
                finalization_policy=object(),
                recipe=recipe,
            )

        catalog = MaverickAgentOnboardingCatalog()
        catalog.register_protocol_adapter(
            MaverickProtocolRuntimeRegistration(
                manifest=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
                runtime_factory=runtime_factory,
            )
        )
        catalog.register_provider_config(GOOGLE_INTERACTIONS_PROVIDER_CONFIG)
        catalog.register_profile(_publication())
        catalog.register_profile(_publication(model_id="gemini-new", profile_revision="test-2"))

        catalog.build_runtime_registry()

        self.assertEqual(built, ["gemini-3.6-flash", "gemini-new"])

    def test_new_trusted_protocol_adapter_plugs_in_without_core_loop_branch(self) -> None:
        base = _publication()
        manifest = replace(
            base.adapter,
            protocol_adapter_id="trusted-jsonl-protocol",
            protocol_adapter_version="1",
            provider_protocol="trusted-jsonl",
            provider_api_version="v2",
        )
        config = replace(
            base.provider_config,
            config_id="trusted-provider-v2",
            model_provider_id="trusted-provider",
            provider_protocol="trusted-jsonl",
            provider_api_version="v2",
            routing_constraint=replace(
                base.provider_config.routing_constraint,
                endpoint_id="trusted-provider-v2",
            ),
        )
        recipe = replace(
            base.recipe,
            recipe_id="trusted-provider-recipe",
            model_provider_id="trusted-provider",
            provider_protocol="trusted-jsonl",
            provider_api_version="v2",
            endpoint_id="trusted-provider-v2",
        )
        profile = replace(
            base.profile,
            definition_id="trusted-provider-profile",
            model_provider_id="trusted-provider",
            provider_protocol="trusted-jsonl",
            provider_api_version="v2",
            routing_constraint=config.routing_constraint,
            harness_recipe_id=recipe.recipe_id,
            harness_recipe_revision=recipe.revision,
            harness_recipe_digest=recipe.recipe_digest,
            provider_capability_catalog_digest=recipe.capability_catalog_digest,
        )
        publication = MaverickAgentProfilePublication(
            adapter=manifest,
            provider_config=config,
            recipe=recipe,
            profile=profile,
            rollout_status="preview",
        )
        built: list[str] = []
        catalog = MaverickAgentOnboardingCatalog()
        catalog.register_protocol_adapter(
            MaverickProtocolRuntimeRegistration(
                manifest=manifest,
                runtime_factory=lambda provider, harness: (
                    built.append(manifest.protocol_adapter_id)
                    or HostedProviderRuntime(
                        model_provider_id=provider.model_provider_id,
                        provider_protocol=provider.provider_protocol,
                        provider_api_version=provider.provider_api_version,
                        client=object(),
                        private_codec=object(),
                        cost_estimator=lambda *_args: 0,
                        finalization_policy=object(),
                        recipe=harness,
                    )
                ),
            )
        )
        catalog.register_provider_config(config)
        catalog.register_profile(publication)

        catalog.build_runtime_registry()

        self.assertEqual(built, ["trusted-jsonl-protocol"])

    def test_vendor_flags_only_create_non_authoritative_candidates(self) -> None:
        catalog = MaverickAgentOnboardingCatalog()
        catalog.register_protocol_adapter(
            MaverickProtocolRuntimeRegistration(
                manifest=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
                runtime_factory=lambda _config, _recipe: None,  # type: ignore[arg-type]
            )
        )
        catalog.register_provider_config(GOOGLE_INTERACTIONS_PROVIDER_CONFIG)
        catalog.register_profile(_publication())
        definition = builtin_provider_registry().get_provider_definition("google-ai-studio")
        definition = replace(
            definition,
            model_options=[
                *definition.model_options,
                ProviderModelOption(
                    model_id="vendor-claims-tools",
                    label="Vendor claims tools",
                    description=None,
                    default_reasoning_effort=None,
                    metadata={"supports_tools": True, "agentic": True},
                ),
            ],
        )

        candidates = catalog.discover_candidates(definition)
        vendor = next(item for item in candidates if item.model_id == "vendor-claims-tools")

        self.assertFalse(vendor.authority_granted)
        self.assertIsNone(vendor.execution_family)
        self.assertEqual(vendor.compatible_recipe_ids, ())

    def test_publication_is_immutable_and_status_is_separate(self) -> None:
        store = _provider_store()
        publication = _publication()

        first = publish_maverick_agent_profile(store, publication=publication, now=NOW)
        second = publish_maverick_agent_profile(
            store,
            publication=replace(
                publication,
                profile=replace(publication.profile, created_at=NOW + timedelta(days=1)),
            ),
            now=NOW + timedelta(days=1),
        )

        self.assertEqual(first, second)
        status = store.get_agentic_profile_definition_status(first.definition_id, first.revision)
        self.assertEqual(status.rollout_status, "preview")
        with self.assertRaisesRegex(AgenticProfileError, "immutable_conflict"):
            publish_maverick_agent_profile(
                store,
                publication=replace(
                    publication,
                    profile=replace(publication.profile, display_name="Changed in place"),
                ),
                now=NOW,
            )

    def test_full_workspace_is_required_before_agent_classification(self) -> None:
        publication = _publication()
        partial = replace(
            publication,
            profile=replace(
                publication.profile,
                policy_ceiling=replace(
                    publication.profile.policy_ceiling,
                    allow_shell=False,
                ),
            ),
        )

        with self.assertRaisesRegex(AgenticProfileError, "full_workspace_contract_required"):
            publish_maverick_agent_profile(
                _provider_store(),
                publication=partial,
                now=NOW,
            )

    def test_untrusted_protocol_adapter_cannot_be_registered(self) -> None:
        catalog = MaverickAgentOnboardingCatalog()
        untrusted = replace(
            GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
            trusted_distribution="vendor_metadata",
        )

        with self.assertRaisesRegex(AgenticProfileError, "adapter_untrusted"):
            catalog.register_protocol_adapter(
                MaverickProtocolRuntimeRegistration(
                    manifest=untrusted,
                    runtime_factory=lambda _config, _recipe: None,  # type: ignore[arg-type]
                )
            )


if __name__ == "__main__":
    unittest.main()
