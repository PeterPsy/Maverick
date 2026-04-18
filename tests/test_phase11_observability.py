"""Tests for finishing Phase 10 hooks and Phase 11 observability/logs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.api.application import create_application
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool
from core.observability.service import ensure_observability_roots
from core.observability.store import MongoObservabilityStore, ObservabilityCollections
from core.observability.audit_log import record_audit_event
from core.observability.event_log import emit_structured_event
from core.observability.metrics import record_metric
from core.observability.runtime_log import append_runtime_log, apply_retention
from core.providers.service import register_builtin_providers
from core.providers.store import MongoProviderStore, ProviderCollections
from core.recovery.service import record_failed_start
from core.recovery.store import MongoRecoveryStore, RecoveryCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.secrets.service import bind_workspace_secret, build_secret_ref, create_platform_secret
from core.secrets.store import MongoSecretStore, SecretCollections
from core.workspaces.files import build_export_manifest
from core.workspaces.service import ensure_default_workspace, ensure_default_workspace_record
from core.workspaces.store import MongoWorkspaceStore, WorkspaceCollections


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


class Phase11ObservabilityTestCase(unittest.TestCase):
    """Verify phase-10 hooks and phase-11 observability behavior."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "local-skills", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        return repo_root

    def make_workspace_store(self) -> MongoWorkspaceStore:
        return MongoWorkspaceStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
            )
        )

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

    def make_recovery_store(self) -> MongoRecoveryStore:
        return MongoRecoveryStore(
            RecoveryCollections(
                failures=FakeCollection(),
                intents=FakeCollection(),
                health_results=FakeCollection(),
            )
        )

    def make_observability_store(self) -> MongoObservabilityStore:
        return MongoObservabilityStore(
            ObservabilityCollections(
                events=FakeCollection(),
                audit=FakeCollection(),
                metrics=FakeCollection(),
            )
        )

    def test_application_bootstrap_creates_installation_log_roots(self) -> None:
        repo_root = self.make_repo_root()

        application = create_application(start_path=repo_root)

        self.assertEqual(application["status"], "initialized")
        self.assertTrue((repo_root / "logs" / "platform").is_dir())
        self.assertTrue((repo_root / "logs" / "runtime").is_dir())

    def test_cli_and_mcp_secret_surfaces_never_return_raw_values(self) -> None:
        repo_root = self.make_repo_root()
        secret_store = self.make_secret_store()
        secret = create_platform_secret(secret_store, label="OpenAI", raw_value="sk-top-secret", alias="default-openai")
        bind_workspace_secret(secret_store, workspace_id="default", logical_name="openai", secret_ref=build_secret_ref(alias=secret.alias))

        cli_context = CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        cli_result = run_core_cli_command(
            command_id="core.secrets.list",
            context=cli_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(cli_result["secrets"][0]["secret_id"], secret.secret_id)
        self.assertNotIn("raw_value", cli_result["secrets"][0])

        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        mcp_result = call_mcp_tool(
            tool_name="core.secrets.list",
            context=mcp_context,
            secret_store=secret_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(mcp_result["items"][0]["secret_id"], secret.secret_id)
        self.assertNotIn("raw_value", mcp_result["items"][0])

    def test_cli_and_mcp_recovery_hooks_plan_and_inspect_without_main_backend_dependency(self) -> None:
        repo_root = self.make_repo_root()
        runtime_store = self.make_runtime_store()
        recovery_store = self.make_recovery_store()
        session = create_runtime_session(
            runtime_store,
            session_id="sess-1",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
        )
        record_failed_start(
            recovery_store,
            category="missing_secret",
            detail="provider secret missing",
            workspace_id="default",
            session_id="sess-1",
        )

        cli_context = CliInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        restart_result = run_core_cli_command(
            command_id="core.recovery.restart",
            context=cli_context,
            arguments={"session_id": session.session_id, "reason": "operator requested"},
            runtime_store=runtime_store,
            recovery_store=recovery_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertTrue(restart_result["planned"])

        mcp_context = McpInvocationContext(caller_kind="operator", workspace_id="default", agent_id=None, effective_mode="full-access")
        status_result = call_mcp_tool(
            tool_name="core.recovery.status",
            context=mcp_context,
            recovery_store=recovery_store,
            runtime_store=runtime_store,
            workspace_id="default",
            start_path=repo_root,
        )
        self.assertEqual(status_result["status"]["failure_count"], 1)
        self.assertEqual(status_result["status"]["latest_intent_action"], "restart_runtime")

    def test_observability_store_records_redacted_event_audit_and_metrics(self) -> None:
        store = self.make_observability_store()

        event = emit_structured_event(
            store,
            event_type="secret.resolution",
            event_plane="platform",
            source_domain="secrets",
            workspace_id="default",
            payload={"secret_ref": "platform:secrets/openai", "result": "ok"},
        )
        audit = record_audit_event(
            store,
            action="secret.rotate",
            status="succeeded",
            source_domain="secrets",
            detail="operator rotated secret",
            workspace_id="default",
            payload={"raw_value": "sk-secret", "secret_id": "openai"},
        )
        metric = record_metric(
            store,
            metric_name="recovery.intent.count",
            kind="counter",
            value=1,
            workspace_id="default",
            tags={"source_domain": "recovery"},
        )

        self.assertEqual(event.payload["secret_ref"], "<redacted>")
        self.assertEqual(audit.payload["raw_value"], "<redacted>")
        self.assertEqual(metric.metric_name, "recovery.intent.count")
        self.assertEqual(len(store.list_events(workspace_id="default")), 1)
        self.assertEqual(len(store.list_audit(workspace_id="default")), 1)
        self.assertEqual(len(store.list_metrics(workspace_id="default")), 1)

    def test_runtime_log_roots_and_retention_are_applied(self) -> None:
        repo_root = self.make_repo_root()
        roots = ensure_observability_roots(workspace_id="default", app_id="chat", start_path=repo_root)
        self.assertTrue(roots["platform"].is_dir())
        self.assertTrue(roots["runtime"].is_dir())
        self.assertTrue(roots["workspace"].is_dir())
        self.assertTrue(roots["app"].is_dir())

        for index in range(22):
            stale = roots["platform"] / f"platform-old-{index:02d}.jsonl"
            stale.write_text("{}", encoding="utf-8")
        apply_retention(log_root=roots["platform"], max_files=20)
        self.assertLessEqual(len(list(roots["platform"].iterdir())), 20)

        record = append_runtime_log(
            log_plane="app",
            workspace_id="default",
            app_id="chat",
            runtime_session_id="sess-1",
            provider_id="codex",
            message="runtime env prepared",
            payload={"api_key": "secret", "workspace_id": "default"},
            start_path=repo_root,
        )
        self.assertIn("/workspaces/default/logs/apps/chat/", record.log_path)
        log_content = Path(record.log_path).read_text(encoding="utf-8")
        self.assertIn("<redacted>", log_content)
        self.assertNotIn("secret", log_content)

    def test_workspace_export_manifest_excludes_logs_by_default(self) -> None:
        repo_root = self.make_repo_root()
        workspace_paths = ensure_default_workspace(start_path=repo_root)
        data_file = workspace_paths.data / "chat" / "db.sqlite"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_text("db", encoding="utf-8")
        log_file = workspace_paths.logs / "workspace" / "workspace-20260418.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("{}", encoding="utf-8")

        manifest = build_export_manifest(
            "default",
            workspace_paths.root,
            [data_file, log_file],
        )

        self.assertEqual([item.relative_path for item in manifest.files], ["data/chat/db.sqlite"])
