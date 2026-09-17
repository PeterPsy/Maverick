from datetime import UTC, datetime
import unittest

from core.providers.openrouter_agentic_profile import (
    OPENROUTER_AGENTIC_PROFILE_ID,
    OPENROUTER_DEFAULT_REASONING_EFFORT,
    OPENROUTER_REASONING_EFFORTS,
    openrouter_agentic_preview_publication,
)
from core.providers.maverick_agent_onboarding import publish_maverick_agent_profile
from tests.support.maverick_agent_onboarding import provider_store


NOW = datetime(2026, 9, 17, tzinfo=UTC)


class OpenRouterAgenticProfileTest(unittest.TestCase):
    def test_publication_is_one_direct_current_model_config(self) -> None:
        publication = openrouter_agentic_preview_publication(now=NOW)
        profile = publication.profile

        self.assertEqual(profile.definition_id, OPENROUTER_AGENTIC_PROFILE_ID)
        self.assertEqual(profile.model_provider_id, "openrouter")
        self.assertEqual(profile.model_id, "z-ai/glm-5.3-flash")
        self.assertEqual(profile.reasoning_efforts, OPENROUTER_REASONING_EFFORTS)
        self.assertEqual(profile.default_reasoning_effort, OPENROUTER_DEFAULT_REASONING_EFFORT)
        self.assertEqual(profile.adapter_version_constraint, "==59")
        self.assertEqual(profile.routing_constraint.allowed_upstream_ids, ("relace",))
        self.assertFalse(profile.routing_constraint.allow_fallbacks)
        self.assertTrue(profile.routing_constraint.require_zdr)

    def test_republishing_replaces_the_same_config_in_place(self) -> None:
        store = provider_store()
        publication = openrouter_agentic_preview_publication(now=NOW)

        publish_maverick_agent_profile(store, publication=publication, now=NOW)
        publish_maverick_agent_profile(store, publication=publication, now=NOW)

        self.assertEqual(store.list_agentic_profile_definitions(), [publication.profile])


if __name__ == "__main__":
    unittest.main()
