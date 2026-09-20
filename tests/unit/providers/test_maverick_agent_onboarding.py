from dataclasses import replace
from datetime import timedelta
import unittest

from core.providers.agentic_models import (
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.errors import AgenticProfileError, ProviderNotFoundError
from core.providers.google_agentic_profile import google_agentic_preview_publication
from core.providers.maverick_agent_builtins import (
    GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
    retire_builtin_maverick_agent_profiles,
)
from core.providers.maverick_agent_onboarding import (
    MaverickAgentOnboardingCatalog,
    MaverickProtocolRuntimeRegistration,
    publish_maverick_agent_profile,
)
from core.runtime.hosted_runtime_registry_builder import build_builtin_maverick_agent_onboarding_catalog
from tests.support.maverick_agent_onboarding import NOW, google_publication, provider_store


class MaverickAgentOnboardingTest(unittest.TestCase):
    def test_builtin_catalog_has_one_current_publication_per_model(self) -> None:
        catalog = build_builtin_maverick_agent_onboarding_catalog(now=NOW)
        publications = catalog.publications()

        identities = [item.profile.definition_id for item in publications]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertNotIn("agentic-profile-google-gemini-3-6-flash", identities)
        self.assertIn("agentic-profile-openrouter-glm-5-3-flash-relace", identities)
        self.assertIn("agentic-profile-openrouter-deepseek-flash-latest", identities)

    def test_retirement_removes_google_agentic_definition_and_workspace_bindings(self) -> None:
        store = provider_store()
        profile = google_agentic_preview_publication(now=NOW).profile
        store.save_agentic_profile_definition(profile)
        store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="workspace-google-agentic",
                workspace_id="default",
                definition_id=profile.definition_id,
                credential_binding_id=None,
                enabled=False,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=profile.policy_ceiling,
                egress_policy_id=profile.egress_policy_id,
                egress_policy_revision=profile.egress_policy_revision,
                created_at=NOW,
                updated_at=NOW,
            )
        )

        retire_builtin_maverick_agent_profiles(store)

        with self.assertRaises(ProviderNotFoundError):
            store.get_agentic_profile_definition(profile.definition_id)
        self.assertEqual(store.list_workspace_agentic_profile_bindings("default"), [])

    def test_publication_replaces_the_same_direct_config_in_place(self) -> None:
        store = provider_store()
        publication = google_publication()
        first = publish_maverick_agent_profile(store, publication=publication, now=NOW)
        changed = replace(
            publication,
            profile=replace(
                publication.profile,
                display_name="Updated display label",
                created_at=NOW + timedelta(days=1),
            ),
        )
        second = publish_maverick_agent_profile(
            store, publication=changed, now=NOW + timedelta(days=1)
        )

        self.assertEqual(first.definition_id, second.definition_id)
        self.assertEqual(second.display_name, "Updated display label")
        self.assertEqual(store.list_agentic_profile_definitions(), [second])

    def test_untrusted_protocol_adapter_cannot_be_registered(self) -> None:
        catalog = MaverickAgentOnboardingCatalog()
        untrusted = replace(
            GOOGLE_INTERACTIONS_PROTOCOL_ADAPTER,
            trusted_distribution="vendor_metadata",
        )

        with self.assertRaisesRegex(
            AgenticProfileError, "maverick_protocol_adapter_untrusted"
        ):
            catalog.register_protocol_adapter(
                MaverickProtocolRuntimeRegistration(
                    manifest=untrusted,
                    runtime_factory=lambda _config, _recipe: None,  # type: ignore[arg-type]
                )
            )


if __name__ == "__main__":
    unittest.main()
