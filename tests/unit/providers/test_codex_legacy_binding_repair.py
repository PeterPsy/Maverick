from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.providers.agentic_profiles import ensure_codex_workspace_profile
from core.providers.builtin_certification import ensure_codex_preview_certificate
from core.providers.execution_family_readiness import (
    inspect_agentic_family_readiness,
)
from core.providers.models import ProviderSelection
from core.providers.service import builtin_provider_registry
from core.providers.store import ProviderCollections, ProviderDocumentStore
from tests.support.collections import FakeCollection


NOW = datetime(2026, 9, 5, tzinfo=UTC)


class CodexLegacyBindingRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ProviderDocumentStore(
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
        self.registry = builtin_provider_registry()
        self.codex = self.registry.get_provider_definition("codex")
        self.selection = ProviderSelection(
            selection_id="legacy-default-codex",
            workspace_id="default",
            provider_id="codex",
            binding_id=None,
            selection_scope="workspace_default",
            selection_reason="fixture",
            created_at=NOW,
            updated_at=NOW,
            model_id="gpt-5.6-sol",
            model_reasoning_effort=None,
        )

    def test_default_binding_preserves_an_explicit_listing_restriction(self) -> None:
        _profile, original = ensure_codex_workspace_profile(
            self.store,
            definition=self.codex,
            selection=self.selection,
            now=NOW,
        )
        persisted = self.store.save_workspace_agentic_profile_binding(
            replace(
                original,
                workspace_policy_ceiling=replace(
                    original.workspace_policy_ceiling,
                    allow_filesystem_list=False,
                    max_steps_per_turn=32,
                ),
                revision=original.revision + 1,
            ),
            expected_revision=original.revision,
        )

        profile, repaired = ensure_codex_workspace_profile(
            self.store,
            definition=self.codex,
            selection=self.selection,
            now=NOW,
        )

        self.assertFalse(repaired.workspace_policy_ceiling.allow_filesystem_list)
        self.assertEqual(repaired.workspace_policy_ceiling.max_steps_per_turn, 32)
        self.assertEqual(repaired.revision, persisted.revision)
        certificate = ensure_codex_preview_certificate(
            self.store,
            definition=profile,
            provider_definition=self.codex,
            adapter=self.registry.get_agentic_runtime_adapter("codex"),
        )
        readiness = inspect_agentic_family_readiness(
            definition=profile,
            certificate=certificate,
            binding=repaired,
            registry=self.registry,
        )
        self.assertFalse(readiness.complete)
        self.assertEqual(
            certificate.certified_capabilities.attachment_modalities,
            ("file",),
        )

        explicitly_disabled = self.store.save_workspace_agentic_profile_binding(
            replace(
                repaired,
                workspace_policy_ceiling=replace(
                    repaired.workspace_policy_ceiling,
                    allow_filesystem_list=False,
                    tool_handle_mode="none",
                    allowed_tool_handles=(),
                ),
                revision=repaired.revision + 1,
            ),
            expected_revision=repaired.revision,
        )
        _profile, preserved = ensure_codex_workspace_profile(
            self.store,
            definition=self.codex,
            selection=self.selection,
            now=NOW,
        )

        self.assertEqual(
            preserved.workspace_policy_ceiling,
            explicitly_disabled.workspace_policy_ceiling,
        )

        surface_narrowed = self.store.save_workspace_agentic_profile_binding(
            replace(
                repaired,
                workspace_policy_ceiling=replace(
                    repaired.workspace_policy_ceiling,
                    allowed_surface_kinds=("cli",),
                    allow_filesystem_list=False,
                ),
                revision=preserved.revision + 1,
            ),
            expected_revision=preserved.revision,
        )
        _profile, preserved = ensure_codex_workspace_profile(
            self.store,
            definition=self.codex,
            selection=self.selection,
            now=NOW,
        )

        self.assertEqual(
            preserved.workspace_policy_ceiling,
            surface_narrowed.workspace_policy_ceiling,
        )


if __name__ == "__main__":
    unittest.main()
