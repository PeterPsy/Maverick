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
from core.apps.store import AppCollections, MongoAppStore


class FakeCollection:
    """Small in-memory collection for app store tests."""

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
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents.pop(index)
                return


class Phase4AppHostingBase(unittest.TestCase):
    """Shared fixtures for tests/test_phase4_app_hosting.py."""

    def make_store(self) -> MongoAppStore:
        return MongoAppStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
            )
        )

    def make_repo_root(self, temp_dir: str) -> Path:
        root = Path(temp_dir)
        (root / "AGENTS.md").write_text("test", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "maverick-v3"\nversion = "0.1.0"\n',
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
