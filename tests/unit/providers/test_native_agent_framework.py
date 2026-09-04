from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.providers.agentic_profiles import CODEX_PROFILE_ARTIFACT_DIGEST
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.errors import ProviderNotFoundError
from core.providers.execution_families import (
    HOSTED_TEXT_EXECUTION_FAMILY,
    MAVERICK_AGENT_EXECUTION_FAMILY,
    NATIVE_AGENT_EXECUTION_FAMILY,
    NO_WORKSPACE_ACTIONS_MESSAGE,
    effective_agentic_execution_family,
    execution_family_catalog,
)
from core.providers.native_agent_builtins import (
    build_gemini_cli_candidate_definition,
    build_gemini_cli_candidate_installation,
)
from core.providers.native_agent_contract import validate_native_agent_installation
from core.providers.provider_registry import ProviderRegistry
from core.providers.service import builtin_provider_registry


NOW = datetime(2026, 9, 4, tzinfo=UTC)


class NativeAgentFrameworkTest(unittest.TestCase):
    def test_family_catalog_is_normative_and_ordered(self) -> None:
        catalog = execution_family_catalog()

        self.assertEqual(
            [item.family_id for item in catalog],
            [
                NATIVE_AGENT_EXECUTION_FAMILY,
                MAVERICK_AGENT_EXECUTION_FAMILY,
                HOSTED_TEXT_EXECUTION_FAMILY,
            ],
        )
        self.assertEqual(catalog[0].label, "Native Agents (CLI)")
        self.assertEqual(catalog[1].label, "Maverick Agents (API)")
        self.assertEqual(catalog[2].label, "Text-only Models (API)")
        self.assertEqual(NO_WORKSPACE_ACTIONS_MESSAGE, "No workspace tools or actions.")

    def test_only_exact_legacy_codex_identity_is_inferred_as_native(self) -> None:
        self.assertEqual(
            effective_agentic_execution_family(
                "",
                runtime_engine_id="codex",
                adapter_id="codex-app-server",
                model_provider_id="codex",
                provider_protocol="codex-app-server-stdio",
            ),
            NATIVE_AGENT_EXECUTION_FAMILY,
        )
        self.assertEqual(
            effective_agentic_execution_family(
                "",
                runtime_engine_id="vendor-agent",
                adapter_id="codex-app-server",
                model_provider_id="vendor",
                provider_protocol="human-terminal",
            ),
            "",
        )

    def test_codex_is_registered_through_generic_native_contract(self) -> None:
        registry = builtin_provider_registry()
        installation = registry.get_native_agent_installation("codex")
        controller = registry.get_native_agent_controller("codex")

        self.assertEqual(installation.execution_family, NATIVE_AGENT_EXECUTION_FAMILY)
        self.assertTrue(installation.release_eligible)
        self.assertEqual(installation.manifest.protocol_kind, "app_server")
        self.assertEqual(installation.recipe.context_owner, "native_runtime")
        self.assertTrue(installation.effects.workspace_confined)
        self.assertTrue(installation.effects.structured_effect_events)
        self.assertIs(controller.installation, installation)
        self.assertEqual(
            runtime_adapter_artifact_digest(registry.get_runtime_adapter("codex")),
            CODEX_PROFILE_ARTIFACT_DIGEST,
        )
        self.assertEqual(registry.get_provider_definition("codex").status, "active")

    def test_second_native_candidate_is_onboarded_but_cannot_be_enabled(self) -> None:
        registry = builtin_provider_registry()
        installation = registry.get_native_agent_installation("gemini-cli")

        self.assertFalse(installation.release_eligible)
        self.assertEqual(
            registry.get_provider_definition("gemini-cli").status,
            "disabled",
        )
        with self.assertRaises(ProviderNotFoundError):
            registry.get_native_agent_controller("gemini-cli")

        persisted_activation = replace(
            registry.get_provider_definition("gemini-cli"),
            status="active",
        )
        registry.register_provider_definition(persisted_activation)
        self.assertEqual(
            registry.get_provider_definition("gemini-cli").status,
            "disabled",
        )

    def test_unstructured_or_unobservable_native_adapter_is_rejected(self) -> None:
        candidate = build_gemini_cli_candidate_installation()
        with self.assertRaisesRegex(ValueError, "terminal_scraping_forbidden"):
            validate_native_agent_installation(
                replace(
                    candidate,
                    manifest=replace(
                        candidate.manifest,
                        machine_readable=False,
                        human_terminal_scraping=True,
                    ),
                )
            )
        with self.assertRaisesRegex(ValueError, "effects_unconfined"):
            validate_native_agent_installation(
                replace(
                    candidate,
                    effects=replace(candidate.effects, workspace_confined=False),
                )
            )
        with self.assertRaisesRegex(ValueError, "lifecycle_incomplete"):
            validate_native_agent_installation(
                replace(
                    candidate,
                    manifest=replace(candidate.manifest, lifecycle_operations=("discover",)),
                )
            )

    def test_registry_rejects_certified_manifest_without_executable_adapter(self) -> None:
        registry = ProviderRegistry()
        candidate = build_gemini_cli_candidate_installation()
        certified = replace(
            candidate,
            certificate=replace(
                candidate.certificate,
                certification_state="certified",
                certificate_id_template="certificate:{profile_id}",
                full_workspace_contract_revision="codex-baseline-v20",
            ),
        )

        with self.assertRaisesRegex(ValueError, "certified_adapter_missing"):
            registry.register_native_agent_installation(
                certified,
                definition=build_gemini_cli_candidate_definition(NOW),
            )


if __name__ == "__main__":
    unittest.main()
