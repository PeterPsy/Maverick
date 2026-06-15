"""Tests for provider registry, binding, selection, and Codex launch specs."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.api.application import create_application
from core.providers.errors import ProviderCredentialBindingError, ProviderSelectionError
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.provider_codex import CodexProviderAdapter, refresh_workspace_maverick_wrappers
from core.providers.provider_codex_wrappers import _workspace_maverick_wrapper_source
from core.providers.provider_registry import ProviderRegistry
from core.providers.provider_selection import ProviderSelectionService
from core.providers.service import (
    build_runtime_backend_launch_spec,
    builtin_provider_registry,
    configure_workspace_provider,
    list_available_providers,
    register_builtin_providers,
    resolve_provider_for_runtime_session,
)
from core.workspaces.models import WorkspaceGovernanceRecord
from core.runtime.workspace_api_token import verify_workspace_api_token
from core.providers.store import ProviderDocumentStore, ProviderCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.secrets.service import create_platform_secret
from core.secrets.store import SecretDocumentStore, SecretCollections
from tests.support.collections import FakeCollection


class ProvidersTestCase(unittest.TestCase):
    """Verify provider registry, selection, bindings, and Codex adapter behavior."""

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

    def test_builtin_registry_registers_codex_provider(self) -> None:
        registry = builtin_provider_registry()
        definitions = registry.list_provider_definitions()

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].provider_id, "codex")
        self.assertEqual(definitions[0].kind, "runtime_backend")
        self.assertEqual(definitions[0].default_model_family, "gpt-5.5")
        self.assertTrue(definitions[0].capabilities.supports_interactive_runtime)

    def test_builtin_registry_does_not_probe_codex_model_catalog(self) -> None:
        with patch("core.providers.provider_codex_models.subprocess.run") as run:
            registry = builtin_provider_registry()
            definitions = registry.list_provider_definitions()

        self.assertEqual([definition.provider_id for definition in definitions], ["codex"])
        run.assert_not_called()

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
                codex_command="/tmp/codex-settings",
                refresh_model_catalog=True,
            )

        self.assertEqual(run.call_count, 1)
        self.assertEqual(providers[0].model_options[0].model_id, "gpt-settings")
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
        command = "/tmp/codex-refresh-bypass"

        with patch("core.providers.provider_codex_models.subprocess.run", return_value=first_result):
            CodexProviderAdapter(codex_command=command).model_options(refresh=True)
        with patch("core.providers.provider_codex_models.subprocess.run", return_value=refreshed_result) as run:
            providers = list_available_providers(
                provider_store,
                codex_command=command,
                refresh_model_catalog=True,
            )

        self.assertEqual(run.call_count, 1)
        self.assertEqual(providers[0].model_options[0].model_id, "gpt-refreshed")
        self.assertEqual(provider_store.get_provider_definition("codex").model_options[0].model_id, "gpt-refreshed")

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

        self.assertEqual([option.model_id for option in first], ["gpt-5.5"])
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

        with self.assertRaisesRegex(ProviderSelectionError, "no_provider_configured"):
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

    def test_bindings_store_secret_refs_without_raw_secret_values(self) -> None:
        provider_store = self.make_provider_store()
        binding = bind_provider_credential(
            provider_store,
            provider_id="openai-compatible",
            secret_ref="platform:providers/openai-compatible",
            workspace_id="default",
            label="default llm key",
        )

        self.assertEqual(binding.secret_ref, "platform:providers/openai-compatible")
        self.assertEqual(binding.label, "default llm key")
        self.assertFalse(hasattr(binding, "api_key"))

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

    def test_codex_launch_spec_is_built_from_provider_adapter_not_runtime_domain(self) -> None:
        provider_store = self.make_provider_store()
        register_builtin_providers(provider_store)
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        now = datetime.now(tz=UTC)
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            now=now,
            start_path=repo_root,
        )
        configure_workspace_provider(provider_store, workspace_id="acme", provider_id="codex", codex_command="/bin/echo")

        launch_spec = build_runtime_backend_launch_spec(provider_store, session=session, codex_command="/bin/echo")

        self.assertEqual(launch_spec.provider_id, "codex")
        self.assertEqual(launch_spec.command[:2], [os.sys.executable, str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1" / "bin" / "workspace_sandbox.py")])
        self.assertIn("--workspace-root", launch_spec.command)
        self.assertIn(str(repo_root / "workspaces" / "acme"), launch_spec.command)
        self.assertIn("--runtime-root", launch_spec.command)
        self.assertIn(str(repo_root / "workspaces" / "acme" / "runtime" / "sessions" / "sess-1"), launch_spec.command)
        separator_index = launch_spec.command.index("--")
        self.assertEqual(
            launch_spec.command[separator_index + 1 : separator_index + 6],
            ["/bin/echo", "--disable", "apps", "--disable", "plugins"],
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
        self.assertTrue((runtime_bin / "workspace_sandbox.py").is_file())
        self.assertEqual(launch_spec.env_overrides["PATH"].split(os.pathsep)[0], str(runtime_bin))
        self.assertEqual(launch_spec.env_overrides["MAVERICK_RUNTIME_BIN"], str(runtime_bin))
        runtime_config = (Path(launch_spec.env_overrides["CODEX_HOME"]) / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[shell_environment_policy.set]", runtime_config)
        self.assertIn(f'PATH = "{launch_spec.env_overrides["PATH"]}"', runtime_config)
        self.assertIn(f"MAVERICK_RUNTIME_BIN = \"{runtime_bin}\"", runtime_config)
        self.assertIn(f"MAVERICK_RUNTIME_ROOT = \"{runtime_bin.parent}\"", runtime_config)
        self.assertIn(f"MAVERICK_WORKSPACE_ROOT = \"{repo_root / 'workspaces' / 'acme'}\"", runtime_config)
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
                        execution_mode="sandbox",
                    )

        self.assertEqual(roots, [standalone.parent])
        self.assertEqual(runtime_command, str(standalone))
        self.assertIn("--dependency-file", sandbox_command)
        self.assertIn(f"{standalone}={home / 'workspace' / 'runtime' / 'bin' / 'codex'}", sandbox_command)
        self.assertIn(f"{rg}={home / 'workspace' / 'runtime' / 'bin' / 'rg'}", sandbox_command)
        separator_index = sandbox_command.index("--")
        self.assertEqual(sandbox_command[separator_index + 1], str(home / "workspace" / "runtime" / "bin" / "codex"))

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
                    "[profiles.default]",
                    'model = "gpt-5.4"',
                    'model_reasoning_effort = "medium"',
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
        self.assertIn('model = "gpt-5.5"', runtime_config)
        self.assertIn('model_reasoning_effort = "high"', runtime_config)
        self.assertNotIn('model = "gpt-5.4"', runtime_config)
        self.assertNotIn('model_reasoning_effort = "medium"', runtime_config)
        self.assertIn("[profiles.default]", runtime_config)
        self.assertNotIn("[mcp_servers.legacy]", runtime_config)
        self.assertNotIn("127.0.0.1:8002", runtime_config)
        self.assertNotIn("[plugins.", runtime_config)
        self.assertNotIn("github@openai-curated", runtime_config)
        self.assertNotIn("/tmp/outside-workspace", runtime_config)
        self.assertIn(f'[projects."{repo_root / "workspaces" / "default"}"]', runtime_config)
        self.assertIn("[features]", runtime_config)
        self.assertIn("apps = false", runtime_config)
        self.assertIn("plugins = false", runtime_config)
        self.assertIn("skill_mcp_dependency_install = false", runtime_config)
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
        self.assertIn('model = "gpt-5.5"', runtime_config)
        self.assertNotIn("gpt-5.4", runtime_config)

    def test_disable_binding_preserves_record_but_makes_it_inactive(self) -> None:
        provider_store = self.make_provider_store()
        binding = bind_provider_credential(
            provider_store,
            provider_id="future-hosted",
            secret_ref="platform:providers/future-hosted",
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
        configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="credentialed",
            registry=registry,
        )
        runtime_store = self.make_runtime_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-credentialed",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
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
