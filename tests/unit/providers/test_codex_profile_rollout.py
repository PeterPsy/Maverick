from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from core.providers.agentic_migration import _roll_forward_enabled_codex_bindings
from core.providers.agentic_models import (
    AgenticProfileDefinitionStatus,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.agentic_profiles import publish_codex_agentic_profile
from core.providers.service import builtin_provider_registry
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection
from tests.support.native_agent_catalog import codex_snapshot


NOW = datetime(2026, 8, 16, tzinfo=UTC)


class CodexProfileRolloutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider_store = ProviderDocumentStore(
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
        discovery = patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=codex_snapshot(
                "gpt-5.6-sol",
                "alternate-history-model",
                "alternate-authority-model",
                "orphan-binding-model",
            ),
        )
        discovery.start()
        self.addCleanup(discovery.stop)
        self.registry = builtin_provider_registry()
        self.codex = self.registry.get_provider_definition("codex")

    def _historical_profile(self, current_profile, *, revision: str):
        profile = replace(current_profile, revision=revision)
        self.provider_store.save_agentic_profile_definition(profile)
        self.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=profile.definition_id,
                definition_revision=profile.revision,
                rollout_status="suspended",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
        return profile

    def test_migration_rolls_enabled_nondefault_model_binding_to_current_revision(self) -> None:
        current_profile = publish_codex_agentic_profile(
            self.provider_store,
            definition=self.codex,
            model_id="alternate-history-model",
            now=NOW,
        )
        previous_profile = self._historical_profile(current_profile, revision="8")
        historical_binding = WorkspaceAgenticProfileBinding(
            binding_id="historical-alternate-binding",
            workspace_id="default",
            definition_id=previous_profile.definition_id,
            definition_revision=previous_profile.revision,
            credential_binding_id=None,
            enabled=True,
            is_default=False,
            actor_policy=default_actor_selection_policy(),
            workspace_policy_ceiling=previous_profile.policy_ceiling,
            egress_policy_id=previous_profile.egress_policy_id,
            egress_policy_revision=previous_profile.egress_policy_revision,
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        self.provider_store.save_workspace_agentic_profile_binding(
            historical_binding,
            expected_revision=None,
        )
        older_profile = self._historical_profile(current_profile, revision="7")
        self.provider_store.save_workspace_agentic_profile_binding(
            replace(
                historical_binding,
                binding_id="older-alternate-binding",
                definition_revision=older_profile.revision,
            ),
            expected_revision=None,
        )

        _roll_forward_enabled_codex_bindings(
            self.provider_store,
            self.registry,
            workspace_ids={"default"},
            now=NOW,
        )

        current_bindings = [
            binding
            for binding in self.provider_store.list_workspace_agentic_profile_bindings(
                "default"
            )
            if binding.definition_id == current_profile.definition_id
            and binding.definition_revision == current_profile.revision
        ]
        self.assertEqual(len(current_bindings), 1)
        self.assertTrue(current_bindings[0].enabled)
        self.assertFalse(current_bindings[0].is_default)
        self.assertEqual(
            current_bindings[0].workspace_policy_ceiling,
            historical_binding.workspace_policy_ceiling,
        )

    def test_migration_preserves_distinct_historical_authority_bindings(self) -> None:
        current_profile = publish_codex_agentic_profile(
            self.provider_store,
            definition=self.codex,
            model_id="alternate-authority-model",
            now=NOW,
        )
        previous_profile = self._historical_profile(current_profile, revision="8")
        policies = (
            previous_profile.policy_ceiling,
            replace(previous_profile.policy_ceiling, max_steps_per_turn=32),
        )
        for index, policy in enumerate(policies):
            self.provider_store.save_workspace_agentic_profile_binding(
                WorkspaceAgenticProfileBinding(
                    binding_id=f"historical-authority-{index}",
                    workspace_id="default",
                    definition_id=previous_profile.definition_id,
                    definition_revision=previous_profile.revision,
                    credential_binding_id=None,
                    enabled=True,
                    is_default=False,
                    actor_policy=default_actor_selection_policy(),
                    workspace_policy_ceiling=policy,
                    egress_policy_id=previous_profile.egress_policy_id,
                    egress_policy_revision=previous_profile.egress_policy_revision,
                    revision=0,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                expected_revision=None,
            )

        _roll_forward_enabled_codex_bindings(
            self.provider_store,
            self.registry,
            workspace_ids={"default"},
            now=NOW,
        )

        current_bindings = [
            binding
            for binding in self.provider_store.list_workspace_agentic_profile_bindings(
                "default"
            )
            if binding.definition_id == current_profile.definition_id
            and binding.definition_revision == current_profile.revision
        ]
        self.assertEqual(len(current_bindings), 2)
        self.assertEqual(
            {binding.workspace_policy_ceiling for binding in current_bindings},
            set(policies),
        )

    def test_migration_normalizes_legacy_parallel_zero_once(self) -> None:
        current_profile = publish_codex_agentic_profile(
            self.provider_store,
            definition=self.codex,
            model_id="alternate-history-model",
            now=NOW,
        )
        legacy_policy = replace(
            current_profile.policy_ceiling,
            max_parallel_tool_calls=0,  # type: ignore[arg-type]
        )
        previous_profile = self._historical_profile(
            replace(current_profile, policy_ceiling=legacy_policy),
            revision="17.legacy-parallel-zero",
        )
        self.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="legacy-parallel-zero-binding",
                workspace_id="default",
                definition_id=previous_profile.definition_id,
                definition_revision=previous_profile.revision,
                credential_binding_id=None,
                enabled=True,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=legacy_policy,
                egress_policy_id=previous_profile.egress_policy_id,
                egress_policy_revision=previous_profile.egress_policy_revision,
                revision=0,
                created_at=NOW,
                updated_at=NOW,
            ),
            expected_revision=None,
        )

        for _attempt in range(2):
            _roll_forward_enabled_codex_bindings(
                self.provider_store,
                self.registry,
                workspace_ids={"default"},
                now=NOW,
            )

        current_bindings = [
            binding
            for binding in self.provider_store.list_workspace_agentic_profile_bindings(
                "default"
            )
            if binding.definition_revision == current_profile.revision
        ]
        self.assertEqual(len(current_bindings), 1)
        self.assertEqual(
            current_bindings[0].workspace_policy_ceiling.max_parallel_tool_calls,
            "unbounded",
        )
        self.assertEqual(current_bindings[0].revision, 0)

    def test_migration_skips_an_enabled_binding_with_missing_definition(self) -> None:
        profile = publish_codex_agentic_profile(
            self.provider_store,
            definition=self.codex,
            model_id="orphan-binding-model",
            now=NOW,
        )
        self.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="orphan-historical-binding",
                workspace_id="default",
                definition_id="missing-profile-definition",
                definition_revision="8",
                credential_binding_id=None,
                enabled=True,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=profile.policy_ceiling,
                egress_policy_id=profile.egress_policy_id,
                egress_policy_revision=profile.egress_policy_revision,
                revision=0,
                created_at=NOW,
                updated_at=NOW,
            ),
            expected_revision=None,
        )

        _roll_forward_enabled_codex_bindings(
            self.provider_store,
            self.registry,
            workspace_ids={"default"},
            now=NOW,
        )

        bindings = self.provider_store.list_workspace_agentic_profile_bindings(
            "default"
        )
        self.assertEqual(
            [item.binding_id for item in bindings],
            ["orphan-historical-binding"],
        )


if __name__ == "__main__":
    unittest.main()
