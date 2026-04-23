"""Tests for the official Maverick App SDK."""

from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
import os
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
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
from core.runtime.workspace_api_token import issue_workspace_api_token
from core.workspaces.service import create_workspace
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

    def invoke_json(
        self,
        app: PlatformHost,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        token: str | None = None,
    ) -> tuple[str, dict[str, object]]:
        raw = json.dumps(payload or {}).encode("utf-8") if payload is not None else b""
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": BytesIO(raw),
        }
        if token:
            environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        status_holder: list[str] = []

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            status_holder.append(status)

        body = b"".join(app(environ, start_response)).decode("utf-8")
        return status_holder[0], json.loads(body) if body else {}

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
                if template_id == "react-vite":
                    self.assertTrue(parsed.contract.lifecycle.rebuild)
                if template_id == "entity-sqlite":
                    self.assertEqual(parsed.contract.storage.storage_kind, "sqlite")
                    self.assertEqual([entity.entity_type for entity in parsed.contract.capabilities.reference_entities], ["record"])
                    self.assertTrue(parsed.contract.lifecycle.rebuild)

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

    def test_workspace_sdk_api_uses_runtime_token_without_default_workspace_fallback(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        create_workspace(
            state.workspace_store,
            name="CEIDA",
            created_by_user_id="user:admin",
            creator_role="member",
        )
        app = PlatformHost(state, workspace_id="default", start_path=repo_root)
        token = issue_workspace_api_token(workspace_id="ceida", runtime_session_id="sess-ceida")

        create_status, create_payload = self.invoke_json(
            app,
            "/api/app-sdk",
            method="POST",
            token=token,
            payload={
                "action": "create",
                "app_id": "pisa-weather",
                "template_id": "react-vite",
                "name": "Pisa Weather",
            },
        )
        register_status, register_payload = self.invoke_json(
            app,
            "/api/app-sdk",
            method="POST",
            token=token,
            payload={"action": "register-local", "app_id": "pisa-weather"},
        )
        install_status, install_payload = self.invoke_json(
            app,
            "/api/app-sdk",
            method="POST",
            token=token,
            payload={"action": "install-local", "app_id": "pisa-weather"},
        )
        status_status, status_payload = self.invoke_json(
            app,
            "/api/app-sdk",
            method="POST",
            token=token,
            payload={"action": "status", "app_id": "pisa-weather"},
        )

        self.assertEqual(create_status, "201 Created")
        self.assertEqual(create_payload["workspace_id"], "ceida")
        self.assertTrue((repo_root / "workspaces" / "ceida" / "apps" / "pisa-weather" / "app_contract.json").is_file())
        self.assertFalse((repo_root / "workspaces" / "default" / "apps" / "pisa-weather").exists())
        self.assertEqual(register_status, "201 Created")
        self.assertEqual(register_payload["workspace_id"], "ceida")
        self.assertEqual(install_status, "201 Created")
        self.assertEqual(install_payload["workspace_id"], "ceida")
        self.assertEqual(status_status, "200 OK")
        self.assertTrue(status_payload["installed"])

    def test_workspace_sdk_api_returns_documentation_content(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        create_workspace(
            state.workspace_store,
            name="Docs Workspace",
            created_by_user_id="user:admin",
            creator_role="member",
        )
        app = PlatformHost(state, workspace_id="default", start_path=repo_root)
        token = issue_workspace_api_token(workspace_id="docs-workspace", runtime_session_id="sess-docs")

        status, payload = self.invoke_json(
            app,
            "/api/app-sdk",
            method="POST",
            token=token,
            payload={"action": "docs"},
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["workspace_id"], "docs-workspace")
        self.assertEqual(payload["format"], "markdown")
        self.assertIn("Maverick App SDK", payload["content"])
        self.assertIn("maverick app create", payload["content"])
        self.assertNotIn("docs/app-sdk", payload["content"])

    def test_runtime_cli_api_runs_official_cli_with_runtime_token_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        create_workspace(
            state.workspace_store,
            name="CEIDA",
            created_by_user_id="user:admin",
            creator_role="member",
        )
        app = PlatformHost(state, workspace_id="default", start_path=repo_root)
        token = issue_workspace_api_token(workspace_id="ceida", runtime_session_id="sess-ceida")

        status, payload = self.invoke_json(
            app,
            "/api/runtime/cli",
            method="POST",
            token=token,
            payload={"argv": ["apps", "list", "--json"], "effective_mode": "sandbox"},
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["workspace_id"], "ceida")
        self.assertEqual(payload["apps"], [])

    def test_sdk_skill_sources_do_not_reference_installation_global_paths(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        skill_paths = [
            repo_root / "apps" / "skills" / "skills" / "maverick3-code-skill" / "SKILL.md",
            repo_root / "apps" / "skills" / "skills" / "maverick-v3-app-creator" / "SKILL.md",
            repo_root / "apps" / "skills" / "skills" / "maverick-v3-app-porting" / "SKILL.md",
        ]

        for skill_path in skill_paths:
            with self.subTest(skill_path=skill_path):
                content = skill_path.read_text(encoding="utf-8")
                self.assertNotIn("<repo>", content)
                self.assertNotIn("maverick-v3/workspaces/default", content)
                self.assertNotIn("docs/architecture", content)
                self.assertNotIn("core_architecture", content)
                self.assertNotIn("workspace_root_architecture", content)
                self.assertNotIn("app_contract_architecture", content)
                self.assertNotIn("app_sdk_architecture", content)

    def test_developer_kit_contract_parses(self) -> None:
        app_root = Path(__file__).resolve().parents[1] / "apps" / "developer-kit"

        parsed = parse_app_contract_file(app_root)

        self.assertEqual(parsed.app_id, "developer-kit")
        self.assertIsNone(parsed.contract.entrypoints.backend)
        self.assertIsNone(parsed.contract.visibility.platform_roles)


if __name__ == "__main__":
    unittest.main()
