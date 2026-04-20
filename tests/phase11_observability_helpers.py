"""Tests for finishing Phase 10 hooks and Phase 11 observability/logs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.api.application import create_application
from core.apps.contracts import build_app_capabilities, build_app_contract, build_parsed_app_contract, write_app_contract_file
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppCollections, MongoAppStore
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
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_credentials import bind_provider_credential
from core.providers.provider_registry import ProviderRegistry
from core.providers.service import build_runtime_backend_launch_spec, configure_workspace_provider, register_builtin_providers
from core.providers.store import MongoProviderStore, ProviderCollections
from core.recovery.service import record_failed_start
from core.recovery.store import MongoRecoveryStore, RecoveryCollections
from core.runtime.service import create_runtime_session, transition_runtime_session
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


class Phase11ObservabilityBase(unittest.TestCase):
    """Shared fixtures for tests/test_phase11_observability.py."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
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
