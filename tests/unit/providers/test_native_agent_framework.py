from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

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
from core.providers.native_agent_contract import (
    validate_native_agent_installation,
    validate_native_runtime_adapter,
)
from core.providers.agentic_adapter import (
    LocalPrewarmResult,
    RuntimeProviderEvent,
    RuntimeRecoveryContext,
)
from core.providers.models import RuntimeBackendLaunchSpec
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
        self.assertIs(registry.get_agentic_runtime_adapter("codex"), controller)
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

    def test_registry_rejects_present_but_incomplete_native_adapter(self) -> None:
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

        with self.assertRaisesRegex(ValueError, "runtime_adapter_incomplete"):
            registry.register_native_agent_installation(
                certified,
                definition=build_gemini_cli_candidate_definition(NOW),
                runtime_adapter=_IncompleteNativeAdapter(),
            )

    def test_recovery_contract_validates_the_primitive_used_by_controller(self) -> None:
        candidate = build_gemini_cli_candidate_installation()
        adapter = SimpleNamespace(
            provider_definition=lambda: build_gemini_cli_candidate_definition(NOW),
            validate_backend=lambda: None,
            prepare_runtime_skills=lambda *_args: [],
            build_launch_spec=lambda *_args, **_kwargs: None,
            execute_turn=lambda **_kwargs: None,
            steer_turn=lambda *_args, **_kwargs: None,
            interrupt_turn=lambda *_args: False,
            build_recovery_command=lambda **_kwargs: [],
            close_runtime=lambda *_args: 0,
        )

        with self.assertRaisesRegex(ValueError, "runtime_adapter_incomplete"):
            validate_native_runtime_adapter(candidate, adapter)

        adapter.prewarm_runtime = lambda *_args: "provider-thread"
        validate_native_runtime_adapter(candidate, adapter)

    def test_codex_controller_recover_and_resume_use_validated_prewarm(self) -> None:
        controller = builtin_provider_registry().get_native_agent_controller("codex")
        context = RuntimeRecoveryContext(
            session=object(),  # type: ignore[arg-type]
            binding=object(),  # type: ignore[arg-type]
            provider_state=object(),  # type: ignore[arg-type]
        )
        launch_spec = RuntimeBackendLaunchSpec(
            provider_id="codex",
            command=["codex", "app-server"],
            env_overrides={},
            credential_binding_id=None,
            resolved_secret_refs=[],
            working_directory="/tmp",
            execution_mode="full-access",
            readable_roots=["/tmp"],
            writable_roots=["/tmp"],
        )
        recovered = LocalPrewarmResult(
            ready=True,
            provider_state_updates={
                "provider_thread_id": "thread-recovered",
                "continuation_id": "thread-recovered",
            },
        )
        lifecycle = controller.engine_adapter.local_process_lifecycle
        self.assertIsNotNone(lifecycle)
        with patch.object(
            lifecycle,
            "build_launch_spec",
            new=AsyncMock(return_value=launch_spec),
        ) as build_launch, patch.object(
            lifecycle,
            "prewarm",
            new=AsyncMock(return_value=recovered),
        ) as prewarm:
            recovery_result = asyncio.run(controller.recover(context))
            resume_result = asyncio.run(controller.resume(context))

        self.assertTrue(recovery_result.recovered)
        self.assertEqual(recovery_result.reason_code, "recovered")
        self.assertEqual(
            recovery_result.provider_state_updates["provider_thread_id"],
            "thread-recovered",
        )
        self.assertEqual(resume_result, recovery_result)
        self.assertEqual(build_launch.await_count, 2)
        self.assertEqual(prewarm.await_count, 2)

    def test_native_final_output_must_contain_non_empty_text(self) -> None:
        controller = builtin_provider_registry().get_native_agent_controller("codex")
        empty = RuntimeProviderEvent(
            event_type="runtime.output.final",
            correlation_id="turn-empty",
            ordinal=1,
            schema_version="1",
            payload={"text": "  "},
        )

        with self.assertRaisesRegex(RuntimeError, "agent_final_output_empty"):
            controller.final_output([empty])


class _IncompleteNativeAdapter:
    adapter_id = "gemini-cli-structured-candidate"
    adapter_version = "0"

    def provider_definition(self):
        return build_gemini_cli_candidate_definition(NOW)


if __name__ == "__main__":
    unittest.main()
