"""Tests for the official Maverick App SDK."""

from __future__ import annotations

from pathlib import Path
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import BytesIO, StringIO
import json
import os
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.app_sdk.errors import AppSdkPathError, AppSdkValidationError
from core.app_sdk.cli import main as app_sdk_cli_main
from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.packaging import package_app_source
from core.app_sdk.service import app_sdk_status, create_app_source, register_local_app, validate_app_source
from core.app_sdk.storage import ensure_json_state, safe_app_data_path
from core.apps.contracts import parse_app_contract_file
from core.shared.entrypoints import run_json_entrypoint
from core.apps.store import AppCollections, AppDocumentStore
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.runtime.service import create_runtime_session
from core.runtime.workspace_api_token import issue_workspace_api_token, register_workspace_api_token, verify_workspace_api_token
from core.workspaces.service import create_workspace
from tests.support.app_hosting import FakeCollection
from tests.support.markers import slow_test_class


@slow_test_class("slow app-sdk integration suite; run with scripts/test_suite.py --level slow")
class MaverickAppSdkTestCase(unittest.TestCase):
    """Verify SDK app generation, validation, registration, installation, and helpers."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        repo_root.mkdir()
        source_repo = Path(__file__).resolve().parents[3]
        os.symlink(source_repo / "core", repo_root / "core", target_is_directory=True)
        for name in ("apps", "workspaces", "docs", "scripts", "tests"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("test", encoding="utf-8")
        return repo_root

    def make_store(self) -> AppDocumentStore:
        return AppDocumentStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
                workspace_app_dependency_selections=FakeCollection(),
            )
        )

    def operator_context(self) -> CliInvocationContext:
        return CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

    def sandbox_agent_context(self, *, workspace_id: str = "default") -> CliInvocationContext:
        return CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id=workspace_id,
            agent_id="agent-1",
            effective_mode="sandbox",
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
                if parsed.contract.entrypoints.frontend is not None:
                    app_root = Path(result.app_root)
                    self.assertTrue((app_root / ".npmrc").is_file())
                    self.assertTrue((app_root / "package.json").is_file())
                    self.assertTrue((app_root / "vite.config.ts").is_file())
                    self.assertTrue((app_root / "tsconfig.json").is_file())
                    self.assertTrue((app_root / "scripts" / "check-node-runtime.mjs").is_file())
                    self.assertTrue((app_root / "frontend" / "index.html").is_file())
                    self.assertTrue((app_root / "frontend" / "src" / "main.tsx").is_file())
                    self.assertTrue((app_root / "frontend" / "src" / "styles.css").is_file())
                    package = json.loads((app_root / "package.json").read_text(encoding="utf-8"))
                    self.assertEqual(package["scripts"]["prebuild"], "node scripts/check-node-runtime.mjs")
                    self.assertEqual(package["scripts"]["build"], "tsc --noEmit && vite build")
                    self.assertEqual(package["scripts"]["predev"], "node scripts/check-node-runtime.mjs")
                    self.assertIn("react", package["dependencies"])
                    self.assertIn("react-dom", package["dependencies"])
                    self.assertIn("@vitejs/plugin-react", package["devDependencies"])
                    self.assertFalse((app_root / "frontend" / "src" / "index.html").exists())
                    self.assertFalse((app_root / "scripts" / "build-frontend.mjs").exists())
                if template_id == "widget":
                    self.assertEqual(parsed.contract.widgets[0].widget_id, "sdk-widget-widget")
                    self.assertTrue((Path(result.app_root) / "frontend" / "widgets" / "main" / "index.html").is_file())
                    self.assertTrue((Path(result.app_root) / "frontend" / "src" / "widgets" / "main" / "main.tsx").is_file())
                if template_id == "entity-sqlite":
                    self.assertEqual(parsed.contract.storage.storage_kind, "sqlite")
                    self.assertEqual(
                        [entity.entity_type for entity in parsed.contract.capabilities.reference_entities],
                        ["record"],
                    )
                    self.assertIn("sdk_entity_sqlite_view_filter", parsed.contract.capabilities.mcp_tools)
                    self.assertIn(
                        "view-state",
                        [event.resource for event in parsed.contract.capabilities.data_events],
                    )
                    self.assertEqual(
                        [action.action for action in parsed.contract.capabilities.view_surfaces[0].state_actions],
                        ["view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"],
                    )

    def test_sdk_cli_create_register_install_status_and_app_cli_surface(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_store()
        context = self.sandbox_agent_context()

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
        (app_root / ".env").write_text("TOKEN=secret", encoding="utf-8")
        (app_root / "private.pem").write_text("private", encoding="utf-8")
        (app_root / "node_modules").mkdir()
        (app_root / "node_modules" / "large.js").write_text("junk", encoding="utf-8")
        outside_secret = repo_root / "outside-secret.txt"
        outside_secret.write_text("outside", encoding="utf-8")
        (app_root / "outside-link.txt").symlink_to(outside_secret)

        package = package_app_source(app_root, output_path=repo_root / "tmp" / "sdk-package.tar.gz")
        manifest = json.loads(Path(package.manifest_path).read_text(encoding="utf-8"))

        self.assertTrue(Path(package.artifact_path).is_file())
        self.assertIn("app_contract.json", package.files_packaged)
        self.assertNotIn("__pycache__/junk.pyc", package.files_packaged)
        self.assertNotIn(".env", package.files_packaged)
        self.assertNotIn("private.pem", package.files_packaged)
        self.assertNotIn("node_modules/large.js", package.files_packaged)
        self.assertNotIn("outside-link.txt", package.files_packaged)
        self.assertTrue(Path(package.manifest_path).is_file())
        self.assertEqual(len(package.checksum_sha256), 64)
        self.assertEqual(manifest["provenance"]["source"], {"kind": "app_source_tree", "app_id": "sdk-package"})
        self.assertNotIn(str(repo_root), json.dumps(manifest))

    def test_package_without_output_uses_workspace_generated_storage(self) -> None:
        repo_root = self.make_repo_root()
        result = create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-package-default",
                template_id="minimal",
                target_kind="workspace_local",
                workspace_id="default",
            ),
            start_path=repo_root,
        )

        package = package_app_source(result.app_root)

        self.assertEqual(
            Path(package.artifact_path),
            repo_root / "workspaces" / "default" / "storage" / "generated" / "sdk-package-default.tar.gz",
        )
        self.assertTrue(Path(package.manifest_path).is_file())

    def test_sdk_validation_rejects_noop_frontend_build_script(self) -> None:
        repo_root = self.make_repo_root()
        result = create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-noop-build",
                template_id="react-vite",
                target_kind="workspace_local",
                workspace_id="default",
            ),
            start_path=repo_root,
        )
        app_root = Path(result.app_root)
        package_json = json.loads((app_root / "package.json").read_text(encoding="utf-8"))
        package_json["scripts"]["build"] = "node -e \"require('fs').accessSync('frontend/dist/index.html'); process.exit(0)\""
        (app_root / "package.json").write_text(json.dumps(package_json, indent=2), encoding="utf-8")

        validation = validate_app_source(app_root)

        self.assertFalse(validation.valid)
        self.assertTrue(any(issue.field == "package.json.scripts.build" for issue in validation.issues))

    def test_entity_sqlite_template_exercises_backend_cli_and_mcp(self) -> None:
        repo_root = self.make_repo_root()
        result = create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-records-lite",
                template_id="entity-sqlite",
                target_kind="workspace_local",
                workspace_id="default",
                entities=["account", "contact", "deal"],
            ),
            start_path=repo_root,
        )
        app_root = Path(result.app_root)
        data_root = repo_root / "workspaces" / "default" / "data" / "sdk-records-lite"

        backend_create = run_json_entrypoint(
            app_root / "backend" / "app_backend.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-records-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "body": {"action": "create", "entity_type": "account", "title": "Acme"},
            },
        )
        cli_list = run_json_entrypoint(
            app_root / "cli" / "app_cli.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-records-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "arguments": {"action": "list", "entity_type": "account"},
            },
        )
        mcp_manifest = run_json_entrypoint(
            app_root / "mcp" / "server.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-records-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "tool_name": "sdk_records_lite_reference_manifest",
                "arguments": {},
            },
        )
        mcp_view_state = run_json_entrypoint(
            app_root / "mcp" / "server.py",
            cwd=app_root,
            payload={
                "app_id": "sdk-records-lite",
                "workspace_id": "default",
                "data_root": str(data_root),
                "tool_name": "sdk_records_lite_set_view_filter",
                "arguments": {"query": "Acme", "entity_type": "account"},
            },
        )

        self.assertEqual(backend_create["status_code"], 201)
        self.assertEqual(cli_list["items"][0]["title"], "Acme")
        self.assertEqual(
            [entity["entity_type"] for entity in mcp_manifest["entity_types"]],
            ["account", "contact", "deal"],
        )
        self.assertEqual(mcp_view_state["state"]["view_filter"]["query"], "Acme")
        self.assertEqual(mcp_view_state["app_events"][0]["resource"], "view-state")

    def test_sdk_validation_enforces_reference_and_view_state_surface_completeness(self) -> None:
        repo_root = self.make_repo_root()
        store = self.make_store()
        result = create_app_source(
            AppSdkCreateRequest(
                app_id="sdk-incomplete-records",
                template_id="entity-sqlite",
                target_kind="workspace_local",
                workspace_id="default",
                entities=["account"],
            ),
            start_path=repo_root,
        )
        contract_path = Path(result.contract_path)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"]["mcp_tools"].remove("sdk_incomplete_records_set_view_filter")
        contract["capabilities"]["data_events"] = [
            event for event in contract["capabilities"]["data_events"] if event["resource"] != "view-state"
        ]
        contract_path.write_text(json.dumps(contract, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        validation = validate_app_source(result.app_root)
        issue_text = " ".join(issue.message for issue in validation.issues)

        self.assertFalse(validation.valid)
        self.assertIn("View surface `main` is missing matching MCP tools", issue_text)
        self.assertIn("Apps with view_surfaces must declare a `view-state` data event", issue_text)
        with self.assertRaises(AppSdkValidationError):
            register_local_app(store, workspace_id="default", app_id="sdk-incomplete-records", start_path=repo_root)

    def test_cli_wrapper_creates_workspace_app(self) -> None:
        repo_root = self.make_repo_root()

        with redirect_stdout(StringIO()):
            exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "core.app-sdk.create",
                    "--app-id",
                    "sdk-cli",
                    "--template-id",
                    "react-vite",
                    "--workspace",
                    "default",
                ]
            )
        with redirect_stdout(StringIO()):
            register_exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "core.app-sdk.register-local",
                    "--app-id",
                    "sdk-cli",
                    "--workspace",
                    "default",
                ]
            )
        with redirect_stdout(StringIO()):
            install_exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "core.app-sdk.install-local",
                    "--app-id",
                    "sdk-cli",
                    "--workspace",
                    "default",
                ]
            )
        list_output = StringIO()
        with redirect_stdout(list_output):
            list_exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "list",
                    "--workspace",
                    "default",
                    "--json",
                ]
            )
        dependencies_output = StringIO()
        with redirect_stdout(dependencies_output):
            dependencies_exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "app.sdk-cli.dependencies",
                    "--workspace",
                    "default",
                    "--json",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(register_exit_code, 0)
        self.assertEqual(install_exit_code, 0)
        self.assertEqual(list_exit_code, 0)
        self.assertEqual(dependencies_exit_code, 0)
        self.assertTrue((repo_root / "workspaces" / "default" / "apps" / "sdk-cli" / "package.json").is_file())
        list_payload = json.loads(list_output.getvalue())
        command_ids = {command["command_id"] for command in list_payload["commands"]}
        self.assertIn("app.sdk-cli.dependencies", command_ids)
        dependencies_payload = json.loads(dependencies_output.getvalue())
        self.assertEqual(dependencies_payload["status"], "resolved")

    def test_cli_wrapper_exposes_sdk_docs_and_templates_domain(self) -> None:
        repo_root = self.make_repo_root()
        docs_output = StringIO()
        templates_output = StringIO()

        with redirect_stdout(docs_output):
            docs_exit_code = app_sdk_cli_main(["--repository-root", str(repo_root), "sdk", "docs", "--json"])
        with redirect_stdout(templates_output):
            templates_exit_code = app_sdk_cli_main(["--repository-root", str(repo_root), "sdk", "templates", "--json"])

        docs_payload = json.loads(docs_output.getvalue())
        templates_payload = json.loads(templates_output.getvalue())
        self.assertEqual(docs_exit_code, 0)
        self.assertEqual(templates_exit_code, 0)
        self.assertEqual(docs_payload["format"], "markdown")
        self.assertIn("Maverick App SDK", docs_payload["content"])
        self.assertIn("minimal", templates_payload["templates"])

    def test_cli_wrapper_packages_workspace_app_by_app_id_to_generated_storage(self) -> None:
        repo_root = self.make_repo_root()
        package_output = StringIO()
        with redirect_stdout(StringIO()):
            app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "core.app-sdk.create",
                    "--app-id",
                    "sdk-cli-package",
                    "--template-id",
                    "minimal",
                    "--workspace",
                    "default",
                ]
            )

        with redirect_stdout(package_output):
            exit_code = app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "core.app-sdk.package",
                    "--app-id",
                    "sdk-cli-package",
                    "--workspace",
                    "default",
                ]
            )

        payload = json.loads(package_output.getvalue())
        artifact_path = Path(payload["artifact_path"])
        manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(artifact_path, repo_root / "workspaces" / "default" / "storage" / "generated" / "sdk-cli-package.tar.gz")
        self.assertTrue(artifact_path.is_file())
        self.assertEqual(manifest["provenance"]["source"], {"kind": "app_source_tree", "app_id": "sdk-cli-package"})
        self.assertNotIn(str(repo_root), json.dumps(manifest))

    def test_cli_wrapper_rejects_package_app_root_and_output_path(self) -> None:
        repo_root = self.make_repo_root()
        app_root_flag = "--app-" + "root"
        output_path_flag = "--output-" + "path"

        with self.assertRaises(RuntimeError) as captured:
            app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "core",
                    "cli",
                    "run",
                    "core.app-sdk.package",
                    app_root_flag,
                    str(repo_root / "workspaces" / "default" / "apps" / "sdk-cli-package"),
                    output_path_flag,
                    str(repo_root / "tmp" / "custom.tar.gz"),
                    "--workspace",
                    "default",
                ]
            )

        self.assertIn("requires `app_id`", str(captured.exception))

    def test_legacy_app_sdk_shortcut_no_longer_runs(self) -> None:
        repo_root = self.make_repo_root()

        with self.assertRaises(SystemExit) as captured:
            app_sdk_cli_main(
                [
                    "--repository-root",
                    str(repo_root),
                    "app",
                    "status",
                    "does-not-exist",
                    "--json",
                ]
            )

        self.assertIn("app surface must be `cli`, `mcp`, or `frontend`", str(captured.exception))

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
        create_runtime_session(
            state.runtime_store,
            session_id="sess-ceida",
            workspace_id="ceida",
            agent_id="agent",
            requested_mode="sandbox",
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            start_path=repo_root,
        )
        token = issue_workspace_api_token(workspace_id="ceida", runtime_session_id="sess-ceida")
        register_workspace_api_token(state.runtime_store, token)

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
        package_status, package_payload = self.invoke_json(
            app,
            "/api/app-sdk",
            method="POST",
            token=token,
            payload={"action": "package", "app_id": "pisa-weather"},
        )

        self.assertEqual(create_status, "403 Forbidden")
        self.assertEqual(create_payload["error"], "app_management_forbidden")
        self.assertFalse((repo_root / "workspaces" / "ceida" / "apps" / "pisa-weather").exists())
        self.assertFalse((repo_root / "workspaces" / "default" / "apps" / "pisa-weather").exists())
        self.assertEqual(register_status, "403 Forbidden")
        self.assertEqual(register_payload["error"], "app_management_forbidden")
        self.assertEqual(install_status, "403 Forbidden")
        self.assertEqual(install_payload["error"], "app_management_forbidden")
        self.assertEqual(status_status, "200 OK")
        self.assertFalse(status_payload["registered"])
        self.assertFalse(status_payload["installed"])
        self.assertEqual(package_status, "403 Forbidden")
        self.assertEqual(package_payload["error"], "app_management_forbidden")

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
        create_runtime_session(
            state.runtime_store,
            session_id="sess-docs",
            workspace_id="docs-workspace",
            agent_id="agent",
            requested_mode="sandbox",
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            start_path=repo_root,
        )
        token = issue_workspace_api_token(workspace_id="docs-workspace", runtime_session_id="sess-docs")
        register_workspace_api_token(state.runtime_store, token)

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
        self.assertIn("maverick core cli run core.app-sdk.create", payload["content"])
        self.assertNotIn("maverick app " + "create", payload["content"])
        self.assertNotIn("docs/app-sdk", payload["content"])

    def test_runtime_api_token_carries_mode_and_expires(self) -> None:
        now = datetime(2026, 4, 28, tzinfo=UTC)

        token = issue_workspace_api_token(
            workspace_id="default",
            runtime_session_id="sess-1",
            effective_mode="sandbox",
            ttl_seconds=30,
            now=now,
        )

        active_claims = verify_workspace_api_token(token, now=now + timedelta(seconds=29))
        expired_claims = verify_workspace_api_token(token, now=now + timedelta(seconds=31))
        self.assertIsNotNone(active_claims)
        assert active_claims is not None
        self.assertEqual(active_claims["mode"], "sandbox")
        self.assertTrue(active_claims["token_id"])
        self.assertIsNone(expired_claims)

    def test_runtime_cli_api_runs_official_cli_with_runtime_token_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        create_workspace(
            state.workspace_store,
            name="CEIDA",
            created_by_user_id="user:admin",
            creator_role="member",
        )
        create_runtime_session(
            state.runtime_store,
            session_id="sess-ceida",
            workspace_id="ceida",
            agent_id="agent",
            requested_mode="sandbox",
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            start_path=repo_root,
        )
        app = PlatformHost(state, workspace_id="default", start_path=repo_root)
        token = issue_workspace_api_token(workspace_id="ceida", runtime_session_id="sess-ceida")
        register_workspace_api_token(state.runtime_store, token)

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

    def test_runtime_cli_api_runs_app_sdk_status_with_runtime_token_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        create_workspace(
            state.workspace_store,
            name="CEIDA",
            created_by_user_id="user:admin",
            creator_role="member",
        )
        create_runtime_session(
            state.runtime_store,
            session_id="sess-sdk-ceida",
            workspace_id="ceida",
            agent_id="agent",
            requested_mode="sandbox",
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            start_path=repo_root,
        )
        app = PlatformHost(state, workspace_id="default", start_path=repo_root)
        token = issue_workspace_api_token(workspace_id="ceida", runtime_session_id="sess-sdk-ceida")
        register_workspace_api_token(state.runtime_store, token)

        status, payload = self.invoke_json(
            app,
            "/api/runtime/cli",
            method="POST",
            token=token,
            payload={"argv": ["core", "cli", "run", "core.app-sdk.status", "--app-id", "missing-app", "--json"]},
        )

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["workspace_id"], "ceida")
        self.assertFalse(payload["source_exists"])
        self.assertFalse(payload["registered"])
        self.assertFalse(payload["installed"])

    def test_runtime_cli_api_rejects_revoked_runtime_token(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        create_workspace(
            state.workspace_store,
            name="CEIDA",
            created_by_user_id="user:admin",
            creator_role="member",
        )
        create_runtime_session(
            state.runtime_store,
            session_id="sess-ceida",
            workspace_id="ceida",
            agent_id="agent",
            requested_mode="sandbox",
            owner_user_id="user:admin",
            created_by_user_id="user:admin",
            start_path=repo_root,
        )
        app = PlatformHost(state, workspace_id="default", start_path=repo_root)
        token = issue_workspace_api_token(workspace_id="ceida", runtime_session_id="sess-ceida")
        record = register_workspace_api_token(state.runtime_store, token)
        assert record is not None
        state.runtime_store.revoke_api_token(record.token_id)

        status, payload = self.invoke_json(
            app,
            "/api/runtime/cli",
            method="POST",
            token=token,
            payload={"argv": ["apps", "list", "--json"]},
        )

        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(payload["error"], "runtime_token_revoked")


if __name__ == "__main__":
    unittest.main()
