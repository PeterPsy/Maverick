"""Tests for Phase 7 provider registry, binding, selection, and Codex launch specs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from core.api.application import create_application
from core.providers.errors import ProviderCredentialBindingError
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_credentials import bind_provider_credential, disable_provider_binding
from core.providers.provider_registry import ProviderRegistry
from core.providers.provider_selection import ProviderSelectionService
from core.providers.service import (
    build_runtime_backend_launch_spec,
    builtin_provider_registry,
    configure_workspace_provider,
    register_builtin_providers,
    resolve_provider_for_runtime_session,
)
from core.providers.store import MongoProviderStore, ProviderCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.secrets.service import create_platform_secret
from core.secrets.store import MongoSecretStore, SecretCollections


class FakeCollection:
    """Small in-memory collection for provider and runtime store tests."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    def find(self, query: dict) -> list[dict]:
        return [dict(document) for document in self.documents if all(document.get(key) == value for key, value in query.items())]

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents[index] = {**document, **payload}
                return
        if upsert:
            self.documents.append({**query, **payload})


class Phase7ProvidersTestCase(unittest.TestCase):
    """Verify provider registry, selection, bindings, and Codex adapter behavior."""

    def make_provider_store(self) -> MongoProviderStore:
        return MongoProviderStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )

    def make_runtime_store(self) -> MongoRuntimeStore:
        return MongoRuntimeStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
            )
        )

    def make_secret_store(self) -> MongoSecretStore:
        return MongoSecretStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
            )
        )

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "docs", "local-skills", "scripts"):
            target = repo_root / name
            if name == "docs":
                (target / "architecture").mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        return repo_root

    def test_builtin_registry_registers_codex_provider(self) -> None:
        registry = builtin_provider_registry()
        definitions = registry.list_provider_definitions()

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].provider_id, "codex")
        self.assertEqual(definitions[0].kind, "runtime_backend")
        self.assertTrue(definitions[0].capabilities.supports_interactive_runtime)

    def test_application_bootstrap_registers_builtin_providers(self) -> None:
        provider_store = self.make_provider_store()
        repo_root = self.make_repo_root()

        application = create_application(start_path=repo_root, provider_store=provider_store)

        self.assertEqual(application["status"], "initialized")
        self.assertEqual(provider_store.get_provider_definition("codex").label, "Codex")

    def test_workspace_selection_defaults_to_codex_runtime_backend(self) -> None:
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

        definition, selection = resolve_provider_for_runtime_session(provider_store, session=session)

        self.assertEqual(definition.provider_id, "codex")
        self.assertIsNone(selection)

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

        launch_spec = build_runtime_backend_launch_spec(provider_store, session=session, codex_command="/bin/echo")

        self.assertEqual(launch_spec.provider_id, "codex")
        self.assertEqual(launch_spec.command[:4], ["/bin/echo", "--enable", "use_legacy_landlock", "app-server"])
        self.assertEqual(launch_spec.execution_mode, "sandbox")
        self.assertEqual(launch_spec.working_directory, str(repo_root / "workspaces" / "acme"))
        self.assertEqual(launch_spec.writable_roots, [str(repo_root / "workspaces" / "acme")])
        self.assertIn("CODEX_HOME", launch_spec.env_overrides)
        self.assertEqual(launch_spec.env_overrides["MAVERICK_WORKSPACE_ROOT"], str(repo_root / "workspaces" / "acme"))
        self.assertEqual(launch_spec.env_overrides["TMPDIR"], str(repo_root / "workspaces" / "acme" / "runtime"))
        self.assertTrue((Path(launch_spec.env_overrides["CODEX_HOME"])).is_dir())

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
