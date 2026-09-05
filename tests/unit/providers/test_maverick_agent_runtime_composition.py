"""Executable config, transport, and accounting checks for Maverick Agents."""

from __future__ import annotations

from dataclasses import replace
import unittest

from core.providers.errors import AgenticProfileError
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentOnboardingCatalog,
    MaverickAgentProfilePublication,
    MaverickProtocolRuntimeRegistration,
    MaverickTokenCostPolicy,
    publish_maverick_agent_profile,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_preview_publication,
)
from core.runtime.hosted_provider_runtime import HostedProviderRuntime
from core.runtime.hosted_agentic_models import HostedProviderPrivateCodec
from core.runtime.hosted_finalization_policy import provider_finalization_policy
from core.runtime.hosted_runtime_registry_builder import (
    build_builtin_maverick_agent_onboarding_catalog,
    build_hosted_provider_runtime_registry,
)
from tests.support.maverick_agent_onboarding import (
    NOW,
    RuntimeClient,
    google_publication,
    provider_store,
)


def _runtime(config, recipe, *, client=None, cost_estimator=None, manifest=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER):
    return HostedProviderRuntime(
        model_provider_id=config.model_provider_id,
        provider_protocol=config.provider_protocol,
        provider_api_version=config.provider_api_version,
        client=client or RuntimeClient(config, recipe),
        private_codec=HostedProviderPrivateCodec(
            codec_id=manifest.private_state_codec_id.split("@")[0],
            codec_version=manifest.private_state_codec_id.split("@")[1],
            schema_version="1",
            content_type="application/json",
        ),
        cost_estimator=(
            cost_estimator
            or config.token_cost_policy.request_ceiling_microusd
        ),
        finalization_policy=provider_finalization_policy(config, recipe),
        private_state_inspector=lambda content: None,
        context_compactor=lambda state, policy, summary: None,
        request_preflight=lambda request, credential: None,
        implementation_manifest=manifest,
        recipe=recipe,
    )


def _register(publication, factory) -> MaverickAgentOnboardingCatalog:
    catalog = MaverickAgentOnboardingCatalog()
    catalog.register_protocol_adapter(
        MaverickProtocolRuntimeRegistration(
            manifest=publication.adapter,
            runtime_factory=factory,
        )
    )
    catalog.register_provider_config(publication.provider_config)
    catalog.register_profile(publication)
    return catalog


