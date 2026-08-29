"""Tests for app-hosting control-plane behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.apps.contracts import (
    build_app_capabilities,
    build_app_compatibility,
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_failure_semantics,
    build_app_health_contract,
    build_app_hook_timeouts,
    build_app_lifecycle,
    build_app_rollback_support,
    build_app_storage,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.errors import (
    AppCompatibilityError,
    AppLifecycleError,
    WorkspaceAppBindingNotFoundError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.service import (
    fork_store_app_to_workspace,
    install_store_app,
    install_workspace_local_app,
    purge_workspace_app_data,
    register_app_source_from_contract,
    register_workspace_local_app_project_from_contract,
    reinstall_workspace_app,
    transition_workspace_app_status,
    uninstall_workspace_app,
    upgrade_workspace_app,
)
from core.apps.store import AppCollections, AppDocumentStore
from tests.support.collections import FakeCollection

__all__ = [
    "AppHostingTestBase",
    "AppCollections",
    "AppCompatibilityError",
    "AppLifecycleError",
    "FakeCollection",
    "AppDocumentStore",
    "Path",
    "TemporaryDirectory",
    "UTC",
    "WorkspaceAppBindingNotFoundError",
    "WorkspaceLocalAppProjectNotFoundError",
    "build_app_capabilities",
    "build_app_compatibility",
    "build_app_contract",
    "build_app_distribution",
    "build_app_entrypoints",
    "build_app_failure_semantics",
    "build_app_health_contract",
    "build_app_hook_timeouts",
    "build_app_lifecycle",
    "build_app_rollback_support",
    "build_app_storage",
    "build_parsed_app_contract",
    "datetime",
    "fork_store_app_to_workspace",
    "install_store_app",
    "install_workspace_local_app",
    "patch",
    "purge_workspace_app_data",
    "register_app_source_from_contract",
    "register_workspace_local_app_project_from_contract",
    "reinstall_workspace_app",
    "transition_workspace_app_status",
    "uninstall_workspace_app",
    "unittest",
    "upgrade_workspace_app",
    "write_app_contract_file",
]



class AppHostingTestBase(unittest.TestCase):
    """Shared fixtures for app hosting helper module."""

    def make_store(self) -> AppDocumentStore:
        return AppDocumentStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
                workspace_app_sidecar_quarantines=FakeCollection(),
                workspace_app_dependency_selections=FakeCollection(),
            )
        )

    def make_repo_root(self, temp_dir: str) -> Path:
        root = Path(temp_dir)
        (root / "AGENTS.md").write_text("test", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "maverick"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        for name in ("core", "apps", "workspaces", "docs", "scripts", "tests"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def write_contract(
        self,
        app_root: Path,
        *,
        app_id: str,
        name: str | None = None,
        version: str = "1.0.0",
        publisher: str = "maverick",
        contract=None,
    ) -> None:
        parsed = build_parsed_app_contract(
            app_id=app_id,
            name=name or app_id.title(),
            version=version,
            description=f"{app_id} app",
            publisher=publisher,
            contract=contract or build_app_contract(),
        )
        write_app_contract_file(app_root, parsed)
