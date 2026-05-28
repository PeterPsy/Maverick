"""Shared helpers for observability and log tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from core.api.application import create_application
from core.apps.contracts import build_app_capabilities, build_app_contract, build_parsed_app_contract, write_app_contract_file
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool
from core.observability.service import ensure_observability_roots
from core.observability.store import ObservabilityDocumentStore, ObservabilityCollections
from core.observability.audit_log import record_audit_event
from core.observability.event_log import emit_structured_event
from core.observability.metrics import record_metric
from core.observability.runtime_log import append_runtime_log, apply_retention
from core.providers.models import ProviderCapabilitySet, ProviderDefinition, RuntimeBackendLaunchSpec
from core.providers.provider_credentials import bind_provider_credential
from core.providers.provider_registry import ProviderRegistry
from core.providers.service import build_runtime_backend_launch_spec, configure_workspace_provider, register_builtin_providers
from core.providers.store import ProviderDocumentStore, ProviderCollections
from core.recovery.service import record_failed_start
from core.recovery.store import RecoveryDocumentStore, RecoveryCollections
from core.runtime.service import create_runtime_session, transition_runtime_session
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.secrets.service import bind_workspace_secret, build_secret_ref, create_platform_secret
from core.secrets.store import SecretDocumentStore, SecretCollections
from core.workspaces.files import build_export_manifest
from core.workspaces.service import ensure_default_workspace, ensure_default_workspace_record
from core.workspaces.store import WorkspaceDocumentStore, WorkspaceCollections
from tests.support.collections import FakeCollection

__all__ = [
    "ObservabilityTestBase",
    "AppCollections",
    "CliInvocationContext",
    "FakeCollection",
    "McpInvocationContext",
    "AppDocumentStore",
    "ObservabilityDocumentStore",
    "ProviderDocumentStore",
    "RecoveryDocumentStore",
    "RuntimeDocumentStore",
    "SecretDocumentStore",
    "WorkspaceDocumentStore",
    "ObservabilityCollections",
    "Path",
    "ProviderCapabilitySet",
    "ProviderCollections",
    "ProviderDefinition",
    "ProviderRegistry",
    "RecoveryCollections",
    "RuntimeBackendLaunchSpec",
    "RuntimeCollections",
    "SecretCollections",
    "UTC",
    "WorkspaceCollections",
    "append_runtime_log",
    "apply_retention",
    "bind_provider_credential",
    "bind_workspace_secret",
    "build_app_capabilities",
    "build_app_contract",
    "build_export_manifest",
    "build_parsed_app_contract",
    "build_runtime_backend_launch_spec",
    "build_secret_ref",
    "call_mcp_tool",
    "configure_workspace_provider",
    "create_application",
    "create_platform_secret",
    "create_runtime_session",
    "datetime",
    "emit_structured_event",
    "ensure_default_workspace",
    "ensure_default_workspace_record",
    "ensure_observability_roots",
    "install_store_app",
    "record_audit_event",
    "record_failed_start",
    "record_metric",
    "register_app_source_from_contract",
    "register_builtin_providers",
    "run_core_cli_command",
    "tempfile",
    "timedelta",
    "transition_runtime_session",
    "unittest",
    "write_app_contract_file",
]



class ObservabilityTestBase(unittest.TestCase):
    """Shared fixtures for observability helper module."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def make_workspace_store(self) -> WorkspaceDocumentStore:
        return WorkspaceDocumentStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
            )
        )

    def make_provider_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
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
