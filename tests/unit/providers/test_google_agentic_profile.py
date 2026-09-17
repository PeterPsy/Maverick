from datetime import UTC, datetime
import unittest

from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_DEFAULT_REASONING_EFFORT,
    GOOGLE_REASONING_EFFORTS,
    google_agentic_preview_publication,
)
from core.providers.maverick_agent_onboarding import publish_maverick_agent_profile
from tests.support.maverick_agent_onboarding import provider_store


NOW = datetime(2026, 9, 17, tzinfo=UTC)


class GoogleAgenticProfileTest(unittest.TestCase):
    def test_publication_is_one_direct_current_model_config(self) -> None:
        publication = google_agentic_preview_publication(now=NOW)
        profile = publication.profile

        self.assertEqual(profile.definition_id, GOOGLE_AGENTIC_PROFILE_ID)
        self.assertEqual(profile.model_provider_id, "google-ai-studio")
        self.assertEqual(profile.model_id, "gemini-3.6-flash")
        self.assertEqual(profile.reasoning_efforts, GOOGLE_REASONING_EFFORTS)
        self.assertEqual(profile.default_reasoning_effort, GOOGLE_DEFAULT_REASONING_EFFORT)
        self.assertEqual(profile.adapter_version_constraint, "==59")
        self.assertTrue(profile.capabilities.tool_orchestration)
        self.assertTrue(profile.policy_ceiling.allow_filesystem_write)

    def test_republishing_replaces_the_same_config_in_place(self) -> None:
        store = provider_store()
        publication = google_agentic_preview_publication(now=NOW)

        publish_maverick_agent_profile(store, publication=publication, now=NOW)
        publish_maverick_agent_profile(store, publication=publication, now=NOW)

        self.assertEqual(store.list_agentic_profile_definitions(), [publication.profile])


if __name__ == "__main__":
    unittest.main()
