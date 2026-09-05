from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import importlib
import inspect
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

from core.providers.agentic_migration import _roll_forward_enabled_codex_bindings
from core.providers.agentic_models import (
    AgenticProfileDefinitionStatus,
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.agentic_profiles import (
    CODEX_PROFILE_ARTIFACT_DIGEST,
    CODEX_PROFILE_ARTIFACT_DIGESTS,
    CODEX_PROFILE_REVISION,
    publish_codex_agentic_profile,
)
from core.providers.builtin_certification import ensure_codex_preview_certificate
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.codex_profile_revision_guard import (
    compare_codex_profile_artifact_manifests,
    verify_codex_profile_artifact_history,
)
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
        discovery = patch("core.providers.native_agent_reconciliation.discover_codex_native_catalog",
                          return_value=codex_snapshot("gpt-5.6-sol", "alternate-history-model", "alternate-authority-model", "orphan-binding-model"))
        discovery.start()
        self.addCleanup(discovery.stop)
        self.registry = builtin_provider_registry()
        self.codex = self.registry.get_provider_definition("codex")

    def test_current_codex_profile_revision_pins_the_complete_adapter_digest(self) -> None:
        importlib.import_module("core.providers.codex_app_server_runtime")
        adapter = self.registry.get_agentic_runtime_adapter("codex")

        self.assertEqual(
            runtime_adapter_artifact_digest(adapter),
            CODEX_PROFILE_ARTIFACT_DIGEST,
        )

    def test_codex_artifact_bundle_covers_every_operational_module(self) -> None:
        adapter = self.registry.get_agentic_runtime_adapter("codex")
        concrete = adapter.legacy_adapter
        components = (concrete, *concrete.artifact_components)
        covered_paths: set[Path] = set()
        for component in components:
            if isinstance(component, ModuleType):
                source_components = (component,)
            else:
                component_type = component if inspect.isclass(component) else type(component)
                source_components = component_type.__mro__
            for source_component in source_components:
                try:
                    source = inspect.getsourcefile(source_component)
                except TypeError:
                    source = None
                if source is not None:
                    covered_paths.add(Path(source).resolve())
        expected = {
            Path(path).resolve()
            for path in (
                "core/runtime/workspace_sandbox.py",
                "core/providers/provider_codex_hooks.py",
                "core/providers/provider_codex_config_policy.py",
                "core/providers/provider_codex_reasoning.py",
                "core/providers/provider_codex_wrappers.py",
                "core/providers/provider_codex_continuation_home.py",
                "core/providers/codex_app_server_runtime_lifecycle.py",
                "core/providers/codex_app_server_runtime_resume.py",
                "core/runtime/process_control.py",
                "core/runtime/provider_step_admission.py",
                "core/runtime/provider_start_handoff.py",
                "core/runtime/turn_queue_admission.py",
            )
        }

        self.assertTrue(expected.issubset(covered_paths), expected - covered_paths)

    def test_each_codex_operational_source_changes_the_artifact_digest(self) -> None:
        adapter = self.registry.get_agentic_runtime_adapter("codex")
        concrete = adapter.legacy_adapter
        baseline = runtime_adapter_artifact_digest(adapter)
        source_paths: set[Path] = set()
        for component in (concrete, *concrete.artifact_components):
            source_components = (
                (component,)
                if isinstance(component, ModuleType)
                else type(component).__mro__
            )
            for source_component in source_components:
                try:
                    source = inspect.getsourcefile(source_component)
                except TypeError:
                    source = None
                if source is not None:
                    source_paths.add(Path(source).resolve())
        original_read_bytes = Path.read_bytes

        for source_path in source_paths:
            with self.subTest(source_path=source_path.name):
                def modified_read_bytes(path: Path, *, target=source_path) -> bytes:
                    payload = original_read_bytes(path)
                    return (
                        payload + b"\n# simulated mutation\n"
                        if path.resolve() == target
                        else payload
                    )

                with patch.object(Path, "read_bytes", modified_read_bytes):
                    self.assertNotEqual(
                        runtime_adapter_artifact_digest(adapter),
                        baseline,
                    )

    def test_codex_profile_artifact_history_is_append_only(self) -> None:
        baseline = {
            "current_revision": "8",
            "revisions": {"7": "7" * 64, "8": "8" * 64},
        }
        valid = {
            "current_revision": "9",
            "revisions": {"7": "7" * 64, "8": "8" * 64, "9": "9" * 64},
        }
        compare_codex_profile_artifact_manifests(baseline, valid)

        invalid = {
            "current_revision": "9",
            "revisions": {"7": "7" * 64, "8": "0" * 64, "9": "9" * 64},
        }
        with self.assertRaisesRegex(RuntimeError, "history_changed:8"):
            compare_codex_profile_artifact_manifests(baseline, invalid)

        self.assertEqual(
            CODEX_PROFILE_ARTIFACT_DIGESTS[CODEX_PROFILE_REVISION],
            CODEX_PROFILE_ARTIFACT_DIGEST,
        )

    def test_repository_codex_profile_artifact_history_is_immutable(self) -> None:
        verify_codex_profile_artifact_history(Path(__file__).resolve().parents[3])

    def test_migration_rolls_enabled_nondefault_model_binding_to_current_revision(self) -> None:
        current_profile = publish_codex_agentic_profile(
            self.provider_store,
            definition=self.codex,
            model_id="alternate-history-model",
            now=NOW,
        )
        ensure_codex_preview_certificate(
            self.provider_store,
            definition=current_profile,
            provider_definition=self.codex,
            adapter=self.registry.get_agentic_runtime_adapter("codex"),
        )
        previous_profile = replace(
            current_profile,
            revision="8",
            capability_certificate_id="historical-certificate-unused",
        )
        self.provider_store.save_agentic_profile_definition(previous_profile)
        self.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=previous_profile.definition_id,
                definition_revision=previous_profile.revision,
                rollout_status="suspended",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
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
        older_profile = replace(
            previous_profile,
            revision="7",
            capability_certificate_id="older-certificate-unused",
        )
        self.provider_store.save_agentic_profile_definition(older_profile)
        self.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=older_profile.definition_id,
                definition_revision=older_profile.revision,
                rollout_status="suspended",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
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
        ensure_codex_preview_certificate(
            self.provider_store,
            definition=current_profile,
            provider_definition=self.codex,
            adapter=self.registry.get_agentic_runtime_adapter("codex"),
        )
        previous_profile = replace(
            current_profile,
            revision="8",
            capability_certificate_id="historical-authority-certificate",
        )
        self.provider_store.save_agentic_profile_definition(previous_profile)
        self.provider_store.save_agentic_profile_definition_status(
            AgenticProfileDefinitionStatus(
                definition_id=previous_profile.definition_id,
                definition_revision=previous_profile.revision,
                rollout_status="suspended",
                revision=0,
                updated_at=NOW,
            ),
            expected_revision=None,
        )
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