class MaverickAgentRuntimeCompositionTest(unittest.TestCase):
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
                self.assertEqual(
                    runtime.provider_config_digest,
                    publication.provider_config.digest,
                )
                self.assertEqual(
                    runtime.protocol_adapter_id,
                    publication.adapter.protocol_adapter_id,
                )
                self.assertEqual(
                    runtime.client.endpoint_url,
                    publication.provider_config.endpoint_url,
                )
                self.assertIs(
                    runtime.client.token_cost_policy,
                    publication.provider_config.token_cost_policy,
                )
                self.assertIs(
                    runtime.cost_estimator.__self__,
                    publication.provider_config.token_cost_policy,
                )

    def test_catalog_publishes_registered_profiles_through_one_path(self) -> None:
        store = provider_store()
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
            return _runtime(config, recipe)

        catalog = MaverickAgentOnboardingCatalog()
        catalog.register_protocol_adapter(
            MaverickProtocolRuntimeRegistration(
                manifest=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
                runtime_factory=runtime_factory,
            )
        )
        catalog.register_provider_config(GOOGLE_INTERACTIONS_PROVIDER_CONFIG)
        catalog.register_profile(google_publication())
        catalog.register_profile(
            google_publication(
                model_id="gemini-new",
                profile_revision="test-2",
            )
        )

        catalog.build_runtime_registry()

        self.assertEqual(built, ["gemini-3.6-flash", "gemini-new"])

    def test_new_trusted_protocol_adapter_plugs_in_without_core_loop_branch(self) -> None:
        base = google_publication()
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
            endpoint_url="https://trusted-provider.example/v2/agent",
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
            provider_config_id=config.config_id,
            provider_config_revision=config.revision,
            provider_config_digest=config.digest,
            protocol_adapter_id=manifest.protocol_adapter_id,
            protocol_adapter_version=manifest.protocol_adapter_version,
        )
        publication = MaverickAgentProfilePublication(
            adapter=manifest,
            provider_config=config,
            recipe=recipe,
            profile=profile,
            rollout_status="preview",
        )
        built: list[str] = []

        catalog = _register(
            publication,
            lambda provider, harness: (
                built.append(manifest.protocol_adapter_id)
                or _runtime(provider, harness, manifest=manifest)
            ),
        )
        catalog.build_runtime_registry()

        self.assertEqual(built, ["trusted-jsonl-protocol"])

    def test_publication_rejects_protocol_api_or_upstream_drift(self) -> None:
        publication = google_publication()
        variants = (
            replace(
                publication,
                provider_config=replace(
                    publication.provider_config,
                    provider_api_version="v2",
                ),
            ),
            replace(
                publication,
                recipe=replace(
                    publication.recipe,
                    upstream_ids=("unexpected-upstream",),
                ),
            ),
        )

        for changed in variants:
            with self.subTest(changed=changed), self.assertRaisesRegex(
                AgenticProfileError,
                "composition_mismatch",
            ):
                publish_maverick_agent_profile(
                    provider_store(),
                    publication=changed,
                    now=NOW,
                )

    def test_provider_config_requires_endpoint_routing_and_pricing_data(self) -> None:
        variants = (
            replace(
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
                config_id="declared-private-endpoint",
                endpoint_url="declared-private-endpoint",
            ),
            replace(
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
                upstream_provider_names=("unexpected",),
            ),
            replace(
                GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
                token_cost_policy=replace(
                    GOOGLE_INTERACTIONS_PROVIDER_CONFIG.token_cost_policy,
                    input_microusd_per_million_tokens=-1,
                ),
            ),
        )

        for config in variants:
            with self.subTest(config=config), self.assertRaises(AgenticProfileError):
                MaverickAgentOnboardingCatalog().register_provider_config(config)

    def test_catalog_rejects_factory_transport_endpoint_drift(self) -> None:
        publication = google_publication()

        def drifted_factory(config, recipe):
            client = RuntimeClient(config, recipe)
            client.endpoint_url = "https://different.example/v1/agent"
            return _runtime(config, recipe, client=client)

        catalog = _register(publication, drifted_factory)

        with self.assertRaisesRegex(
            AgenticProfileError,
            "transport_identity_mismatch",
        ):
            catalog.build_runtime_registry()

    def test_catalog_rejects_factory_accounting_policy_drift(self) -> None:
        publication = google_publication()
        different_policy = replace(
            publication.provider_config.token_cost_policy,
            policy_id="hardcoded-wrong-model-price",
        )
        catalog = _register(
            publication,
            lambda config, recipe: _runtime(
                config,
                recipe,
                cost_estimator=different_policy.request_ceiling_microusd,
            ),
        )

        with self.assertRaisesRegex(
            AgenticProfileError,
            "accounting_identity_mismatch",
        ):
            catalog.build_runtime_registry()

    def test_google_factory_rejects_declared_but_unimplemented_upstream(self) -> None:
        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)
        base = google_publication(
            model_id="gemini-unexecutable-route",
            profile_revision="route-2",
        )
        routing = replace(
            base.provider_config.routing_constraint,
            allowed_upstream_ids=("unexpected-upstream",),
        )
        config = replace(
            base.provider_config,
            config_id="google-unexecutable-route",
            routing_constraint=routing,
            upstream_provider_names=("Unexpected Upstream",),
        )
        recipe = replace(
            base.recipe,
            upstream_ids=routing.allowed_upstream_ids,
        )
        publication = replace(
            base,
            provider_config=config,
            recipe=recipe,
            profile=replace(
                base.profile,
                routing_constraint=routing,
                harness_recipe_digest=recipe.recipe_digest,
                provider_capability_catalog_digest=recipe.capability_catalog_digest,
                provider_config_id=config.config_id,
                provider_config_revision=config.revision,
                provider_config_digest=config.digest,
            ),
        )
        catalog.register_provider_config(config)
        catalog.register_profile(publication)

        with self.assertRaisesRegex(ValueError, "routing config is unsupported"):
            catalog.build_runtime_registry()

    def test_google_production_factory_binds_second_model_pricing_data(self) -> None:
        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)
        base = google_publication(
            model_id="gemini-data-only",
            profile_revision="data-2",
        )
        pricing = MaverickTokenCostPolicy(
            policy_id="fixture-google-model-price",
            revision="7",
            input_microusd_per_million_tokens=2_000_000,
            output_microusd_per_million_tokens=4_000_000,
        )
        config = replace(
            base.provider_config,
            config_id="google-data-only-model",
            revision="7",
            token_cost_policy=pricing,
        )
        publication = replace(
            base,
            provider_config=config,
            profile=replace(
                base.profile,
                provider_config_id=config.config_id,
                provider_config_revision=config.revision,
                provider_config_digest=config.digest,
            ),
        )
        catalog.register_provider_config(config)
        catalog.register_profile(publication)

        registry = catalog.build_runtime_registry()
        runtime = registry._recipes[
            (publication.recipe.recipe_id, publication.recipe.revision)
        ]

        self.assertEqual(runtime.client.model_id, "gemini-data-only")
        self.assertEqual(runtime.client.endpoint_url, config.endpoint_url)
        self.assertIs(runtime.client.token_cost_policy, pricing)
        self.assertIs(runtime.cost_estimator.__self__, pricing)
        self.assertEqual(runtime.client._usage_cost(100, 200), 1_000)

    def test_openrouter_production_factory_binds_second_model_route_and_price(self) -> None:
        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)
        base = openrouter_agentic_preview_publication(now=NOW)
        routing = replace(
            base.provider_config.routing_constraint,
            allowed_upstream_ids=("other-provider/fp16",),
            allowed_quantizations=("fp16",),
        )
        pricing = MaverickTokenCostPolicy(
            policy_id="fixture-openrouter-model-price",
            revision="9",
            input_microusd_per_million_tokens=3_000_000,
            output_microusd_per_million_tokens=5_000_000,
        )
        config = replace(
            base.provider_config,
            config_id="openrouter-other-provider-fp16",
            revision="9",
            routing_constraint=routing,
            token_cost_policy=pricing,
            upstream_provider_names=("Other Provider",),
            resolved_model_ids=("other/model-resolved",),
        )
        recipe = replace(
            base.recipe,
            recipe_id="openrouter-data-only-model-recipe",
            revision="data-2",
            model_id="vendor/data-only-model",
            model_revision="provider-alias-data-only",
            upstream_ids=routing.allowed_upstream_ids,
        )
        profile = replace(
            base.profile,
            definition_id="agentic-profile-openrouter-data-only-model",
            policy_ceiling=replace(base.profile.policy_ceiling, max_estimated_cost_microusd=3_000_000),
            revision="data-2",
            model_id=recipe.model_id,
            model_revision=recipe.model_revision,
            routing_constraint=routing,
            harness_recipe_id=recipe.recipe_id,
            harness_recipe_revision=recipe.revision,
            harness_recipe_digest=recipe.recipe_digest,
            provider_capability_catalog_digest=recipe.capability_catalog_digest,
            provider_config_id=config.config_id,
            provider_config_revision=config.revision,
            provider_config_digest=config.digest,
        )
        publication = replace(
            base,
            provider_config=config,
            recipe=recipe,
            profile=profile,
            superseded_profile_revisions=(),
        )
        catalog.register_provider_config(config)
        catalog.register_profile(publication)

        registry = catalog.build_runtime_registry()
        runtime = registry._recipes[(recipe.recipe_id, recipe.revision)]

        self.assertEqual(runtime.client.model_id, recipe.model_id)
        self.assertEqual(runtime.client.routing_constraint, routing)
        self.assertEqual(
            runtime.client.allowed_upstream_ids,
            ("other-provider/fp16",),
        )
        self.assertEqual(runtime.client.upstream_provider_names, ("Other Provider",))
        self.assertEqual(runtime.client.resolved_model_ids, ("other/model-resolved",))
        self.assertIs(runtime.client.token_cost_policy, pricing)
        self.assertIs(runtime.cost_estimator.__self__, pricing)
        self.assertEqual(runtime.client._usage_cost(100, 200), 1_300)


if __name__ == "__main__":
    unittest.main()
