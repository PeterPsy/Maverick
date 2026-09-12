from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import unittest

from core.providers.agentic_models import AgenticProfileDefinitionStatus
from core.providers.errors import AgenticProfileError
from core.providers.google_agentic_profile import google_agentic_preview_publication
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    GOOGLE_INTERACTIONS_PROVIDER_CONFIG,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentOnboardingCatalog,
    MaverickProtocolRuntimeRegistration,
    publish_maverick_agent_profile,
)
from core.providers.models import ProviderModelOption
from core.providers.service import builtin_provider_registry
from core.runtime.hosted_runtime_registry_builder import (
    build_builtin_maverick_agent_onboarding_catalog,
)
from tests.support.maverick_agent_onboarding import (
    NOW,
    google_publication,
    provider_store,
)


class MaverickAgentOnboardingTest(unittest.TestCase):
    def test_catalog_upgrades_persisted_google_adapter_56_profile(self) -> None:
        store = provider_store()
        current = google_agentic_preview_publication(now=NOW).profile
        previous = replace(
            current,
            revision="67",
            adapter_version_constraint="==56",
            capability_certificate_id=(
                f"capability-certificate:{current.definition_id}:67"
            ),
        )
        store.save_agentic_profile_definition(previous)
        store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=previous.definition_id,
                definition_revision=previous.revision,
                rollout_status="preview",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )

        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)
        published = catalog.publish_profiles(store, now=NOW)
        later = NOW + timedelta(days=1)
        republished = build_builtin_maverick_agent_onboarding_catalog(
            now=later,
        ).publish_profiles(store, now=later)

        self.assertIn(current, published)
        self.assertEqual(published, republished)
        self.assertNotEqual(current.revision, previous.revision)
        self.assertEqual(
            store.get_agentic_profile_definition(
                previous.definition_id, previous.revision,
            ),
            previous,
        )
        status = store.get_agentic_profile_definition_status(
            previous.definition_id, previous.revision,
        )
        self.assertEqual(status.rollout_status, "suspended")
        self.assertEqual(status.revision, 1)

    def test_vendor_flags_only_create_non_authoritative_candidates(self) -> None:
        catalog = MaverickAgentOnboardingCatalog()
        catalog.register_protocol_adapter(
            MaverickProtocolRuntimeRegistration(
                manifest=GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
                runtime_factory=lambda _config, _recipe: None,  # type: ignore[arg-type]
            )
        )
        catalog.register_provider_config(GOOGLE_INTERACTIONS_PROVIDER_CONFIG)
        catalog.register_profile(google_publication())
        definition = builtin_provider_registry().get_provider_definition(
            "google-ai-studio"
        )
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
        vendor = next(
            item for item in candidates if item.model_id == "vendor-claims-tools"
        )

        self.assertFalse(vendor.authority_granted)
        self.assertIsNone(vendor.execution_family)
        self.assertEqual(vendor.compatible_recipe_ids, ())

    def test_publication_is_immutable_and_status_is_separate(self) -> None:
        store = provider_store()
        publication = google_publication()

        first = publish_maverick_agent_profile(
            store,
            publication=publication,
            now=NOW,
        )
        second = publish_maverick_agent_profile(
            store,
            publication=replace(
                publication,
                profile=replace(
                    publication.profile,
                    created_at=NOW + timedelta(days=1),
                ),
            ),
            now=NOW + timedelta(days=1),
        )

        self.assertEqual(first, second)
        status = store.get_agentic_profile_definition_status(
            first.definition_id,
            first.revision,
        )
        self.assertEqual(status.rollout_status, "preview")
        with self.assertRaisesRegex(AgenticProfileError, "immutable_conflict"):
            publish_maverick_agent_profile(
                store,
                publication=replace(
                    publication,
                    profile=replace(
                        publication.profile,
                        display_name="Changed in place",
                    ),
                ),
                now=NOW,
            )

    def test_full_workspace_is_required_before_agent_classification(self) -> None:
        publication = google_publication()
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

        with self.assertRaisesRegex(
            AgenticProfileError,
            "full_workspace_contract_required",
        ):
            publish_maverick_agent_profile(
                provider_store(),
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
