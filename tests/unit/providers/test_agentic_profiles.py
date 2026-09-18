from dataclasses import asdict
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.providers.agentic_profiles import (
    _validated_reasoning_effort,
    ensure_codex_workspace_profile,
    publish_codex_agentic_profile,
)
from core.providers.errors import AgenticProfileError
from core.providers.models import ProviderSelection
from core.providers.provider_codex_models import build_codex_definition
from tests.support.maverick_agent_onboarding import provider_store


NOW = datetime(2026, 9, 17, tzinfo=UTC)


class AgenticProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = provider_store()
        self.codex = build_codex_definition()
        self.selection = ProviderSelection(
            selection_id="default:codex",
            workspace_id="default",
            provider_id="codex",
            binding_id=None,
            selection_scope="workspace_default",
            selection_reason="test",
            created_at=NOW,
            updated_at=NOW,
            model_id="gpt-5.6-sol",
            model_reasoning_effort="high",
        )

    def test_workspace_config_points_to_one_direct_model_definition(self) -> None:
        definition, config = ensure_codex_workspace_profile(
            self.store,
            definition=self.codex,
            selection=self.selection,
            now=NOW,
        )

        self.assertNotIn("revision", asdict(definition))
        self.assertNotIn("execution_family", asdict(definition))
        self.assertEqual(config.definition_id, definition.definition_id)
        self.assertTrue(config.enabled)
        self.assertTrue(config.is_default)

    def test_republishing_a_model_replaces_the_same_definition(self) -> None:
        first = publish_codex_agentic_profile(
            self.store, definition=self.codex, model_id="gpt-5.6-sol", now=NOW
        )
        second = publish_codex_agentic_profile(
            self.store, definition=self.codex, model_id="gpt-5.6-sol", now=NOW
        )

        self.assertEqual(first.definition_id, second.definition_id)
        self.assertEqual(self.store.list_agentic_profile_definitions(), [second])

    def test_adapter_version_change_updates_the_same_definition(self) -> None:
        first = publish_codex_agentic_profile(
            self.store, definition=self.codex, model_id="gpt-5.6-sol", now=NOW
        )
        with patch("core.providers.agentic_profiles.CODEX_ADAPTER_VERSION", "999"):
            updated = publish_codex_agentic_profile(
                self.store,
                definition=self.codex,
                model_id="gpt-5.6-sol",
                now=NOW,
            )

        self.assertEqual(updated.definition_id, first.definition_id)
        self.assertEqual(updated.adapter_version_constraint, "==999")
        self.assertEqual(self.store.list_agentic_profile_definitions(), [updated])

    def test_profile_hydration_ignores_and_republication_removes_retired_fields(self) -> None:
        current = publish_codex_agentic_profile(
            self.store, definition=self.codex, model_id="gpt-5.6-sol", now=NOW
        )
        collection = self.store.collections.agentic_profile_definitions
        document = collection.documents[0]
        document.update(
            revision="retired-revision",
            execution_family="retired-family",
            retired_metadata="ignored",
        )

        self.assertEqual(
            self.store.get_agentic_profile_definition(current.definition_id),
            current,
        )
        self.store.save_agentic_profile_definition(current)
        persisted = collection.documents[0]
        self.assertNotIn("revision", persisted)
        self.assertNotIn("execution_family", persisted)

    def test_reasoning_is_validated_directly_against_the_model(self) -> None:
        definition = publish_codex_agentic_profile(
            self.store, definition=self.codex, model_id="gpt-5.6-sol", now=NOW
        )
        self.assertEqual(_validated_reasoning_effort(definition, reasoning_effort="high"), "high")
        with self.assertRaisesRegex(AgenticProfileError, "profile_reasoning_effort_unsupported"):
            _validated_reasoning_effort(definition, reasoning_effort="impossible")


if __name__ == "__main__":
    unittest.main()
