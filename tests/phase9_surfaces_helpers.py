"""Tests for Phase 9 MCP, CLI, and skills surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
import tempfile
import unittest

from core.apps.contracts import (
    build_app_capabilities,
    build_app_contract,
    build_app_entrypoints,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.service import install_store_app, register_app_source_from_contract, transition_workspace_app_status
from core.apps.store import AppCollections, MongoAppStore
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.models import McpInvocationContext
from core.mcp.service import build_workspace_mcp_surface, call_mcp_tool, list_mcp_tools
from core.providers.service import prepare_runtime_skills, register_builtin_providers
from core.providers.store import MongoProviderStore, ProviderCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import MongoRuntimeStore, RuntimeCollections
from core.skills.service import list_available_workspace_skills, resolve_runtime_skills
from core.workspaces.store import MongoWorkspaceStore, WorkspaceCollections
from core.workspaces.service import ensure_default_workspace_record


class FakeCollection:
    """Small in-memory collection for control-plane store tests."""

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


class Phase9SurfacesBase(unittest.TestCase):
    """Shared fixtures for tests/test_phase9_surfaces.py."""

    def make_app_store(self) -> MongoAppStore:
        return MongoAppStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
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

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def write_app_contract(self, app_root: Path, *, skill_id: str = "task-helper") -> None:
        (app_root / "backend" / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "skills" / skill_id).mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "mcp" / "server.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'surface': payload.get('surface'), 'tool_name': payload.get('tool_name'), 'workspace_id': payload.get('workspace_id'), 'workspace_root': payload.get('workspace_root'), 'data_root': payload.get('data_root'), 'uploaded_storage_root': payload.get('uploaded_storage_root'), 'generated_storage_root': payload.get('generated_storage_root'), 'arguments': payload.get('arguments'), 'python': sys.executable}))\n",
            encoding="utf-8",
        )
        (app_root / "backend" / "cli" / "app_cli.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'surface': payload.get('surface'), 'command_id': payload.get('command_id'), 'workspace_id': payload.get('workspace_id'), 'workspace_root': payload.get('workspace_root'), 'data_root': payload.get('data_root'), 'uploaded_storage_root': payload.get('uploaded_storage_root'), 'generated_storage_root': payload.get('generated_storage_root'), 'arguments': payload.get('arguments'), 'python': sys.executable}))\n",
            encoding="utf-8",
        )
        (app_root / "backend" / "skills" / skill_id / "SKILL.md").write_text("# Task Helper\n", encoding="utf-8")
        parsed = build_parsed_app_contract(
            app_id="checklists",
            name="Checklists",
            version="1.0.0",
            description="Checklist app",
            publisher="maverick",
            contract=build_app_contract(
                capabilities=build_app_capabilities(
                    mcp_tools=["checklists.list"],
                    cli_commands=["checklists"],
                    skills=[skill_id],
                    views=[],
                ),
                entrypoints=build_app_entrypoints(
                    mcp="backend/mcp/server.py",
                    cli="backend/cli/app_cli.py",
                    skills_root="backend/skills",
                ),
            ),
        )
        write_app_contract_file(app_root, parsed)
