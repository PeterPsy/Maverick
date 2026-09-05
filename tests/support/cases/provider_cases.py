"""Tests for provider registry, binding, selection, and Codex launch specs."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.application import create_application
from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.errors import ProviderCredentialBindingError, ProviderNotFoundError, ProviderSelectionError
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_codex_config_policy import (
    CODEX_POST_TOOL_USE_SHELL_MATCHER,
    codex_post_tool_use_hook_state_key,
    codex_post_tool_use_hook_trusted_hash,
)
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.provider_codex import CodexProviderAdapter, refresh_workspace_maverick_wrappers
from core.providers.provider_codex_hooks import CODEX_POST_TOOL_USE_HOOK_NAME
from core.providers.provider_codex_launch import CODEX_SKILL_MANIFEST_FILE, _skill_manifest
from core.providers.provider_codex_wrappers import _workspace_maverick_wrapper_source
from core.providers.provider_registry import ProviderRegistry
from core.providers.provider_selection import ProviderSelectionService
from core.providers.service import (
    build_runtime_backend_launch_spec,
    builtin_provider_registry,
    configure_workspace_provider,
    list_available_providers,
    register_builtin_providers,
    resolve_runtime_backend_for_session,
    resolve_provider_for_runtime_session,
)
from core.workspaces.models import WorkspaceGovernanceRecord
from core.runtime.workspace_api_token import verify_workspace_api_token
from core.providers.store import ProviderDocumentStore, ProviderCollections
from core.runtime.service import create_runtime_session
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretDocumentStore, SecretCollections
from core.skills.models import SkillDefinition
from tests.support.collections import FakeCollection


class ProvidersTestCase(unittest.TestCase):
    """Verify provider registry, selection, bindings, and Codex adapter behavior."""

    def provider_by_id(self, definitions: list[ProviderDefinition], provider_id: str) -> ProviderDefinition:
        for definition in definitions:
            if definition.provider_id == provider_id:
                return definition
        self.fail(f"Provider `{provider_id}` not found.")

    def make_provider_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )

    def make_runtime_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            )
        )

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "docs", "scripts"):
            target = repo_root / name
            if name == "docs":
                (target / "architecture").mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def make_catalog_command(self, name):
        command = self.make_repo_root() / name
        command.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        command.chmod(0o755)
        return str(command)

    def make_pinned_codex_session(
        self,
        provider_store: ProviderDocumentStore,
        runtime_store: RuntimeDocumentStore,
        *,
        repo_root: Path,
        session_id: str,
        workspace_id: str,
        codex_command: str | None = None,
        now: datetime | None = None,
    ):
        timestamp = now or datetime.now(tz=UTC)
        registry = builtin_provider_registry(codex_command=codex_command)
        configure_workspace_provider(
            provider_store,
            workspace_id=workspace_id,
            provider_id="codex",
            registry=registry,
            codex_command=codex_command,
            now=timestamp,
        )
        execution_binding = build_pinned_execution_binding(
            provider_store,
            registry,
            session_id=session_id,
            workspace_id=workspace_id,
            execution_mode="sandbox",
            now=timestamp,
        )
        session = create_runtime_session(
            runtime_store,
            session_id=session_id,
            workspace_id=workspace_id,
            agent_id="agent-1",
            now=timestamp,
            start_path=repo_root,
            execution_binding=execution_binding,
        )
        return session, registry

    def test_builtin_registry_registers_codex_provider(self) -> None:
        registry = builtin_provider_registry()
        definitions = registry.list_provider_definitions()
        codex = self.provider_by_id(definitions, "codex")

        self.assertEqual(
            {definition.provider_id for definition in definitions},
            {
                "cartesia",
                "codex",
                "deepgram",
                "gemini-cli",
                "google-ai-studio",
                "kokoro-hosted",
                "maverick-tool-loop",
                "openrouter",
            },
        )
        self.assertEqual(codex.kind, "runtime_backend")
        self.assertEqual(codex.provider_role, "runtime_engine")
        self.assertEqual(codex.default_model_family, "gpt-5.6-sol")
        self.assertTrue(codex.capabilities.supports_interactive_runtime)

    def test_builtin_registry_does_not_probe_codex_model_catalog(self) -> None:
        with patch("core.providers.provider_codex_models.subprocess.run") as run:
            registry = builtin_provider_registry()
            definitions = registry.list_provider_definitions()

        self.assertIn("codex", [definition.provider_id for definition in definitions])
        run.assert_not_called()

    def test_builtin_registry_exposes_remote_providers_as_disabled_metadata(self) -> None:
        definitions = builtin_provider_registry().list_provider_definitions()
        google_ai_studio = self.provider_by_id(definitions, "google-ai-studio")
        openrouter = self.provider_by_id(definitions, "openrouter")
        deepgram = self.provider_by_id(definitions, "deepgram")
        cartesia = self.provider_by_id(definitions, "cartesia")
        kokoro_hosted = self.provider_by_id(definitions, "kokoro-hosted")

        self.assertEqual(google_ai_studio.provider_role, "model_provider")
        self.assertEqual(google_ai_studio.status, "disabled")
        self.assertEqual(openrouter.provider_role, "model_provider")
        self.assertEqual(openrouter.status, "disabled")
        self.assertEqual(openrouter.default_model_family, "google/gemma-4-31b-it:free")
        self.assertEqual([option.model_id for option in openrouter.model_options], [
            "google/gemma-4-31b-it:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "deepseek/deepseek-v4-flash",
            "hexgrad/kokoro-82m",
        ])
        self.assertEqual(openrouter.network_requirements[0].allowed_hosts, ["openrouter.ai"])
        self.assertEqual(openrouter.execution_contract.adapter_type if openrouter.execution_contract else None, "hosted_text_generation")
        self.assertEqual(
            openrouter.execution_contract.secret_alias_or_logical_name if openrouter.execution_contract else None,
            "openrouter_api_key",
        )
        self.assertEqual(deepgram.provider_role, "speech_provider")
        self.assertEqual(cartesia.provider_role, "speech_provider")
        self.assertEqual(kokoro_hosted.provider_role, "speech_provider")
        self.assertEqual(kokoro_hosted.status, "disabled")

    def test_provider_settings_can_refresh_codex_model_catalog(self) -> None:
        provider_store = self.make_provider_store()
        payload = {
            "models": [
                {
                    "slug": "gpt-settings",
                    "display_name": "GPT Settings",
                    "visibility": "list",
                    "default_reasoning_level": "medium",
                    "supported_reasoning_levels": [
                        {"effort": "medium", "description": "Balanced reasoning depth"}
                    ],
                }
            ]
        }
        result = type("Result", (), {"stdout": json.dumps(payload)})()

        with patch("core.providers.provider_codex_models.subprocess.run", return_value=result) as run:
            providers = list_available_providers(
                provider_store,
                codex_command=self.make_catalog_command("codex-settings"),
                refresh_model_catalog=True,
            )

        self.assertEqual(sum(call.args[0][1:] == ["debug", "models"] for call in run.call_args_list), 1)
        self.assertEqual(self.provider_by_id(providers, "codex").model_options[0].model_id, "gpt-settings")
        self.assertEqual(provider_store.get_provider_definition("codex").model_options[0].model_id, "gpt-settings")

    def test_provider_settings_refresh_bypasses_cached_codex_model_catalog(self) -> None:
        provider_store = self.make_provider_store()
        first_payload = {
            "models": [
                {
                    "slug": "gpt-old",
                    "display_name": "GPT Old",
                    "visibility": "list",
                    "default_reasoning_level": "high",
                    "supported_reasoning_levels": [{"effort": "high"}],
                }
            ]
        }
        refreshed_payload = {
            "models": [
                {
                    "slug": "gpt-refreshed",
                    "display_name": "GPT Refreshed",
                    "visibility": "list",
                    "default_reasoning_level": "medium",
                    "supported_reasoning_levels": [{"effort": "medium"}],
                }
            ]
        }
        first_result = type("Result", (), {"stdout": json.dumps(first_payload)})()
        refreshed_result = type("Result", (), {"stdout": json.dumps(refreshed_payload)})()
        command = self.make_catalog_command("codex-refresh-bypass")

        with patch("core.providers.provider_codex_models.subprocess.run", return_value=first_result):
            CodexProviderAdapter(codex_command=command).model_options(refresh=True)
        with patch("core.providers.provider_codex_models.subprocess.run", return_value=refreshed_result) as run:
            providers = list_available_providers(
                provider_store,
                codex_command=command,
                refresh_model_catalog=True,
            )

        self.assertEqual(sum(call.args[0][1:] == ["debug", "models"] for call in run.call_args_list), 1)
        self.assertEqual(self.provider_by_id(providers, "codex").model_options[0].model_id, "gpt-refreshed")
        self.assertEqual(provider_store.get_provider_definition("codex").model_options[0].model_id, "gpt-refreshed")

    def test_non_refresh_registration_preserves_refreshed_codex_model_catalog(self) -> None:
        provider_store = self.make_provider_store()
        payload = {
            "models": [
                {
                    "slug": "gpt-5.6-sol",
                    "display_name": "GPT-5.6 Sol",
                    "visibility": "list",
                    "default_reasoning_level": "low",
                    "supported_reasoning_levels": [
                        {"effort": "low"},
                        {"effort": "xhigh"},
                        {"effort": "max"},
                        {"effort": "ultra"},
                    ],
                },
                {
                    "slug": "gpt-5.5",
                    "display_name": "GPT-5.5",
                    "visibility": "list",
                    "default_reasoning_level": "medium",
                    "supported_reasoning_levels": [
                        {"effort": "medium"},
                        {"effort": "xhigh"},
                    ],
                },
            ]
        }
        result = type("Result", (), {"stdout": json.dumps(payload)})()
        command = self.make_catalog_command("codex-preserve-refreshed")

        with patch("core.providers.provider_codex_models.subprocess.run", return_value=result) as run:
            register_builtin_providers(provider_store, codex_command=command, refresh_model_catalog=True)
        register_builtin_providers(provider_store, codex_command=command)
        providers = list_available_providers(provider_store, codex_command=command)

        self.assertEqual(run.call_count, 1)
        self.assertEqual(
            [option.model_id for option in provider_store.get_provider_definition("codex").model_options],
            ["gpt-5.6-sol", "gpt-5.5"],
        )
        self.assertEqual(
            [option.model_id for option in self.provider_by_id(providers, "codex").model_options],
            ["gpt-5.6-sol", "gpt-5.5"],
        )
        persisted_options = provider_store.get_provider_definition("codex").model_options
        self.assertEqual(
            [option.default_reasoning_effort for option in persisted_options],
            ["max", "xhigh"],
        )
        self.assertEqual(
            [item.effort for item in persisted_options[0].supported_reasoning_efforts],
            ["low", "xhigh", "max"],
        )

    def test_non_refresh_registration_updates_stale_codex_fallback_model(self) -> None:
        provider_store = self.make_provider_store()
        from core.providers.provider_codex_models import build_codex_definition

        codex = build_codex_definition()
        stale_option = replace(codex.model_options[0], model_id="gpt-5.5", label="gpt-5.5")
        provider_store.save_provider_definition(
            replace(codex, default_model_family="gpt-5.5", model_options=[stale_option])
        )

        with patch("core.providers.native_agent_reconciliation.discover_codex_native_catalog", return_value=None):
            register_builtin_providers(provider_store)

        refreshed = provider_store.get_provider_definition("codex")
        self.assertEqual(refreshed.default_model_family, "gpt-5.6-sol")
        self.assertEqual([option.model_id for option in refreshed.model_options], ["gpt-5.6-sol"])

    def test_codex_model_catalog_is_cached_after_first_probe(self) -> None:
        payload = {
            "models": [
                {
                    "slug": "gpt-test",
                    "display_name": "GPT Test",
                    "description": "Test model.",
                    "visibility": "list",
                    "default_reasoning_level": "high",
                    "supported_reasoning_levels": [
                        {"effort": "high", "description": "Greater reasoning depth"}
                    ],
                }
            ]
        }
        result = type("Result", (), {"stdout": json.dumps(payload)})()
        adapter = CodexProviderAdapter(codex_command="/tmp/codex-cache")

        with patch("core.providers.provider_codex_models.subprocess.run", return_value=result) as run:
            first = adapter.model_options(refresh=True)
            second = adapter.model_options()
            third = CodexProviderAdapter(codex_command="/tmp/codex-cache").model_options()

        self.assertEqual(run.call_count, 1)
        self.assertEqual([option.model_id for option in first], ["gpt-test"])
        self.assertEqual([option.model_id for option in second], ["gpt-test"])
        self.assertEqual([option.model_id for option in third], ["gpt-test"])

    def test_codex_model_catalog_fallback_is_not_cached(self) -> None:
        old_payload = {
            "models": [
                {
                    "slug": "gpt-before-error",
                    "display_name": "GPT Before Error",
                    "visibility": "list",
                    "default_reasoning_level": "high",
                    "supported_reasoning_levels": [{"effort": "high"}],
                }
            ]
        }
        payload = {
            "models": [
                {
                    "slug": "gpt-after-error",
                    "display_name": "GPT After Error",
                    "description": "Recovered model.",
                    "visibility": "list",
                    "default_reasoning_level": "high",
                    "supported_reasoning_levels": [{"effort": "high"}],
                }
            ]
        }
        old_result = type("Result", (), {"stdout": json.dumps(old_payload)})()
        result = type("Result", (), {"stdout": json.dumps(payload)})()
        adapter = CodexProviderAdapter(codex_command="/tmp/codex-fallback-not-cached")

        with patch("core.providers.provider_codex_models.subprocess.run", return_value=old_result):
            adapter.model_options(refresh=True)
        with patch("core.providers.provider_codex_models.subprocess.run", side_effect=OSError):
            first = adapter.model_options(refresh=True)
        with patch("core.providers.provider_codex_models.subprocess.run", return_value=result) as run:
            second = adapter.model_options()

        self.assertEqual([option.model_id for option in first], ["gpt-5.6-sol"])
        self.assertEqual(run.call_count, 1)
        self.assertEqual([option.model_id for option in second], ["gpt-after-error"])

    def test_application_bootstrap_registers_builtin_providers(self) -> None:
        provider_store = self.make_provider_store()
        repo_root = self.make_repo_root()

        application = create_application(start_path=repo_root, provider_store=provider_store)

        self.assertEqual(application["status"], "initialized")
        self.assertEqual(provider_store.get_provider_definition("codex").label, "Codex")

    def test_workspace_selection_requires_explicit_provider_configuration(self) -> None:
        provider_store = self.make_provider_store()
        register_builtin_providers(provider_store)
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )

        with self.assertRaisesRegex(
            ProviderSelectionError,
            "runtime_execution_binding_missing",
        ):
            resolve_provider_for_runtime_session(provider_store, session=session)

    def test_configured_selection_is_persisted_per_workspace(self) -> None:
        provider_store = self.make_provider_store()
        register_builtin_providers(provider_store)

        selection = configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="codex",
            selection_reason="default local runtime backend",
        )

        self.assertEqual(selection.provider_id, "codex")
        self.assertEqual(provider_store.get_provider_selection("default").selection_reason, "default local runtime backend")

    def test_runtime_resolution_uses_configured_codex_adapter(self) -> None:
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session, registry = self.make_pinned_codex_session(
            provider_store,
            runtime_store,
            repo_root=repo_root,
            session_id="sess-codex-runtime",
            workspace_id="default",
        )

        provider, selection, runtime_adapter = resolve_runtime_backend_for_session(
            provider_store,
            session=session,
            registry=registry,
        )

        self.assertEqual(provider.provider_id, "codex")
        self.assertEqual(selection.provider_id if selection is not None else None, "codex")
        self.assertEqual(runtime_adapter.provider_definition().provider_id, "codex")

    def test_runtime_resolution_honors_codex_command_environment_override(self) -> None:
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-codex-command-override",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )

        with patch.dict(os.environ, {"MAVERICK_CODEX_COMMAND": "/opt/maverick/codex-fixture"}, clear=False):
            register_builtin_providers(provider_store)
            configure_workspace_provider(provider_store, workspace_id="default", provider_id="codex")
            _provider, _selection, runtime_adapter = resolve_runtime_backend_for_session(
                provider_store,
                session=session,
            )

        self.assertEqual(runtime_adapter.codex_command, "/opt/maverick/codex-fixture")

    def test_configure_workspace_provider_rejects_hosted_api_without_runtime_adapter(self) -> None:
        provider_store = self.make_provider_store()
        registry = builtin_provider_registry()
        now = datetime.now(tz=UTC)
        registry.register_provider_definition(
            ProviderDefinition(
                provider_id="hosted-text-only",
                label="Hosted Text Only",
                description="Hosted model provider that must not own runtime execution.",
                kind="hosted_api",
                provider_role="model_provider",
                status="active",
                capabilities=ProviderCapabilitySet(
                    supports_interactive_runtime=False,
                    supports_streaming=True,
                    supports_tools=False,
                    supports_mcp=False,
                    supports_skills=False,
                    supports_filesystem_access=False,
                    supports_remote_execution=True,
                    supports_api_key_auth=True,
                    supports_local_binary=False,
                ),
                default_model_family="fast-text",
                requires_credentials=False,
                supported_execution_modes=[],
                created_at=now,
                updated_at=now,
            )
        )

        with self.assertRaisesRegex(ProviderNotFoundError, "Runtime backend adapter"):
            configure_workspace_provider(
                provider_store,
                workspace_id="default",
                provider_id="hosted-text-only",
                registry=registry,
            )
        self.assertIsNone(provider_store.get_provider_selection("default"))

    def test_bindings_store_secret_refs_without_raw_secret_values(self) -> None:
        provider_store = self.make_provider_store()
        binding = bind_provider_credential(
            provider_store,
            provider_id="openai-compatible",
            secret_ref="platform:secret-alias/openai-compatible",
            workspace_id="default",
            label="default llm key",
        )

        self.assertEqual(binding.secret_ref, "platform:secret-alias/openai-compatible")
        self.assertEqual(binding.label, "default llm key")
        self.assertFalse(hasattr(binding, "api_key"))

    def test_provider_bindings_reject_non_core_secret_refs(self) -> None:
        provider_store = self.make_provider_store()

        with self.assertRaises(ProviderCredentialBindingError):
            bind_provider_credential(
                provider_store,
                provider_id="openai-compatible",
                secret_ref="platform:providers/openai-compatible",
                workspace_id="default",
            )

    def test_provider_binding_id_collision_is_rejected(self) -> None:
        provider_store = self.make_provider_store()
        bind_provider_credential(
            provider_store,
            provider_id="openai-compatible",
            secret_ref="platform:secret-alias/openai-compatible",
            workspace_id="default",
            binding_id="shared-binding",
        )

        with self.assertRaises(ProviderCredentialBindingError):
            bind_provider_credential(
                provider_store,
                provider_id="other-provider",
                secret_ref="platform:secret-alias/other-provider",
                workspace_id="default",
                binding_id="shared-binding",
            )

    def test_selection_requires_binding_for_credentialed_runtime_provider(self) -> None:
        provider_store = self.make_provider_store()
        registry = ProviderRegistry()
        now = datetime.now(tz=UTC)
        registry.register_provider_definition(
            ProviderDefinition(
                provider_id="claude-code",
                label="Claude Code",
                description="Future hosted runtime backend.",
                kind="runtime_backend",
                status="active",
                capabilities=ProviderCapabilitySet(
                    supports_interactive_runtime=True,
                    supports_streaming=True,
                    supports_tools=True,
                    supports_mcp=False,
                    supports_skills=False,
                    supports_filesystem_access=False,
                    supports_remote_execution=True,
                    supports_api_key_auth=True,
                    supports_local_binary=False,
                ),
                default_model_family="claude-code",
                requires_credentials=True,
                supported_execution_modes=["sandbox"],
                created_at=now,
                updated_at=now,
            )
        )

        service = ProviderSelectionService(provider_store, registry)

        with self.assertRaises(ProviderCredentialBindingError):
            service.configure_workspace_provider(workspace_id="default", provider_id="claude-code")

    def test_codex_post_tool_use_hook_trust_identity_is_stable(self) -> None:
        self.assertEqual(
            codex_post_tool_use_hook_state_key(config_path=Path("/tmp/runtime/codex-home/config.toml")),
            "/tmp/runtime/codex-home/config.toml:post_tool_use:0:0",
        )
        self.assertEqual(
            codex_post_tool_use_hook_trusted_hash(command="/tmp/maverick_codex_post_tool_use_hook.py"),
            "sha256:aaaa8ec2f50abcbb07464a6a10bbc2686b20bd279c17e0cd13cd181944b2f308",
        )

    def test_codex_launch_spec_is_built_from_provider_adapter_not_runtime_domain(self) -> None:
        provider_store = self.make_provider_store()
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        from tests.support.native_agent_catalog import codex_snapshot
        from core.providers.native_runtime_artifact import inspect_native_runtime_artifact

        # This launch-shape fixture intentionally substitutes an executable;
        # approve only that test artifact, never weaken production validation.
        command = repo_root / "codex-launch-fixture"
        command.write_text("#!/bin/sh\necho codex-launch-fixture-1\n")
        command.chmod(0o755)
        approval = patch("core.providers.native_agent_builtins.CODEX_PACKAGED_RUNTIME_ARTIFACT",
                         inspect_native_runtime_artifact(str(command)))
        approval.start()
        self.addCleanup(approval.stop)

        discovery = patch("core.providers.native_agent_reconciliation.discover_codex_native_catalog",
                          return_value=codex_snapshot("gpt-5.6-sol"))
        discovery.start()
        self.addCleanup(discovery.stop)
        session, registry = self.make_pinned_codex_session(
            provider_store,
            runtime_store,
            repo_root=repo_root,
            session_id="sess-1",
            workspace_id="acme",
            now=now,
            codex_command=str(command),
        )

        launch_spec = build_runtime_backend_launch_spec(
            provider_store,
            session=session,
            registry=registry,
            codex_command=str(command),
        )

        self.assertEqual(launch_spec.provider_id, "codex")
        self.assertEqual(launch_spec.command[:2], [os.sys.executable, str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1" / "bin" / "workspace_sandbox.py")])
        self.assertIn("--workspace-root", launch_spec.command)
        self.assertIn(str(repo_root / "workspaces" / "acme"), launch_spec.command)
        self.assertIn("--runtime-root", launch_spec.command)
        self.assertIn(str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1"), launch_spec.command)
        separator_index = launch_spec.command.index("--")
        self.assertEqual(
            launch_spec.command[separator_index + 1 : separator_index + 6],
            [str(command), "--disable", "apps", "--disable", "plugins"],
        )
        self.assertEqual(launch_spec.command[separator_index + 6], "app-server")
        self.assertNotIn("use_legacy_landlock", launch_spec.command)
        self.assertEqual(launch_spec.execution_mode, "sandbox")
        self.assertEqual(launch_spec.working_directory, str(repo_root / "workspaces" / "acme"))
        self.assertEqual(launch_spec.readable_roots, [str(repo_root / "workspaces" / "acme")])
        self.assertEqual(launch_spec.writable_roots, [str(repo_root / "workspaces" / "acme")])
        self.assertIn("CODEX_HOME", launch_spec.env_overrides)
        self.assertEqual(launch_spec.env_overrides["MAVERICK_WORKSPACE_ROOT"], str(repo_root / "workspaces" / "acme"))
        self.assertEqual(launch_spec.env_overrides["MAVERICK_WORKSPACE_ID"], "acme")
        self.assertEqual(launch_spec.env_overrides["MAVERICK_EFFECTIVE_MODE"], "sandbox")
        claims = verify_workspace_api_token(launch_spec.env_overrides["MAVERICK_RUNTIME_API_TOKEN"])
        self.assertIsNotNone(claims)
        assert claims is not None
        self.assertEqual(claims["workspace_id"], "acme")
        self.assertEqual(claims["runtime_session_id"], "sess-1")
        self.assertEqual(claims["mode"], "sandbox")
        self.assertTrue(claims["token_id"])
        self.assertEqual(launch_spec.env_overrides["TMPDIR"], str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1"))
        self.assertEqual(launch_spec.env_overrides["HOME"], launch_spec.env_overrides["CODEX_HOME"])
        runtime_bin = repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1" / "bin"
        self.assertTrue((runtime_bin / "maverick").is_file())
        self.assertTrue(os.access(runtime_bin / "maverick", os.X_OK))
        self.assertIn("/api/runtime/cli", (runtime_bin / "maverick").read_text(encoding="utf-8"))
        self.assertNotIn("timeout=30", (runtime_bin / "maverick").read_text(encoding="utf-8"))
        hook_script = runtime_bin / CODEX_POST_TOOL_USE_HOOK_NAME
        self.assertTrue(hook_script.is_file())
        self.assertTrue(os.access(hook_script, os.X_OK))
        self.assertIn("/api/runtime/provider-hooks/codex/post-tool-use", hook_script.read_text(encoding="utf-8"))
        self.assertTrue((runtime_bin / "workspace_sandbox.py").is_file())
        self.assertEqual(launch_spec.env_overrides["PATH"].split(os.pathsep)[0], str(runtime_bin))
        self.assertEqual(launch_spec.env_overrides["MAVERICK_RUNTIME_BIN"], str(runtime_bin))
        runtime_config = (Path(launch_spec.env_overrides["CODEX_HOME"]) / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[shell_environment_policy]", runtime_config)
        self.assertIn('inherit = "all"', runtime_config)
        self.assertIn("ignore_default_excludes = true", runtime_config)
        self.assertIn('"MAVERICK_RUNTIME_API_TOKEN"', runtime_config)
        self.assertNotIn(launch_spec.env_overrides["MAVERICK_RUNTIME_API_TOKEN"], runtime_config)
        self.assertIn("experimental_use_unified_exec_tool = false", runtime_config)
        self.assertIn("[skills]", runtime_config)
        self.assertIn("include_instructions = true", runtime_config)
        self.assertIn("[shell_environment_policy.set]", runtime_config)
        self.assertIn(f'PATH = "{launch_spec.env_overrides["PATH"]}"', runtime_config)
        self.assertIn(f"MAVERICK_RUNTIME_BIN = \"{runtime_bin}\"", runtime_config)
        self.assertIn(f"MAVERICK_RUNTIME_ROOT = \"{runtime_bin.parent}\"", runtime_config)
        self.assertIn(f"MAVERICK_WORKSPACE_ROOT = \"{repo_root / 'workspaces' / 'acme'}\"", runtime_config)
        self.assertIn("[[hooks.PostToolUse]]", runtime_config)
        self.assertIn(f"matcher = {json.dumps(CODEX_POST_TOOL_USE_SHELL_MATCHER)}", runtime_config)
        self.assertIn("exec_command", runtime_config)
        self.assertNotIn("web_search", runtime_config)
        self.assertIn(str(hook_script), runtime_config)
        hook_state_key = codex_post_tool_use_hook_state_key(
            config_path=Path(launch_spec.env_overrides["CODEX_HOME"]) / "config.toml"
        )
        hook_trusted_hash = codex_post_tool_use_hook_trusted_hash(command=str(hook_script))
        self.assertIn(f"[hooks.state.{json.dumps(hook_state_key)}]", runtime_config)
        self.assertIn(f"trusted_hash = {json.dumps(hook_trusted_hash)}", runtime_config)
        self.assertIn("hooks = true", runtime_config)
        repository_root = Path(__file__).resolve().parents[3]
        self.assertNotIn("PYTHONPATH", launch_spec.env_overrides)
        self.assertNotIn(str(repository_root / "core"), launch_spec.command)
        self.assertNotIn(str(repository_root / "apps"), launch_spec.command)
        self.assertNotIn(str(repository_root / "scripts"), launch_spec.command)
        self.assertTrue((Path(launch_spec.env_overrides["CODEX_HOME"])).is_dir())

    def test_codex_nvm_dependency_root_is_standalone_binary_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            node_version_root = home / ".nvm" / "versions" / "node" / "v24.14.0"
            codex_bin = node_version_root / "bin" / "codex"
            codex_js = node_version_root / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            standalone = (
                node_version_root
                / "lib"
                / "node_modules"
                / "@openai"
                / "codex"
                / "node_modules"
                / "@openai"
                / "codex-linux-x64"
                / "vendor"
                / "x86_64-unknown-linux-musl"
                / "codex"
                / "codex"
            )
            rg = standalone.parent.parent / "path" / "rg"
            codex_js.parent.mkdir(parents=True)
            standalone.parent.mkdir(parents=True)
            rg.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            standalone.write_text("binary\n", encoding="utf-8")
            rg.write_text("rg-binary\n", encoding="utf-8")
            codex_bin.parent.mkdir(parents=True)
            codex_bin.symlink_to("../lib/node_modules/@openai/codex/bin/codex.js")
            adapter = CodexProviderAdapter(codex_command="codex")

            with patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                with patch("core.providers.provider_codex.shutil.which", return_value=str(codex_bin)):
                    roots = adapter._command_dependency_roots("codex")
                    runtime_command = adapter._runtime_command("codex")
                    sandbox_command = adapter._build_command(
                        workspace_root=home / "workspace",
                        runtime_root=home / "workspace" / "runtime",
                        runtime_home=home / "workspace" / "runtime" / "codex-home",
                        execution_mode="sandbox",
                    )

        self.assertEqual(roots, [standalone.parent])
        self.assertEqual(runtime_command, str(standalone))
        self.assertIn("--dependency-file", sandbox_command)
        self.assertIn(f"{standalone}={home / 'workspace' / 'runtime' / 'bin' / 'codex'}", sandbox_command)
        self.assertIn(f"{rg}={home / 'workspace' / 'runtime' / 'bin' / 'rg'}", sandbox_command)
        separator_index = sandbox_command.index("--")
        self.assertEqual(sandbox_command[separator_index + 1], str(home / "workspace" / "runtime" / "bin" / "codex"))

    def test_codex_current_vendor_layout_uses_native_binary_and_codex_path_rg(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            package_root = home / "lib" / "node_modules" / "@openai" / "codex"
            codex_bin = home / "bin" / "codex"
            codex_js = package_root / "bin" / "codex.js"
            vendor_target = (
                package_root
                / "node_modules"
                / "@openai"
                / "codex-linux-x64"
                / "vendor"
                / "x86_64-unknown-linux-musl"
            )
            standalone = vendor_target / "bin" / "codex"
            rg = vendor_target / "codex-path" / "rg"
            codex_js.parent.mkdir(parents=True)
            standalone.parent.mkdir(parents=True)
            rg.parent.mkdir(parents=True)
            codex_bin.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            standalone.write_text("binary\n", encoding="utf-8")
            rg.write_text("rg-binary\n", encoding="utf-8")
            codex_bin.symlink_to(codex_js)
            adapter = CodexProviderAdapter(codex_command="codex")

            with patch("core.providers.provider_codex.shutil.which", return_value=str(codex_bin)):
                runtime_command = adapter._runtime_command("codex")
                sandbox_command = adapter._build_command(
                    workspace_root=home / "workspace",
                    runtime_root=home / "workspace" / "runtime",
                    runtime_home=home / "workspace" / "runtime" / "codex-home",
                    execution_mode="sandbox",
                )

        self.assertEqual(runtime_command, str(standalone))
        self.assertIn(f"{standalone}={home / 'workspace' / 'runtime' / 'bin' / 'codex'}", sandbox_command)
        self.assertIn(f"{rg}={home / 'workspace' / 'runtime' / 'bin' / 'rg'}", sandbox_command)

    def test_codex_nvm_dependency_root_fails_closed_without_standalone_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            node_version_root = home / ".nvm" / "versions" / "node" / "v24.14.0"
            codex_bin = node_version_root / "bin" / "codex"
            codex_js = node_version_root / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            codex_js.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            codex_bin.parent.mkdir(parents=True)
            codex_bin.symlink_to("../lib/node_modules/@openai/codex/bin/codex.js")
            adapter = CodexProviderAdapter(codex_command="codex")

            with patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                with patch("core.providers.provider_codex.shutil.which", return_value=str(codex_bin)):
                    roots = adapter._command_dependency_roots("codex")

        self.assertEqual(roots, [codex_js.parent])
        self.assertNotIn(node_version_root, roots)

    def test_codex_launch_bypasses_host_wrapper_that_clears_runtime_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            wrapper = home / "bin" / "codex"
            codex_js = home / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            standalone = (
                home
                / "lib"
                / "node_modules"
                / "@openai"
                / "codex"
                / "node_modules"
                / "@openai"
                / "codex-linux-x64"
                / "vendor"
                / "x86_64-unknown-linux-musl"
                / "codex"
                / "codex"
            )
            codex_js.parent.mkdir(parents=True)
            standalone.parent.mkdir(parents=True)
            wrapper.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            standalone.write_text("binary\n", encoding="utf-8")
            wrapper.write_text(
                "#!/bin/sh\n"
                f"CODEX_REAL={str(codex_js)!r}\n"
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin\n"
                "export PATH\n"
                "unset CODEX_HOME\n"
                '"$CODEX_REAL" "$@"\n',
                encoding="utf-8",
            )
            adapter = CodexProviderAdapter(codex_command="codex")

            with patch("core.providers.provider_codex.shutil.which", return_value=str(wrapper)):
                roots = adapter._command_dependency_roots("codex")
                runtime_command = adapter._runtime_command("codex")

        self.assertEqual(roots, [standalone.parent])
        self.assertEqual(runtime_command, str(standalone))

    def test_codex_full_access_runtime_bin_prefers_vendored_rg_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            node_version_root = home / ".nvm" / "versions" / "node" / "v24.14.0"
            codex_bin = node_version_root / "bin" / "codex"
            codex_js = node_version_root / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            standalone = (
                node_version_root
                / "lib"
                / "node_modules"
                / "@openai"
                / "codex"
                / "node_modules"
                / "@openai"
                / "codex-linux-x64"
                / "vendor"
                / "x86_64-unknown-linux-musl"
                / "codex"
                / "codex"
            )
            rg = standalone.parent.parent / "path" / "rg"
            codex_js.parent.mkdir(parents=True)
            standalone.parent.mkdir(parents=True)
            rg.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            standalone.write_text("binary\n", encoding="utf-8")
            rg.write_text("rg-binary\n", encoding="utf-8")
            codex_bin.parent.mkdir(parents=True)
            codex_bin.symlink_to("../lib/node_modules/@openai/codex/bin/codex.js")

            runtime_store = self.make_runtime_store()
            repo_root = self.make_repo_root()
            session = create_runtime_session(
                runtime_store,
                session_id="sess-full-rg",
                workspace_id="default",
                agent_id="agent-1",
                requested_mode="full-access",
                governance=WorkspaceGovernanceRecord(
                    workspace_id="default",
                    allow_app_installation=True,
                    allow_agent_creation=True,
                    allow_agent_management=True,
                    allow_custom_apps=True,
                    allow_full_access_runtime=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                platform_allows_full_access=True,
                start_path=repo_root,
            )

            with patch.dict(os.environ, {"HOME": str(home)}, clear=False):
                with patch("core.providers.provider_codex.shutil.which", return_value=str(codex_bin)):
                    spec = CodexProviderAdapter(codex_command="codex").build_launch_spec(session)

        runtime_bin = Path(spec.env_overrides["PATH"].split(os.pathsep)[0])
        runtime_rg = runtime_bin / "rg"
        self.assertEqual(spec.command[0], str(standalone))
        self.assertEqual(runtime_rg.read_text(encoding="utf-8"), "rg-binary\n")
        self.assertTrue(os.access(runtime_rg, os.X_OK))
        self.assertEqual(spec.env_overrides["HOME"], spec.env_overrides["CODEX_HOME"])
        self.assertTrue((runtime_bin / CODEX_POST_TOOL_USE_HOOK_NAME).is_file())

    def test_codex_skill_prepare_reuses_current_manifest(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-codex-skills",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        source_root = repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "writer"
        source_root.mkdir(parents=True)
        (source_root / "SKILL.md").write_text("# Writer\n", encoding="utf-8")
        skill = SkillDefinition(
            skill_id="workspace.writer",
            local_skill_id="writer",
            name="Writer",
            description="Writes.",
            source_root=str(source_root),
            owner_kind="workspace",
            owner_id="default",
            workspace_id="default",
            status="available",
        )
        adapter = CodexProviderAdapter(codex_command="/bin/echo")

        adapter.prepare_runtime_skills(session, [skill])
        target_root = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "sess-codex-skills" / "codex-home" / "skills" / "workspace" / "writer"
        sentinel = target_root / "sentinel.txt"
        sentinel.write_text("kept when cached\n", encoding="utf-8")

        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("cache hit should not read skill file bytes")):
            adapter.prepare_runtime_skills(session, [skill])

        self.assertTrue(sentinel.exists())

        (source_root / "SKILL.md").write_text("# Writer\n\nChanged.\n", encoding="utf-8")
        adapter.prepare_runtime_skills(session, [skill])

        self.assertFalse(sentinel.exists())
        self.assertEqual((target_root / "SKILL.md").read_text(encoding="utf-8"), "# Writer\n\nChanged.\n")

    def test_codex_skill_prepare_removes_stale_manifest_targets(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-codex-stale-skills",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        skills_source_root = repo_root / "workspaces" / "default" / "data" / "skills" / "skills"
        writer_root = skills_source_root / "writer"
        reviewer_root = skills_source_root / "reviewer"
        writer_root.mkdir(parents=True)
        reviewer_root.mkdir(parents=True)
        (writer_root / "SKILL.md").write_text("# Writer\n", encoding="utf-8")
        (reviewer_root / "SKILL.md").write_text("# Reviewer\n", encoding="utf-8")
        writer = SkillDefinition(
            skill_id="workspace.writer",
            local_skill_id="writer",
            name="Writer",
            description="Writes.",
            source_root=str(writer_root),
            owner_kind="workspace",
            owner_id="default",
            workspace_id="default",
            status="available",
        )
        reviewer = SkillDefinition(
            skill_id="workspace.reviewer",
            local_skill_id="reviewer",
            name="Reviewer",
            description="Reviews.",
            source_root=str(reviewer_root),
            owner_kind="workspace",
            owner_id="default",
            workspace_id="default",
            status="available",
        )
        adapter = CodexProviderAdapter(codex_command="/bin/echo")

        adapter.prepare_runtime_skills(session, [writer, reviewer])
        skills_root = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "sess-codex-stale-skills" / "codex-home" / "skills"
        writer_target = skills_root / "workspace" / "writer"
        reviewer_target = skills_root / "workspace" / "reviewer"
        self.assertTrue(writer_target.is_dir())
        self.assertTrue(reviewer_target.is_dir())

        adapter.prepare_runtime_skills(session, [reviewer])

        self.assertFalse(writer_target.exists())
        self.assertTrue((reviewer_target / "SKILL.md").is_file())

    def test_codex_skill_prepare_empty_set_cleans_previous_skills(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-codex-empty-skills",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        source_root = repo_root / "workspaces" / "default" / "data" / "skills" / "skills" / "writer"
        source_root.mkdir(parents=True)
        (source_root / "SKILL.md").write_text("# Writer\n", encoding="utf-8")
        skill = SkillDefinition(
            skill_id="workspace.writer",
            local_skill_id="writer",
            name="Writer",
            description="Writes.",
            source_root=str(source_root),
            owner_kind="workspace",
            owner_id="default",
            workspace_id="default",
            status="available",
        )
        adapter = CodexProviderAdapter(codex_command="/bin/echo")

        adapter.prepare_runtime_skills(session, [skill])
        skills_root = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "sess-codex-empty-skills" / "codex-home" / "skills"
        target_root = skills_root / "workspace" / "writer"
        self.assertTrue(target_root.is_dir())
        manifest_path = skills_root / CODEX_SKILL_MANIFEST_FILE
        manifest_path.write_text(
            json.dumps(_skill_manifest([]), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        adapter.prepare_runtime_skills(session, [])

        self.assertFalse(target_root.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], [])

    def test_codex_runtime_home_is_prepared_from_configured_source_home(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        source_home = repo_root / "operator-codex-home"
        source_home.mkdir()
        (source_home / "auth.json").write_text('{"tokens": "test"}\n', encoding="utf-8")
        (source_home / "version.json").write_text('{"version": "test"}\n', encoding="utf-8")
        (source_home / ".personality_migration").write_text("done\n", encoding="utf-8")
        (source_home / "installation_id").write_text("install-1\n", encoding="utf-8")
        (source_home / "config.toml").write_text(
            "\n".join(
                [
                    'model = "gpt-5.4"',
                    'model_reasoning_effort = "medium"',
                    "experimental_use_unified_exec_tool = true",
                    "",
                    "[mcp_servers.legacy]",
                    'url = "http://127.0.0.1:8002/mcp/"',
                    "",
                    '[plugins."github@openai-curated"]',
                    "enabled = true",
                    "",
                    '[projects."/tmp/outside-workspace"]',
                    'trust_level = "trusted"',
                    "",
                    f'[projects."{repo_root / "workspaces" / "default"}"]',
                    'trust_level = "trusted"',
                    "",
                    "[features]",
                    "apps = true",
                    "plugins = true",
                    "skill_mcp_dependency_install = true",
                    "",
                    "[skills]",
                    "include_instructions = true",
                    "",
                    "[[hooks.PostToolUse]]",
                    'matcher = ".*"',
                    "",
                    "[[hooks.PostToolUse.hooks]]",
                    'type = "command"',
                    'command = "/tmp/operator-hook"',
                    "",
                    "[profiles.default]",
                    'model = "gpt-5.4"',
                    'model_reasoning_effort = "medium"',
                    "experimental_use_unified_exec_tool = true",
                    'approval_policy = "never"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (source_home / "rules").mkdir()
        (source_home / "rules" / "base.md").write_text("rules\n", encoding="utf-8")
        (source_home / "skills" / ".system").mkdir(parents=True)
        (source_home / "skills" / ".system" / "SKILL.md").write_text("---\nname: system\n---\n", encoding="utf-8")
        session = create_runtime_session(
            runtime_store,
            session_id="sess-codex-home",
            workspace_id="default",
            agent_id="agent-1",
            skill_activation_mode="explicit",
            start_path=repo_root,
        )
        stale_runtime_home = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "sess-codex-home" / "codex-home"
        (stale_runtime_home / "plugins").mkdir(parents=True)
        (stale_runtime_home / "cache" / "codex_apps_tools").mkdir(parents=True)
        (stale_runtime_home / ".tmp" / "plugins").mkdir(parents=True)
        (stale_runtime_home / ".tmp" / "plugins.sha").write_text("stale\n", encoding="utf-8")
        (stale_runtime_home / ".tmp" / "app-server-remote-plugin-sync-v1").write_text("ok\n", encoding="utf-8")

        with patch.dict(os.environ, {"MAVERICK_CODEX_HOME": str(source_home)}, clear=False):
            spec = CodexProviderAdapter(codex_command="/bin/echo").build_launch_spec(session)

        runtime_home = Path(spec.env_overrides["CODEX_HOME"])
        separator_index = spec.command.index("--")
        self.assertEqual(spec.command[separator_index + 1 : separator_index + 6], ["/bin/echo", "--disable", "apps", "--disable", "plugins"])
        self.assertEqual(runtime_home, repo_root / "workspaces" / "default" / "runtime" / "sessions" / "sess-codex-home" / "codex-home")
        self.assertEqual((runtime_home / "auth.json").read_text(encoding="utf-8"), '{"tokens": "test"}\n')
        self.assertTrue((runtime_home / "rules" / "base.md").exists())
        self.assertFalse((runtime_home / "rules").is_symlink())
        self.assertFalse((runtime_home / "skills" / ".system" / "SKILL.md").exists())
        runtime_config = (runtime_home / "config.toml").read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5.6-sol"', runtime_config)
        self.assertIn('model_reasoning_effort = "max"', runtime_config)
        self.assertNotIn('model = "gpt-5.4"', runtime_config)
        self.assertNotIn('model_reasoning_effort = "medium"', runtime_config)
        self.assertIn("experimental_use_unified_exec_tool = false", runtime_config)
        self.assertNotIn("experimental_use_unified_exec_tool = true", runtime_config)
        self.assertIn("[profiles.default]", runtime_config)
        self.assertNotIn("[mcp_servers.legacy]", runtime_config)
        self.assertNotIn("127.0.0.1:8002", runtime_config)
        self.assertNotIn("[plugins.", runtime_config)
        self.assertNotIn("github@openai-curated", runtime_config)
        self.assertNotIn("/tmp/outside-workspace", runtime_config)
        self.assertIn(f'[projects."{repo_root / "workspaces" / "default"}"]', runtime_config)
        self.assertIn("[features]", runtime_config)
        self.assertIn("apps = false", runtime_config)
        self.assertIn("hooks = true", runtime_config)
        self.assertIn("plugins = false", runtime_config)
        self.assertIn("skill_mcp_dependency_install = false", runtime_config)
        self.assertEqual(runtime_config.count("[skills]"), 1)
        self.assertIn("include_instructions = false", runtime_config)
        self.assertIn("[[hooks.PostToolUse]]", runtime_config)
        self.assertIn(CODEX_POST_TOOL_USE_HOOK_NAME, runtime_config)
        runtime_bin = Path(spec.env_overrides["PATH"].split(os.pathsep)[0])
        hook_state_key = codex_post_tool_use_hook_state_key(config_path=runtime_home / "config.toml")
        hook_trusted_hash = codex_post_tool_use_hook_trusted_hash(
            command=str(runtime_bin / CODEX_POST_TOOL_USE_HOOK_NAME)
        )
        self.assertIn(f"[hooks.state.{json.dumps(hook_state_key)}]", runtime_config)
        self.assertIn(f"trusted_hash = {json.dumps(hook_trusted_hash)}", runtime_config)
        self.assertNotIn("/tmp/operator-hook", runtime_config)
        self.assertFalse((runtime_home / "plugins").exists())
        self.assertFalse((runtime_home / "cache" / "codex_apps_tools").exists())
        self.assertFalse((runtime_home / ".tmp" / "plugins").exists())
        self.assertFalse((runtime_home / ".tmp" / "plugins.sha").exists())
        self.assertFalse((runtime_home / ".tmp" / "app-server-remote-plugin-sync-v1").exists())

    def test_existing_runtime_maverick_wrapper_is_refreshed(self) -> None:
        repo_root = self.make_repo_root()
        wrapper = repo_root / "workspaces" / "default" / "runtime" / "sessions" / "sess-stale" / "bin" / "maverick"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        legacy_create_command = "maverick app " + "create"
        wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "def parse_app_create(args):\n"
            f"    raise SystemExit('{legacy_create_command} requires app_id')\n"
            f"print('{legacy_create_command} <app_id>')\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o600)

        refreshed = refresh_workspace_maverick_wrappers(repo_root)
        content = wrapper.read_text(encoding="utf-8")

        self.assertEqual(refreshed, [wrapper])
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertIn("maverick core cli run core.app-sdk.create --app-id <app_id>", content)
        self.assertIn("response_exit_code", content)
        self.assertNotIn("parse_app_create", content)
        self.assertNotIn(legacy_create_command, content)

    def test_workspace_maverick_wrapper_exits_nonzero_for_error_status_payload(self) -> None:
        namespace: dict[str, object] = {"__name__": "wrapper_test"}
        exec(_workspace_maverick_wrapper_source(), namespace)

        response_exit_code = namespace["response_exit_code"]
        self.assertEqual(response_exit_code('{"status_code": 400, "error": "unsupported"}'), 1)  # type: ignore[operator]
        self.assertEqual(response_exit_code('{"status_code": 200}'), 0)  # type: ignore[operator]

    def test_workspace_maverick_wrapper_requests_provider_compact_by_default(self) -> None:
        namespace: dict[str, object] = {"__name__": "wrapper_test"}
        exec(_workspace_maverick_wrapper_source(), namespace)
        captured_payloads: list[dict[str, object]] = []

        class RequestStub:
            def __init__(self, _url: str, *, data: bytes, headers: dict[str, str], method: str) -> None:
                captured_payloads.append(json.loads(data.decode("utf-8")))

        namespace["runtime_auth_headers"] = lambda: {"Content-Type": "application/json", "Authorization": "Bearer token"}
        namespace["print_response"] = lambda _request, text_field=None: 0

        with patch.object(namespace["urllib"].request, "Request", RequestStub):  # type: ignore[index, union-attr]
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(namespace["call_cli"](["apps", "list", "--json"]), 0)  # type: ignore[operator]
            with patch.dict(os.environ, {"MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE": "full"}, clear=True):
                self.assertEqual(namespace["call_cli"](["apps", "list", "--json"]), 0)  # type: ignore[operator]

        self.assertEqual(captured_payloads[0]["output_profile"], "provider_compact")
        self.assertEqual(captured_payloads[1]["output_profile"], "full")

    def test_codex_runtime_home_ignores_unreadable_source_config(self) -> None:
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        source_home = repo_root / "operator-codex-home"
        source_home.mkdir()
        config_path = source_home / "config.toml"
        config_path.write_text('model = "gpt-5.4"\n', encoding="utf-8")
        config_path.chmod(0)
        self.addCleanup(lambda: config_path.chmod(0o600) if config_path.exists() else None)
        session = create_runtime_session(
            runtime_store,
            session_id="sess-unreadable-config",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )

        with patch.dict(os.environ, {"MAVERICK_CODEX_HOME": str(source_home)}, clear=False):
            spec = CodexProviderAdapter(codex_command="/bin/echo").build_launch_spec(session)

        runtime_config = (Path(spec.env_overrides["CODEX_HOME"]) / "config.toml").read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5.6-sol"', runtime_config)
        self.assertNotIn("gpt-5.4", runtime_config)

    def test_disable_binding_preserves_record_but_makes_it_inactive(self) -> None:
        provider_store = self.make_provider_store()
        binding = bind_provider_credential(
            provider_store,
            provider_id="future-hosted",
            secret_ref="platform:secret-alias/future-hosted",
        )

        disabled = disable_provider_binding(provider_store, binding.binding_id)

        self.assertEqual(disabled.status, "disabled")
        self.assertEqual(provider_store.get_provider_binding(binding.binding_id).status, "disabled")

    def test_launch_spec_receives_provider_secret_via_platform_delivery(self) -> None:
        class CredentialedAdapter:
            def provider_definition(self) -> ProviderDefinition:
                timestamp = datetime.now(tz=UTC)
                return ProviderDefinition(
                    provider_id="credentialed",
                    label="Credentialed",
                    description="Credentialed runtime backend.",
                    kind="runtime_backend",
                    status="active",
                    capabilities=ProviderCapabilitySet(
                        supports_interactive_runtime=True,
                        supports_streaming=True,
                        supports_tools=True,
                        supports_mcp=False,
                        supports_skills=False,
                        supports_filesystem_access=True,
                        supports_remote_execution=False,
                        supports_api_key_auth=True,
                        supports_local_binary=True,
                    ),
                    default_model_family="credentialed",
                    requires_credentials=True,
                    supported_execution_modes=["sandbox"],
                    created_at=timestamp,
                    updated_at=timestamp,
                )

            def validate_backend(self) -> None:
                return None

            def build_launch_spec(self, session, *, secret_env=None, credential_binding_id=None, resolved_secret_refs=None) -> RuntimeBackendLaunchSpec:
                return RuntimeBackendLaunchSpec(
                    provider_id="credentialed",
                    command=["echo"],
                    env_overrides=dict(secret_env or {}),
                    credential_binding_id=credential_binding_id,
                    resolved_secret_refs=list(resolved_secret_refs or []),
                    working_directory=session.workdir,
                    execution_mode=session.effective_mode,
                    readable_roots=[session.workspace_root],
                    writable_roots=[session.workspace_root],
                )

            def prepare_runtime_skills(self, session, skills):
                return []

        provider_store = self.make_provider_store()
        secret_store = self.make_secret_store()
        registry = ProviderRegistry()
        registry.register_runtime_adapter(CredentialedAdapter())
        bind_provider_credential(
            provider_store,
            provider_id="credentialed",
            secret_ref="platform:secret-alias/provider-secret",
            workspace_id="default",
        )
        create_platform_secret(secret_store, label="Provider Secret", raw_value="super-secret-token", alias="provider-secret")
        selection = configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="credentialed",
            registry=registry,
        )
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        bridge = registry.get_agentic_runtime_adapter("credentialed")
        policy = codex_runtime_policy()
        execution_binding = build_runtime_execution_binding(
            session_id="sess-credentialed",
            workspace_id="default",
            profile_definition_id="profile-credentialed-fixture",
            profile_definition_revision="1",
            workspace_binding_id="workspace-credentialed-fixture",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-credentialed-fixture",
            certificate_evidence_digest="a" * 64,
            runtime_engine_id="credentialed",
            adapter_id=bridge.adapter_id,
            adapter_version=bridge.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(bridge),
            model_provider_id="credentialed",
            model_id="credentialed",
            provider_protocol="legacy-runtime-backend",
            provider_api_version=None,
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=selection.binding_id,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="sandbox",
            profile_policy_ceiling=policy,
            workspace_policy_ceiling=policy,
            egress_policy_id="local-runtime-no-remote-egress",
            egress_policy_revision="1",
            created_at=datetime.now(tz=UTC),
        )
        # Isolate legacy local launch-spec secret delivery from the authoritative
        # Phase-0 remote admission barrier exercised in dedicated tests.
        with patch(
            "core.runtime.lifecycle_service_sessions.require_remote_agentic_session_admission"
        ):
            session = create_runtime_session(
                runtime_store,
                session_id="sess-credentialed",
                workspace_id="default",
                agent_id="agent-1",
                start_path=repo_root,
                execution_binding=execution_binding,
            )

        spec = build_runtime_backend_launch_spec(
            provider_store,
            session=session,
            registry=registry,
            secret_store=secret_store,
        )

        self.assertEqual(spec.env_overrides["MAVERICK_PROVIDER_SECRET"], "super-secret-token")
        self.assertIsNotNone(spec.credential_binding_id)
        self.assertEqual(spec.resolved_secret_refs, ["platform:secret-alias/provider-secret"])


if __name__ == "__main__":
    unittest.main()
