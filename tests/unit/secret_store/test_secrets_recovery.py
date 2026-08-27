"""Tests for secrets and recovery foundations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.apps.contracts import build_app_contract, build_app_entrypoints, build_app_health_contract, build_app_lifecycle, build_parsed_app_contract, write_app_contract_file
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_registry import ProviderRegistry
from core.recovery.health_checks import run_provider_health_check
from core.recovery.service import plan_session_restart, record_app_health, record_failed_start, record_runtime_health, recovery_status
from core.recovery.store import RecoveryDocumentStore, RecoveryCollections
from core.observability.store import ObservabilityCollections, ObservabilityDocumentStore
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.secrets.errors import SecretBindingError, SecretPolicyError
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.service import (
    bind_app_secret,
    bind_provider_secret,
    bind_workspace_secret,
    build_secret_ref,
    create_platform_secret,
    disable_platform_secret,
    grant_app_secret_use,
    resolve_app_secret_grant,
    resolve_app_secret,
    resolve_provider_secret,
    resolve_workspace_secret,
    revoke_platform_secret,
)
from core.secrets.store import SecretDocumentStore, SecretCollections
from core.secrets.target_policy import normalize_target_patterns, normalize_target_patterns_or_wildcard
from tests.support.collections import FakeCollection


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


class SecretsRecoveryTestCase(unittest.TestCase):
    """Verify secrets and recovery foundation behavior."""

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            )
        )

    def make_recovery_store(self) -> RecoveryDocumentStore:
        return RecoveryDocumentStore(
            RecoveryCollections(
                failures=FakeCollection(),
                intents=FakeCollection(),
                health_results=FakeCollection(),
            )
        )

    def make_observability_store(self) -> ObservabilityDocumentStore:
        return ObservabilityDocumentStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=FakeCollection(),
                metrics=FakeCollection(),
            )
        )

    def make_app_store(self) -> AppDocumentStore:
        return AppDocumentStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
                workspace_app_dependency_selections=FakeCollection(),
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
        stored_value = store.collections.values.find_one({"secret_id": record.secret_id})
        assert stored_value is not None
        self.assertNotIn("raw_value", stored_value)
        self.assertNotEqual(stored_value["value_ciphertext"], "sk-test-secret")
        self.assertEqual(stored_value["value_format"], "mvr3secret2-aesgcm")
        self.assertIn("value_key_id", stored_value)

    def test_create_secret_rejects_id_and_alias_collisions(self) -> None:
        store = self.make_secret_store()
        create_platform_secret(store, label="Same Name", raw_value="first-secret", alias="shared-alias")

        with self.assertRaisesRegex(SecretBindingError, "Secret id `same-name` already exists"):
            create_platform_secret(store, label="Same Name", raw_value="second-secret")
        with self.assertRaisesRegex(SecretBindingError, "Secret alias `shared-alias` is already assigned"):
            create_platform_secret(store, label="Different Name", raw_value="second-secret", alias="shared-alias")
        with self.assertRaisesRegex(SecretBindingError, "collides with alias"):
            create_platform_secret(store, label="Shared Alias", raw_value="second-secret")
        with self.assertRaisesRegex(SecretBindingError, "collides with existing secret id"):
            create_platform_secret(store, label="Different Name", raw_value="second-secret", alias="same-name")

        self.assertEqual(len(store.list_secrets()), 1)
        self.assertEqual(store.get_secret_value(secret_id="same-name"), "first-secret")

    def test_secret_store_key_can_be_loaded_from_protected_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            key_file = Path(temp_dir) / "secret-store.key"
            key_file.write_text("file-backed-key\n", encoding="utf-8")
            key_file.chmod(0o400)
            store = self.make_secret_store()

            with patch.dict("os.environ", {"MAVERICK_SECRET_KEY_FILE": str(key_file)}, clear=True):
                record = create_platform_secret(store, label="File Key", raw_value="file-secret", alias="file-key")
                self.assertEqual(store.get_secret_value(secret_id=record.secret_id), "file-secret")

            stored_value = store.collections.values.find_one({"secret_id": record.secret_id})
            assert stored_value is not None
            self.assertNotIn("file-secret", str(stored_value))

    def test_workspace_app_and_provider_secret_bindings_resolve_only_in_scope(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Workspace Key", raw_value="super-secret", alias="workspace-key")
        secret_ref = build_secret_ref(alias=secret.alias)

        workspace_binding = bind_workspace_secret(store, workspace_id="acme", logical_name="openai", secret_ref=secret_ref)
        app_binding = bind_app_secret(store, workspace_id="acme", app_id="sample-app", logical_name="api-key", secret_ref=secret_ref)
        provider_binding = bind_provider_secret(store, provider_id="codex", workspace_id="acme", logical_name="default", secret_ref=secret_ref)

        workspace_lease = resolve_workspace_secret(store, workspace_id="acme", logical_name="openai", runtime_session_id="sess-1")
        app_lease = resolve_app_secret(store, workspace_id="acme", app_id="sample-app", logical_name="api-key", runtime_session_id="sess-1")
        provider_lease = resolve_provider_secret(store, provider_id="codex", workspace_id="acme", runtime_session_id="sess-1")

        self.assertEqual(workspace_lease.source_binding_id, workspace_binding.binding_id)
        self.assertEqual(app_lease.source_binding_id, app_binding.binding_id)
        self.assertEqual(provider_lease.source_binding_id, provider_binding.binding_id)
        self.assertTrue(workspace_lease.redacted_value.startswith("su"))

        with self.assertRaises(SecretPolicyError):
            resolve_secret_for_runtime(
                store,
                context=SecretResolutionContext(workspace_id="other", app_id="sample-app"),
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

        app_root = repo_root / "apps" / "sample-app"
        lifecycle_root = app_root / "backend" / "lifecycle"
        lifecycle_root.mkdir(parents=True, exist_ok=True)
        (lifecycle_root / "health.py").write_text('print(\'{"status":"healthy","ok":true}\')\n', encoding="utf-8")
        write_app_contract_file(
            app_root,
            build_parsed_app_contract(
                app_id="sample-app",
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
            app_id="sample-app",
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

    def test_app_secret_grants_allow_action_scoped_use_only(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Example Login", raw_value="browser-password", alias="example-login", kind="password")
        grant = grant_app_secret_use(
            store,
            workspace_id="acme",
            app_id="browser",
            logical_name="login",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
            created_by_user_id="admin",
            reason="Allow Browser autofill on example.com.",
        )

        lease = resolve_app_secret_grant(
            store,
            workspace_id="acme",
            app_id="browser",
            grant_id=grant.grant_id,
            action="browser.autofill",
            target="https://example.com/login?token=not-audit-safe",
        )

        self.assertEqual(lease.value, "browser-password")
        self.assertEqual(lease.source_grant_id, grant.grant_id)
        with self.assertRaises(SecretPolicyError):
            resolve_app_secret_grant(
                store,
                workspace_id="acme",
                app_id="browser",
                grant_id=grant.grant_id,
                action="browser.autofill",
                target="https://evil.example/login?token=not-audit-safe",
            )
        with self.assertRaises(SecretPolicyError):
            resolve_app_secret_grant(
                store,
                workspace_id="acme",
                app_id="crm",
                grant_id=grant.grant_id,
                action="browser.autofill",
                target="https://example.com/login",
            )

    def test_disable_secret_revokes_linked_grants_in_service_layer(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Example Login", raw_value="browser-password", alias="example-login")
        grant = grant_app_secret_use(
            store,
            workspace_id="acme",
            app_id="browser",
            logical_name="login",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
        )

        disabled = disable_platform_secret(store, secret_id=secret.secret_id)

        self.assertEqual(disabled.status, "disabled")
        self.assertEqual(store.get_secret_grant(grant.grant_id).status, "revoked")

    def test_mixed_action_grants_reject_wildcard_targets(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Mixed", raw_value="mixed-secret", alias="mixed")

        with self.assertRaises(SecretBindingError):
            grant_app_secret_use(
                store,
                workspace_id="acme",
                app_id="browser",
                logical_name="login",
                secret_ref=build_secret_ref(alias=secret.alias),
                actions=["app.backend", "browser.autofill"],
                target_patterns=["*"],
            )

    def test_non_internal_grants_require_explicit_targets(self) -> None:
        store = self.make_secret_store()
        secret = create_platform_secret(store, label="Autofill", raw_value="autofill-secret", alias="autofill")

        with self.assertRaises(SecretBindingError):
            grant_app_secret_use(
                store,
                workspace_id="acme",
                app_id="browser",
                logical_name="login",
                secret_ref=build_secret_ref(alias=secret.alias),
                actions=["browser.autofill"],
                target_patterns=[],
            )

    def test_target_normalization_requires_deliberate_wildcard_default(self) -> None:
        self.assertEqual(normalize_target_patterns(None), [])
        self.assertEqual(normalize_target_patterns([]), [])
        self.assertEqual(normalize_target_patterns_or_wildcard([]), ["*"])

    def test_secret_resolution_audits_success_and_denial_without_raw_value(self) -> None:
        store = self.make_secret_store()
        observability_store = self.make_observability_store()
        secret = create_platform_secret(store, label="Audited", raw_value="audit-secret", alias="audited")
        grant = grant_app_secret_use(
            store,
            workspace_id="acme",
            app_id="browser",
            logical_name="login",
            secret_ref=build_secret_ref(alias=secret.alias),
            actions=["browser.autofill"],
            target_patterns=["https://example.com/*"],
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=5),
        )

        resolve_app_secret_grant(
            store,
            workspace_id="acme",
            app_id="browser",
            grant_id=grant.grant_id,
            action="browser.autofill",
            target="https://example.com/login",
            observability_store=observability_store,
        )
        with self.assertRaises(SecretPolicyError):
            resolve_app_secret_grant(
                store,
                workspace_id="acme",
                app_id="browser",
                grant_id=grant.grant_id,
                action="browser.autofill",
                target="https://other.example/login?token=not-audit-safe",
                request_context={
                    "surface": "backend",
                    "route_path": "/api/" + ("x" * 220),
                    "raw_payload": "should-not-persist",
                },
                observability_store=observability_store,
            )

        audit_records = observability_store.list_audit(workspace_id="acme", source_domain="secrets")
        self.assertEqual([item.status for item in audit_records], ["succeeded", "failed"])
        encoded = str([item.payload for item in audit_records])
        self.assertNotIn("audit-secret", encoded)
        self.assertNotIn("?", encoded)
        self.assertNotIn("not-audit-safe", encoded)
        self.assertNotIn("should-not-persist", encoded)
        self.assertNotIn("raw_payload", encoded)
        self.assertEqual(audit_records[-1].payload["request_context"]["surface"], "backend")
        self.assertLessEqual(len(audit_records[-1].payload["request_context"]["route_path"]), 163)
