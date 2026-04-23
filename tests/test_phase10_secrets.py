"""Tests for Phase 10 secrets and recovery foundations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest

from core.apps.contracts import build_app_contract, build_app_entrypoints, build_app_health_contract, build_app_lifecycle, build_parsed_app_contract, write_app_contract_file
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppCollections, MongoAppStore
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_registry import ProviderRegistry
from core.recovery.health_checks import run_provider_health_check
from core.recovery.service import plan_session_restart, record_app_health, record_failed_start, record_runtime_health, recovery_status
from core.recovery.store import MongoRecoveryStore, RecoveryCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.secrets.errors import SecretBindingError, SecretPolicyError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.service import (
    bind_app_secret,
    bind_provider_secret,
    bind_workspace_secret,
    build_secret_ref,
    create_platform_secret,
    resolve_app_secret,
    resolve_provider_secret,
    resolve_workspace_secret,
    revoke_platform_secret,
)
from core.secrets.store import MongoSecretStore, SecretCollections


class FakeCollection:
    """Small in-memory collection for store tests."""

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

    def delete_one(self, query: dict) -> None:
        self.documents = [document for document in self.documents if not all(document.get(key) == value for key, value in query.items())]


class BrokenAdapter:
    """Fake provider adapter that fails backend validation."""

    def provider_definition(self) -> ProviderDefinition:
        timestamp = datetime.now(tz=UTC)
        return ProviderDefinition(
            provider_id="broken-provider",
            label="Broken Provider",
            description="Broken test adapter.",
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
                supports_api_key_auth=False,
                supports_local_binary=True,
            ),
            default_model_family="broken",
            requires_credentials=False,
            supported_execution_modes=["sandbox"],
            created_at=timestamp,
            updated_at=timestamp,
        )

    def validate_backend(self) -> None:
        raise RuntimeError("backend unavailable")

    def build_launch_spec(self, session, *, secret_env=None, credential_binding_id=None, resolved_secret_refs=None) -> RuntimeBackendLaunchSpec:  # pragma: no cover
        raise NotImplementedError

    def prepare_runtime_skills(self, session, skills):  # pragma: no cover
        raise NotImplementedError


class Phase10SecretsAndRecoveryTestCase(unittest.TestCase):
    """Verify secrets and recovery foundation behavior."""

    def make_secret_store(self) -> MongoSecretStore:
        return MongoSecretStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
            )
        )

    def make_recovery_store(self) -> MongoRecoveryStore:
        return MongoRecoveryStore(
            RecoveryCollections(
                failures=FakeCollection(),
                intents=FakeCollection(),
                health_results=FakeCollection(),
            )
        )

    def make_app_store(self) -> MongoAppStore:
        return MongoAppStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
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

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "docs", "scripts"):
            target = repo_root / name
            if name == "docs":
                (target / "architecture").mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def test_secret_records_keep_raw_values_out_of_metadata(self) -> None:
        store = self.make_secret_store()

        record = create_platform_secret(
            store,
            label="OpenAI Primary",
            raw_value="sk-test-secret",
            alias="default-openai",
        )

        fetched = store.get_secret(record.secret_id)
        self.assertEqual(fetched.alias, "default-openai")
        self.assertFalse(hasattr(fetched, "raw_value"))
        self.assertEqual(store.get_secret_value(secret_id=record.secret_id), "sk-test-secret")

    def test_workspace_app_and_provider_secret_bindings_resolve_only_in_scope(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Workspace Key", raw_value="super-secret", alias="workspace-key")
        secret_ref = build_secret_ref(alias=secret.alias)

        workspace_binding = bind_workspace_secret(store, workspace_id="acme", logical_name="openai", secret_ref=secret_ref)
        app_binding = bind_app_secret(store, workspace_id="acme", app_id="chat", logical_name="api-key", secret_ref=secret_ref)
        provider_binding = bind_provider_secret(store, provider_id="codex", workspace_id="acme", logical_name="default", secret_ref=secret_ref)

        workspace_lease = resolve_workspace_secret(store, workspace_id="acme", logical_name="openai", runtime_session_id="sess-1")
        app_lease = resolve_app_secret(store, workspace_id="acme", app_id="chat", logical_name="api-key", runtime_session_id="sess-1")
        provider_lease = resolve_provider_secret(store, provider_id="codex", workspace_id="acme", runtime_session_id="sess-1")

        self.assertEqual(workspace_lease.source_binding_id, workspace_binding.binding_id)
        self.assertEqual(app_lease.source_binding_id, app_binding.binding_id)
        self.assertEqual(provider_lease.source_binding_id, provider_binding.binding_id)
        self.assertTrue(workspace_lease.redacted_value.startswith("su"))

        with self.assertRaises(SecretPolicyError):
            resolve_secret_for_runtime(
                store,
                context=SecretResolutionContext(workspace_id="other", app_id="chat"),
                binding_id=app_binding.binding_id,
            )

    def test_direct_secret_refs_require_operator_approval(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Operator Key", raw_value="alpha-secret", alias="operator-key")
        secret_ref = build_secret_ref(secret_id=secret.secret_id)

        with self.assertRaises(SecretPolicyError):
            resolve_secret_for_runtime(
                store,
                context=SecretResolutionContext(workspace_id="default"),
                secret_ref=secret_ref,
            )

        lease = resolve_secret_for_runtime(
            store,
            context=SecretResolutionContext(workspace_id="default", operator_request=True, allow_unbound_secret_refs=True),
            secret_ref=secret_ref,
        )
        self.assertEqual(lease.secret_id, secret.secret_id)

    def test_revoke_secret_removes_stored_raw_value(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Revoked", raw_value="to-be-revoked", alias="revoked-secret")

        revoked = revoke_platform_secret(store, secret_id=secret.secret_id)

        self.assertEqual(revoked.status, "revoked")
        with self.assertRaises(SecretPolicyError):
            resolve_secret_for_runtime(
                store,
                context=SecretResolutionContext(workspace_id="default", operator_request=True, allow_unbound_secret_refs=True),
                secret_ref=build_secret_ref(secret_id=secret.secret_id),
            )

    def test_failed_start_recovery_distinguishes_repair_first_from_restartable(self) -> None:
        store = self.make_recovery_store()

        missing_secret_failure, missing_secret_intent = record_failed_start(
            store,
            category="missing_secret",
            detail="Provider secret binding is missing.",
            workspace_id="acme",
            session_id="sess-1",
        )
        crash_failure, crash_intent = record_failed_start(
            store,
            category="process_crash",
            detail="Runtime subprocess crashed.",
            workspace_id="acme",
            session_id="sess-2",
        )

        self.assertEqual(missing_secret_failure.recoverability, "repair_first")
        self.assertEqual(missing_secret_intent.action, "repair_then_restart")
        self.assertEqual(crash_failure.recoverability, "restartable")
        self.assertEqual(crash_intent.action, "restart_runtime")

    def test_recovery_health_checks_and_status_snapshot(self) -> None:
        recovery_store = self.make_recovery_store()
        runtime_store = self.make_runtime_store()
        app_store = self.make_app_store()
        repo_root = self.make_repo_root()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="acme",
            agent_id="agent-1",
            start_path=repo_root,
        )

        runtime_health = record_runtime_health(recovery_store, session=session)
        self.assertEqual(runtime_health.status, "degraded")

        restart_intent = plan_session_restart(recovery_store, session=session, reason="operator restart")
        self.assertEqual(restart_intent.action, "restart_runtime")

        app_root = repo_root / "apps" / "chat"
        lifecycle_root = app_root / "backend" / "lifecycle"
        lifecycle_root.mkdir(parents=True, exist_ok=True)
        (lifecycle_root / "health.py").write_text("print('ok')\n", encoding="utf-8")
        write_app_contract_file(
            app_root,
            build_parsed_app_contract(
                app_id="chat",
                name="Chat",
                version="1.0.0",
                description="Chat app",
                publisher="maverick",
                contract=build_app_contract(
                    lifecycle=build_app_lifecycle(health_check=True),
                    entrypoints=build_app_entrypoints(hooks={"health_check": "backend/lifecycle/health.py"}),
                    health_contract=build_app_health_contract(mode="hook"),
                ),
            ),
        )
        source = register_app_source_from_contract(app_store, source_kind="platform", source_path=str(app_root))
        install_store_app(app_store, source_id=source.source_id, workspace_id="acme", start_path=repo_root)

        app_health = record_app_health(
            recovery_store,
            app_store=app_store,
            workspace_id="acme",
            app_id="chat",
            start_path=repo_root,
        )
        self.assertEqual(app_health.status, "healthy")

        snapshot = recovery_status(recovery_store, workspace_id="acme")
        self.assertEqual(snapshot["intent_count"], 1)
        self.assertEqual(snapshot["health_check_count"], 2)
        self.assertEqual(snapshot["latest_intent_action"], "restart_runtime")

    def test_provider_health_check_reports_backend_failures(self) -> None:
        registry = ProviderRegistry()
        registry.register_runtime_adapter(BrokenAdapter())

        result = run_provider_health_check(registry, provider_id="broken-provider", workspace_id="default")

        self.assertEqual(result.status, "unhealthy")
        self.assertIn("backend unavailable", result.detail)

    def test_secret_binding_requires_canonical_secret_ref(self) -> None:
        store = self.make_secret_store()
        with self.assertRaises(SecretBindingError):
            bind_workspace_secret(
                store,
                workspace_id="acme",
                logical_name="openai",
                secret_ref="not-a-secret-ref",
            )
