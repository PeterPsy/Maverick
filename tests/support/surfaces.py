"""Shared helpers for MCP, CLI, and skills surface tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
import tempfile
import unittest

from core.apps.contracts import (
    build_app_capabilities,
    build_app_compatibility,
    build_app_contract,
    build_app_entrypoints,
    build_app_permissions,
    build_provided_interface_declaration,
    build_parsed_app_contract,
    build_required_interface_declaration,
    write_app_contract_file,
)
from core.apps.service import install_store_app, register_app_source_from_contract, transition_workspace_app_status
from core.apps.store import AppCollections, AppDocumentStore
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.errors import McpInvocationNotAllowedError
from core.mcp.models import McpInvocationContext
from core.mcp.service import build_workspace_mcp_surface, call_mcp_tool, list_mcp_tools
from core.providers.service import configure_workspace_provider, prepare_runtime_skills, register_builtin_providers
from core.providers.store import ProviderDocumentStore, ProviderCollections
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeDocumentStore, RuntimeCollections
from core.skills.service import list_available_workspace_skills, resolve_runtime_skills
from core.workspaces.store import WorkspaceDocumentStore, WorkspaceCollections
from core.workspaces.service import ensure_default_workspace_record
from tests.support.collections import FakeCollection

__all__ = [
    "SurfaceTestBase",
    "AppCollections",
    "CliInvocationContext",
    "CliInvocationNotAllowedError",
    "FakeCollection",
    "McpInvocationContext",
    "McpInvocationNotAllowedError",
    "AppDocumentStore",
    "ProviderDocumentStore",
    "RuntimeDocumentStore",
    "WorkspaceDocumentStore",
    "Path",
    "ProviderCollections",
    "RuntimeCollections",
    "UTC",
    "WorkspaceCollections",
    "build_app_capabilities",
    "build_app_compatibility",
    "build_app_contract",
    "build_app_entrypoints",
    "build_app_permissions",
    "build_parsed_app_contract",
    "build_provided_interface_declaration",
    "build_required_interface_declaration",
    "build_workspace_mcp_surface",
    "call_mcp_tool",
    "configure_workspace_provider",
    "create_runtime_session",
    "datetime",
    "ensure_default_workspace_record",
    "install_store_app",
    "list_available_workspace_skills",
    "list_core_cli_commands",
    "list_mcp_tools",
    "prepare_runtime_skills",
    "register_app_source_from_contract",
    "register_builtin_providers",
    "resolve_runtime_skills",
    "run_core_cli_command",
    "sys",
    "tempfile",
    "transition_workspace_app_status",
    "unittest",
    "write_app_contract_file",
]



class SurfaceTestBase(unittest.TestCase):
    """Shared fixtures for surface helper module."""

    def make_app_store(self) -> AppDocumentStore:
        return AppDocumentStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
                workspace_app_dependency_selections=FakeCollection(),
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

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def write_app_contract(
        self,
        app_root: Path,
        *,
        skill_id: str = "task-helper",
        secret_read: list[str] | None = None,
        workspace_modes: list[str] | None = None,
        provides: list | None = None,
        requires: list | None = None,
    ) -> None:
        (app_root / "backend" / "mcp").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "cli").mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "skills" / skill_id).mkdir(parents=True, exist_ok=True)
        (app_root / "backend" / "mcp" / "server.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'surface': payload.get('surface'), 'tool_name': payload.get('tool_name'), 'workspace_id': payload.get('workspace_id'), 'agent_id': payload.get('agent_id'), 'effective_mode': payload.get('effective_mode'), 'runtime_session_id': payload.get('runtime_session_id'), 'workspace_root': payload.get('workspace_root'), 'data_root': payload.get('data_root'), 'uploaded_storage_root': payload.get('uploaded_storage_root'), 'generated_storage_root': payload.get('generated_storage_root'), 'app_dependencies': payload.get('app_dependencies'), 'app_secrets': payload.get('app_secrets'), 'app_secret_errors': payload.get('app_secret_errors'), 'arguments': payload.get('arguments'), 'python': sys.executable}))\n",
            encoding="utf-8",
        )
        (app_root / "backend" / "cli" / "app_cli.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'surface': payload.get('surface'), 'command_id': payload.get('command_id'), 'workspace_id': payload.get('workspace_id'), 'agent_id': payload.get('agent_id'), 'effective_mode': payload.get('effective_mode'), 'runtime_session_id': payload.get('runtime_session_id'), 'workspace_root': payload.get('workspace_root'), 'data_root': payload.get('data_root'), 'uploaded_storage_root': payload.get('uploaded_storage_root'), 'generated_storage_root': payload.get('generated_storage_root'), 'app_dependencies': payload.get('app_dependencies'), 'app_secrets': payload.get('app_secrets'), 'app_secret_errors': payload.get('app_secret_errors'), 'arguments': payload.get('arguments'), 'python': sys.executable}))\n",
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
                provides=provides,
                requires=requires,
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
                permissions=build_app_permissions(secret_read=secret_read or []),
                compatibility=build_app_compatibility(supported_workspace_modes=workspace_modes),
            ),
        )
        write_app_contract_file(app_root, parsed)
