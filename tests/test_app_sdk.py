"""Tests for the official Maverick App SDK."""

from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import os
import tempfile
import unittest

from core.app_sdk.errors import AppSdkPathError
from core.app_sdk.cli import main as app_sdk_cli_main
from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.packaging import package_app_source
from core.app_sdk.service import app_sdk_status, create_app_source, validate_app_source
from core.app_sdk.storage import ensure_json_state, safe_app_data_path
from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint
from core.apps.store import AppCollections, MongoAppStore
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from tests.phase4_app_hosting_helpers import FakeCollection


class MaverickAppSdkTestCase(unittest.TestCase):
    """Verify SDK app generation, validation, registration, installation, and helpers."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        repo_root.mkdir()
        source_repo = Path(__file__).resolve().parents[1]
        os.symlink(source_repo / "core", repo_root / "core", target_is_directory=True)
        for name in ("apps", "workspaces", "docs", "scripts", "tests"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("test", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("test", encoding="utf-8")
        return repo_root

    def make_store(self) -> MongoAppStore:
        return MongoAppStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
            )
        )

    def operator_context(self) -> CliInvocationContext:
        return CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

    def test_sdk_generates_valid_contracts_for_supported_templates(self) -> None:
        repo_root = self.make_repo_root()
        for template_id in (
            "minimal",
            "frontend-backend",
            "agent-tool",
            "data-app",
            "widget",
            "react-vite",
            "entity-sqlite",
        ):
            with self.subTest(template_id=template_id):
                app_id = f"sdk-{template_id}"
                result = create_app_source(
                    AppSdkCreateRequest(
                        app_id=app_id,
                        template_id=template_id,
                        target_kind="workspace_local",
                        workspace_id="default",
                    ),
                    start_path=repo_root,
                )

                parsed = parse_app_contract_file(Path(result.app_root))
                validation = validate_app_source(result.app_root)

                self.assertEqual(parsed.app_id, app_id)
                self.assertEqual(parsed.contract.distribution.mode, "workspace_local")
                self.assertEqual(parsed.contract.distribution.source_access, "editable")
                self.assertTrue(validation.valid)
                if template_id == "widget":
                    self.assertEqual(parsed.contract.widgets[0].widget_id, "sdk-widget-widget")
                if template_id == "entity-sqlite":
                    self.assertEqual(parsed.contract.storage.storage_kind, "sqlite")
                    self.assertEqual([entity.entity_type for entity in parsed.contract.capabilities.reference_entities], ["record"])

    def test_sdk_cli_create_register_install_status_and_app_cli_surface(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_store()
        context = self.operator_context()

        create_result = run_core_cli_command(
            command_id="core.app-sdk.create",
            context=context,
            app_store=store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"app_id": "sdk-data", "template_id": "data-app"},
        )
        register_result = run_core_cli_command(
            command_id="core.app-sdk.register-local",
            context=context,
            app_store=store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"app_id": "sdk-data"},
        )
        install_result = run_core_cli_command(
            command_id="core.app-sdk.install-local",
            context=context,
            app_store=store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"app_id": "sdk-data"},
        )
        status_result = run_core_cli_command(
            command_id="core.app-sdk.status",
            context=context,
            app_store=store,
            workspace_id="default",
            start_path=repo_root,
            arguments={"app_id": "sdk-data"},
        )
        commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
        app_result = run_core_cli_command(
            command_id="app.sdk-data.sdk-data",
            context=CliInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="agent-1",
                effective_mode="sandbox",
            ),
            app_store=store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(create_result["app_id"], "sdk-data")
        self.assertEqual(register_result["status"], "registered")
        self.assertEqual(install_result["binding_status"], "enabled")
        self.assertTrue(status_result["source_exists"])
        self.assertTrue(status_result["registered"])
        self.assertTrue(status_result["installed"])
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "sdk-data" / "state.json").is_file())
        self.assertIn("core.app-sdk.create", [command.command_id for command in commands])
        self.assertIn("app.sdk-data.sdk-data", [command.command_id for command in commands])
        self.assertEqual(app_result["reference_manifest"], {"entity_types": []})

    def test_status_distinguishes_source_registered_and_installed(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_store()

        missing = app_sdk_status(store, workspace_id="default", app_id="sdk-notes", start_path=repo_root)
        create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-notes",
                template_id="minimal",
                target_kind="workspace_local",
                workspace_id="default",
            ),
            start_path=repo_root,
        )
        source_only = app_sdk_status(store, workspace_id="default", app_id="sdk-notes", start_path=repo_root)

        self.assertFalse(missing.source_exists)
        self.assertTrue(source_only.source_exists)
        self.assertFalse(source_only.registered)
        self.assertFalse(source_only.installed)
        self.assertIsNotNone(source_only.validation)
        self.assertTrue(source_only.validation.valid)

    def test_storage_helpers_reject_path_traversal(self) -> None:
        repo_root = self.make_repo_root()
        data_root = repo_root / "workspaces" / "default" / "data" / "sdk-data"

        path = ensure_json_state(data_root, "state.json", {"schema_version": "1"})

        self.assertEqual(path, safe_app_data_path(data_root, "state.json"))
        with self.assertRaises(AppSdkPathError):
            safe_app_data_path(data_root, "../other/state.json")

    def test_package_valid_app_source_excludes_generated_junk(self) -> None:
        repo_root = self.make_repo_root()
        result = create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-package",
                template_id="data-app",
                target_kind="workspace_local",
                workspace_id="default",
            ),
            start_path=repo_root,
        )
        app_root = Path(result.app_root)
        (app_root / "__pycache__").mkdir()
        (app_root / "__pycache__" / "junk.pyc").write_text("junk", encoding="utf-8")

        package = package_app_source(app_root, output_path=repo_root / "tmp" / "sdk-package.tar.gz")

        self.assertTrue(Path(package.artifact_path).is_file())
        self.assertIn("app_contract.json", package.files_packaged)
        self.assertNotIn("__pycache__/junk.pyc", package.files_packaged)
        self.assertTrue(Path(package.manifest_path).is_file())
        self.assertEqual(len(package.checksum_sha256), 64)

    def test_entity_sqlite_template_exercises_backend_cli_and_mcp(self) -> None:
        repo_root = self.make_repo_root()
        result = create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-crm-lite",
                template_id="entity-sqlite",
                target_kind="workspace_local",
                workspace_id="default",
                entities=["account", "contact", "deal"],
            ),
            start_path=repo_root,
        )
        app_root = Path(result.app_root)
        data_root = repo_root / "workspaces" / "default" / "data" / "sdk-crm-lite"

        backend_create = run_json_entrypoint(
            app_root / "backend" / "app_backend.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-crm-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "body": {"action": "create", "entity_type": "account", "title": "Acme"},
            },
        )
        cli_list = run_json_entrypoint(
            app_root / "cli" / "app_cli.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-crm-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "arguments": {"action": "list", "entity_type": "account"},
            },
        )
        mcp_manifest = run_json_entrypoint(
            app_root / "mcp" / "server.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-crm-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "tool_name": "sdk-crm-lite_reference_manifest",
                "arguments": {},
            },
        )

        self.assertEqual(backend_create["status_code"], 201)
        self.assertEqual(cli_list["items"][0]["title"], "Acme")
        self.assertEqual(
            [entity["entity_type"] for entity in mcp_manifest["entity_types"]],
            ["account", "contact", "deal"],
        )

    def test_cli_wrapper_creates_workspace_app(self) -> None:
        repo_root = self.make_repo_root()

        with redirect_stdout(StringIO()):
            exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "app",
                    "create",
                    "sdk-cli",
                    "--template",
                    "react-vite",
                    "--workspace",
                    "default",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue((repo_root / "workspaces" / "default" / "apps" / "sdk-cli" / "package.json").is_file())

    def test_developer_kit_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1] / "apps" / "developer-kit"

        parsed = parse_app_contract_file(app_root)

        self.assertEqual(parsed.app_id, "developer-kit")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertIsNone(parsed.contract.visibility.platform_roles)


if __name__ == "__main__":
    unittest.main()
