"""Tests for the Maverick v3 App Store app and install API."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from threading import Thread
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.apps.errors import WorkspaceAppBindingNotFoundError, WorkspaceLocalAppProjectNotFoundError
from core.apps.service import register_workspace_local_app_project_from_contract
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools


class AppStoreAppTestCase(unittest.TestCase):
    """Verify app-store surfaces and authenticated install behavior."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[1] / "apps"
        for app_id in ("base-shell", "chat", "agents", "app-store", "user-admin"):
            shutil.copytree(
                source_apps_root / app_id,
                repo_root / "apps" / app_id,
                ignore=shutil.ignore_patterns("node_modules", "__pycache__"),
            )
        return repo_root

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
        query_string: str = "",
    ) -> tuple[int, dict | bytes, dict[str, str]]:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": query_string,
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        raw = b"".join(app(environ, start_response))
        status = int(headers["__status__"].split()[0])
        if "application/json" in headers.get("Content-Type", ""):
            return status, json.loads(raw.decode("utf-8")), headers
        return status, raw, headers

    def login(self, app, *, username: str = "admin", password: str = "maverick3") -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def create_member_user(self, app, admin_cookie: str, *, username: str = "viewer") -> str:
        status_user, user, _user_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": username, "password": "memberpass", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_user, 201)
        status_workspace, _workspace, _workspace_headers = self.invoke(
            app,
            path=f"/api/admin/users/{user['user_id']}/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )
        self.assertEqual(status_workspace, 200)
        return self.login(app, username=username, password="memberpass")

    def write_remote_app_contract(self, app_root: Path) -> None:
        contract = {
            "app_id": "notes",
            "contract_version": "1.0",
            "name": "Notes",
            "version": "1.0.0",
            "description": "Tiny notes app for app-store install tests.",
            "publisher": "versy",
            "minimum_core_version": "0.1.0",
            "distribution": {"mode": "sealed", "source_access": "none"},
            "capabilities": {"mcp_tools": [], "cli_commands": [], "skills": [], "views": []},
            "entrypoints": {"hooks": {}},
            "storage": {
                "storage_kind": "json",
                "data_schema_version": "1",
                "primary_paths": ["data/notes/state.json"],
                "indices": None,
                "supports_export": False,
                "supports_import": False,
                "supports_migrations": False,
            },
            "compatibility": {"workspace_modes": ["sandbox", "full-access"]},
            "hook_timeouts": {
                "install_seconds": 60,
                "upgrade_seconds": 120,
                "migrate_seconds": 300,
                "export_seconds": 120,
                "import_seconds": 120,
                "validate_after_import_seconds": 60,
                "repair_after_import_seconds": 180,
                "health_check_seconds": 30,
            },
            "lifecycle": {
                "install": False,
                "upgrade": False,
                "uninstall": False,
                "migrate": False,
                "export": False,
                "import": False,
                "validate_after_import": False,
                "repair_after_import": False,
                "rebuild": False,
                "health_check": False,
            },
            "health_contract": {"mode": "none", "degraded_on_failure": True},
            "failure_semantics": {
                "install_failure": "block_activation",
                "migrate_failure": "preserve_data_mark_unhealthy",
                "import_failure": "preserve_payload_mark_failed",
            },
            "rollback_support": {"bundle": False, "data": False, "repair_only": False},
        }
        app_root.mkdir(parents=True)
        (app_root / "app_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")

    def write_workspace_local_app_contract(
        self,
        app_root: Path,
        *,
        frontend: bool = False,
        platform_roles: list[str] | None = None,
    ) -> None:
        contract = {
            "app_id": "local-notes",
            "contract_version": "1.0",
            "name": "Local Notes",
            "version": "0.1.0",
            "description": "Workspace-local notes app.",
            "publisher": "workspace",
            "minimum_core_version": "0.1.0",
            "distribution": {"mode": "workspace_local", "source_access": "editable"},
            **({"visibility": {"platform_roles": platform_roles}} if platform_roles is not None else {}),
            "capabilities": {"mcp_tools": [], "cli_commands": [], "skills": [], "views": ["main"] if frontend else []},
            "entrypoints": {"frontend": "frontend/dist", "hooks": {}} if frontend else {"hooks": {}},
            "storage": {
                "storage_kind": "json",
                "data_schema_version": "1",
                "primary_paths": ["data/local-notes/state.json"],
                "indices": None,
                "supports_export": False,
                "supports_import": False,
                "supports_migrations": False,
            },
            "compatibility": {"workspace_modes": ["sandbox", "full-access"]},
            "hook_timeouts": {
                "install_seconds": 60,
                "upgrade_seconds": 120,
                "migrate_seconds": 300,
                "export_seconds": 120,
                "import_seconds": 120,
                "validate_after_import_seconds": 60,
                "repair_after_import_seconds": 180,
                "health_check_seconds": 30,
            },
            "lifecycle": {
                "install": False,
                "upgrade": False,
                "uninstall": False,
                "migrate": False,
                "export": False,
                "import": False,
                "validate_after_import": False,
                "repair_after_import": False,
                "rebuild": False,
                "health_check": False,
            },
            "health_contract": {"mode": "none", "degraded_on_failure": True},
            "failure_semantics": {
                "install_failure": "block_activation",
                "migrate_failure": "preserve_data_mark_unhealthy",
                "import_failure": "preserve_payload_mark_failed",
            },
            "rollback_support": {"bundle": False, "data": False, "repair_only": False},
        }
        app_root.mkdir(parents=True)
        (app_root / "app_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
        if frontend:
            dist_root = app_root / "frontend" / "dist"
            dist_root.mkdir(parents=True)
            (dist_root / "index.html").write_text("<h1>Local Notes</h1>", encoding="utf-8")

    def start_catalog_server(self) -> tuple[str, tempfile.TemporaryDirectory]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        http_root = Path(temp_dir.name)
        bundle_source = http_root / "bundle-source" / "notes"
        self.write_remote_app_contract(bundle_source)
        artifact_path = http_root / "artifact.tar.gz"
        with tarfile.open(artifact_path, "w:gz") as archive:
            archive.add(bundle_source, arcname="notes")
        checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

        catalog: dict[str, object] = {}

        class CatalogHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/api/apps":
                    body = json.dumps(catalog).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/api/apps/notes/versions/1.0.0/artifact":
                    body = artifact_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, _format: str, *_args) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), CatalogHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        base_url = f"http://127.0.0.1:{server.server_port}"

        catalog.update({
            "count": 1,
            "items": [
                {
                    "app_id": "notes",
                    "name": "Notes",
                    "description": "Tiny notes app for app-store install tests.",
                    "publisher": "versy",
                    "latest_version": "1.0.0",
                    "surfaces": [],
                    "versions": [
                        {
                            "app_id": "notes",
                            "name": "Notes",
                            "version": "1.0.0",
                            "description": "Tiny notes app for app-store install tests.",
                            "publisher": "versy",
                            "status": "published",
                            "sha256": checksum,
                            "artifact_download_url": f"{base_url}/api/apps/notes/versions/1.0.0/artifact",
                            "surfaces": [],
                        }
                    ],
                }
            ],
        })
        return base_url, temp_dir

    def test_contract_declares_app_store_surfaces(self) -> None:
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1] / "apps" / "app-store")

        self.assertEqual(parsed.app_id, "app-store")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertIn("maverick_app_store", parsed.contract.capabilities.mcp_tools)
        self.assertIn("app_store_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["app-store"])
        self.assertIn("installed_app", {item.entity_type for item in parsed.contract.capabilities.reference_entities})
        self.assertEqual(parsed.contract.capabilities.skills, [])
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        self.assertEqual(widgets["app-shortcuts"].host, "base-shell")
        self.assertEqual(widgets["app-shortcuts"].content_kinds, ["shell.sidebar.apps"])
        self.assertEqual(widgets["app-shortcuts"].frontend.mount, "frontend/dist/widgets/app-shortcuts")
        self.assertTrue(
            (Path(__file__).resolve().parents[1] / "apps" / "app-store" / "frontend" / "dist" / "widgets" / "app-shortcuts" / "index.html").is_file()
        )

    def test_bootstrap_installs_app_store_and_exposes_surfaces(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        self.assertIn("app-store", {binding.app_id for binding in bindings})
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "app-store" / "state.json").is_file())

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.app-store.maverick_app_store", [tool.tool_name for tool in tools])
        self.assertIn("app.app-store.app-store", [command.command_id for command in commands])

    def test_frontend_is_mounted_as_an_app(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status, payload, headers = self.invoke(app, path="/apps/app-store/")

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"App Store", payload)
        self.assertIn(b"Catalog apps", payload)
        self.assertIn(b"Installed apps", payload)
        self.assertIn(b"Local apps", payload)

    def test_sidebar_app_shortcuts_widget_is_discoverable_and_mounted(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(
            app,
            path="/api/apps/widgets",
            cookie=cookie,
        )
        self.assertEqual(status, 200)

        status_filtered, filtered, _filtered_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=base-shell&content_kind=shell.sidebar.apps",
            cookie=cookie,
        )
        if isinstance(filtered, bytes):
            filtered = json.loads(filtered.decode("utf-8"))
        status_widget, widget_body, widget_headers = self.invoke(
            app,
            path="/api/apps/widgets/app-store/app-shortcuts/frontend/",
            cookie=cookie,
        )

        self.assertEqual(status_filtered, 200)
        self.assertEqual(filtered["items"][0]["owner_app_id"], "app-store")
        self.assertEqual(filtered["items"][0]["widget_id"], "app-shortcuts")
        self.assertEqual(filtered["items"][0]["frontend_mount"], "/api/apps/widgets/app-store/app-shortcuts/frontend/")
        self.assertEqual(status_widget, 200)
        self.assertIn("text/html", widget_headers["Content-Type"])
        self.assertIn(b"App shortcuts", widget_body)

    def test_catalog_and_install_require_maverick_authentication(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        catalog_status, catalog_payload, _catalog_headers = self.invoke(app, path="/api/app-store/apps")
        install_status, install_payload, _install_headers = self.invoke(
            app,
            path="/api/app-store/install",
            method="POST",
            body={"app_id": "notes", "workspace_ids": ["default"]},
        )

        self.assertEqual(catalog_status, 401)
        self.assertEqual(catalog_payload["error"], "authentication_required")
        self.assertEqual(install_status, 401)
        self.assertEqual(install_payload["error"], "authentication_required")

    def test_catalog_api_hides_admin_only_apps_from_members(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)
        catalog = {
            "count": 2,
            "items": [
                {"app_id": "notes", "name": "Notes"},
                {"app_id": "admin-panel", "name": "Admin Panel", "visibility": {"platform_roles": ["admin"]}},
            ],
        }

        with patch("core.api.app_store_api.fetch_remote_catalog", return_value=catalog):
            admin_status, admin_payload, _admin_headers = self.invoke(app, path="/api/app-store/apps", cookie=admin_cookie)
            member_status, member_payload, _member_headers = self.invoke(app, path="/api/app-store/apps", cookie=member_cookie)

        self.assertEqual(admin_status, 200)
        self.assertEqual(member_status, 200)
        self.assertIn("admin-panel", {item["app_id"] for item in admin_payload["items"]})
        self.assertNotIn("admin-panel", {item["app_id"] for item in member_payload["items"]})
        self.assertEqual(member_payload["count"], 1)

    def test_installations_api_reports_enabled_builtin_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=cookie)

        self.assertEqual(status, 200)
        installed = {(item["workspace_id"], item["app_id"]) for item in payload["items"]}
        self.assertIn(("default", "agents"), installed)
        self.assertIn(("default", "app-store"), installed)
        self.assertIn(("default", "base-shell"), installed)
        self.assertIn(("default", "chat"), installed)

    def test_member_installations_api_hides_admin_only_installed_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=member_cookie)

        self.assertEqual(status, 200)
        installed_app_ids = {item["app_id"] for item in payload["items"]}
        self.assertIn("chat", installed_app_ids)
        self.assertNotIn("user-admin", installed_app_ids)

    def test_installations_api_reports_workspace_local_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root)
        register_workspace_local_app_project_from_contract(
            state.app_store,
            workspace_id="default",
            project_root=str(local_app_root),
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=cookie)

        self.assertEqual(status, 200)
        self.assertIn("local_apps", payload)
        local_apps = {(item["workspace_id"], item["app_id"], item["status"]) for item in payload["local_apps"]}
        self.assertIn(("default", "local-notes", "uninstalled"), local_apps)

    def test_member_installations_api_hides_admin_only_local_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, platform_roles=["admin"])
        register_workspace_local_app_project_from_contract(
            state.app_store,
            workspace_id="default",
            project_root=str(local_app_root),
        )
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)

        admin_status, admin_payload, _admin_headers = self.invoke(app, path="/api/app-store/installations", cookie=admin_cookie)
        member_status, member_payload, _member_headers = self.invoke(app, path="/api/app-store/installations", cookie=member_cookie)

        self.assertEqual(admin_status, 200)
        self.assertEqual(member_status, 200)
        self.assertIn("local-notes", {item["app_id"] for item in admin_payload["local_apps"]})
        self.assertNotIn("local-notes", {item["app_id"] for item in member_payload["local_apps"]})

    def test_installations_api_discovers_workspace_local_app_projects_on_disk(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=cookie)

        self.assertEqual(status, 200)
        local_apps = {(item["workspace_id"], item["app_id"], item["status"]) for item in payload["local_apps"]}
        self.assertIn(("default", "local-notes", "uninstalled"), local_apps)
        saved = state.app_store.get_workspace_local_app_project(workspace_id="default", app_id="local-notes")
        self.assertEqual(saved.project_root, str(local_app_root))

    def test_local_app_discovery_persists_across_platform_bootstrap(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        self.invoke(app, path="/api/app-store/installations", cookie=cookie)

        restarted_state = bootstrap_platform_state(start_path=repo_root)

        saved = restarted_state.app_store.get_workspace_local_app_project(workspace_id="default", app_id="local-notes")
        self.assertEqual(saved.project_root, str(local_app_root))

    def test_authenticated_install_local_app_enables_workspace_mount(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        install_status, install, _install_headers = self.invoke(
            app,
            path="/api/app-store/install-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        mount_status, mount_body, mount_headers = self.invoke(app, path="/apps/local-notes/", cookie=cookie)

        binding = state.app_store.get_workspace_app_binding(workspace_id="default", app_id="local-notes")
        self.assertEqual(install_status, 201)
        self.assertEqual(install["source_kind"], "workspace_local_project")
        self.assertEqual(binding.status, "enabled")
        self.assertEqual(binding.source_kind, "workspace_local_project")
        self.assertEqual(mount_status, 200)
        self.assertIn("text/html", mount_headers["Content-Type"])
        self.assertIn(b"Local Notes", mount_body)

    def test_app_store_backend_owns_pinned_sidebar_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_initial, initial, _initial_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.list"},
            cookie=cookie,
        )
        status_toggle, toggled, _toggle_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.toggle", "app_id": "agents"},
            cookie=cookie,
        )

        self.assertEqual(status_initial, 200)
        self.assertEqual(initial["pinned_apps"], ["chat"])
        self.assertEqual(status_toggle, 200)
        self.assertEqual(toggled["state"]["pinned_apps"], ["chat", "agents"])

    def test_app_store_install_hook_does_not_reset_pinned_apps_on_bootstrap(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.toggle", "app_id": "agents"},
            cookie=cookie,
        )

        restarted_state = bootstrap_platform_state(start_path=repo_root)
        restarted_app = PlatformHost(restarted_state, start_path=repo_root)
        restarted_cookie = self.login(restarted_app)
        status, payload, _headers = self.invoke(
            restarted_app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.list"},
            cookie=restarted_cookie,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["pinned_apps"], ["chat", "agents"])

    def test_authenticated_install_downloads_verifies_and_enables_remote_app(self) -> None:
        repo_root = self.make_repo_root()
        base_url, _temp_dir = self.start_catalog_server()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK_APP_STORE_URL": base_url}):
            catalog_status, catalog, _catalog_headers = self.invoke(app, path="/api/app-store/apps", cookie=cookie)
            install_status, install, _install_headers = self.invoke(
                app,
                path="/api/app-store/install",
                method="POST",
                body={"app_id": "notes", "version": "1.0.0", "workspace_ids": ["default"]},
                cookie=cookie,
            )

        binding = state.app_store.get_workspace_app_binding(workspace_id="default", app_id="notes")
        source = state.app_store.get_app_source("app-store:notes:1.0.0")

        self.assertEqual(catalog_status, 200)
        self.assertEqual(catalog["items"][0]["app_id"], "notes")
        self.assertEqual(install_status, 201)
        self.assertEqual(install["app"]["app_id"], "notes")
        self.assertEqual(binding.status, "enabled")
        self.assertEqual(binding.active_version, "1.0.0")
        self.assertEqual(source.source_kind, "external_bundle")
        self.assertTrue((repo_root / "apps" / "_bundles" / "notes" / "1.0.0" / "app_contract.json").is_file())

    def test_authenticated_uninstall_removes_selected_workspace_binding(self) -> None:
        repo_root = self.make_repo_root()
        base_url, _temp_dir = self.start_catalog_server()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK_APP_STORE_URL": base_url}):
            self.invoke(
                app,
                path="/api/app-store/install",
                method="POST",
                body={"app_id": "notes", "version": "1.0.0", "workspace_ids": ["default"]},
                cookie=cookie,
            )
            uninstall_status, uninstall, _headers = self.invoke(
                app,
                path="/api/app-store/uninstall",
                method="POST",
                body={"app_id": "notes", "workspace_ids": ["default"]},
                cookie=cookie,
            )
            installations_status, installations, _installations_headers = self.invoke(
                app,
                path="/api/app-store/installations",
                cookie=cookie,
            )

        self.assertEqual(uninstall_status, 200)
        self.assertEqual(uninstall["status"], "uninstalled")
        with self.assertRaises(WorkspaceAppBindingNotFoundError):
            state.app_store.get_workspace_app_binding(workspace_id="default", app_id="notes")
        self.assertEqual(installations_status, 200)
        self.assertNotIn("notes", [item["app_id"] for item in installations["items"]])

    def test_authenticated_uninstall_removes_installed_platform_app_binding(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        uninstall_status, uninstall, _headers = self.invoke(
            app,
            path="/api/app-store/uninstall",
            method="POST",
            body={"app_id": "agents", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        installations_status, installations, _installations_headers = self.invoke(
            app,
            path="/api/app-store/installations",
            cookie=cookie,
        )

        self.assertEqual(uninstall_status, 200)
        self.assertEqual(uninstall["status"], "uninstalled")
        with self.assertRaises(WorkspaceAppBindingNotFoundError):
            state.app_store.get_workspace_app_binding(workspace_id="default", app_id="agents")
        self.assertEqual(installations_status, 200)
        self.assertNotIn("agents", [item["app_id"] for item in installations["items"]])

    def test_authenticated_uninstall_removes_workspace_local_app_binding(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        self.invoke(
            app,
            path="/api/app-store/install-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )

        uninstall_status, uninstall, _headers = self.invoke(
            app,
            path="/api/app-store/uninstall",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        installations_status, installations, _installations_headers = self.invoke(
            app,
            path="/api/app-store/installations",
            cookie=cookie,
        )

        self.assertEqual(uninstall_status, 200)
        self.assertEqual(uninstall["status"], "uninstalled")
        with self.assertRaises(WorkspaceAppBindingNotFoundError):
            state.app_store.get_workspace_app_binding(workspace_id="default", app_id="local-notes")
        self.assertEqual(installations_status, 200)
        local_apps = {(item["workspace_id"], item["app_id"], item["status"]) for item in installations["local_apps"]}
        self.assertIn(("default", "local-notes", "uninstalled"), local_apps)

    def test_authenticated_delete_local_app_removes_project_binding_and_data(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        local_data_root = repo_root / "workspaces" / "default" / "data" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        self.invoke(
            app,
            path="/api/app-store/install-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        (local_data_root / "state.json").write_text("{}", encoding="utf-8")

        delete_status, deleted, _headers = self.invoke(
            app,
            path="/api/app-store/delete-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        installations_status, installations, _installations_headers = self.invoke(
            app,
            path="/api/app-store/installations",
            cookie=cookie,
        )

        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted["status"], "deleted")
        self.assertFalse(local_app_root.exists())
        self.assertFalse(local_data_root.exists())
        with self.assertRaises(WorkspaceAppBindingNotFoundError):
            state.app_store.get_workspace_app_binding(workspace_id="default", app_id="local-notes")
        with self.assertRaises(WorkspaceLocalAppProjectNotFoundError):
            state.app_store.get_workspace_local_app_project(workspace_id="default", app_id="local-notes")
        self.assertEqual(installations_status, 200)
        self.assertNotIn("local-notes", [item["app_id"] for item in installations["local_apps"]])

    def test_app_lifecycle_cli_exposes_install_uninstall_and_remove_when_available(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        local_data_root = repo_root / "workspaces" / "default" / "data" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        context = CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode=None,
        )

        initial_commands = {
            command.command_id
            for command in list_core_cli_commands(
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )
        }
        install_result = run_core_cli_command(
            command_id="app.local-notes.install",
            context=context,
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        installed_commands = {
            command.command_id
            for command in list_core_cli_commands(
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )
        }
        uninstall_result = run_core_cli_command(
            command_id="app.agents.uninstall",
            context=context,
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )
        remove_result = run_core_cli_command(
            command_id="app.local-notes.remove",
            context=context,
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertIn("app.agents.install", initial_commands)
        self.assertIn("app.agents.uninstall", initial_commands)
        self.assertNotIn("app.agents.remove", initial_commands)
        self.assertIn("app.local-notes.install", initial_commands)
        self.assertIn("app.local-notes.remove", initial_commands)
        self.assertNotIn("app.local-notes.uninstall", initial_commands)
        self.assertEqual(install_result["status"], "installed")
        self.assertIn("app.local-notes.uninstall", installed_commands)
        self.assertEqual(uninstall_result["status"], "uninstalled")
        self.assertEqual(remove_result["status"], "removed")
        self.assertFalse(local_app_root.exists())
        self.assertFalse(local_data_root.exists())

    def test_mcp_and_cli_can_read_catalog(self) -> None:
        repo_root = self.make_repo_root()
        base_url, _temp_dir = self.start_catalog_server()
        state = bootstrap_platform_state(start_path=repo_root)

        with patch.dict("os.environ", {"MAVERICK_APP_STORE_URL": base_url}):
            mcp_payload = call_mcp_tool(
                tool_name="app.app-store.maverick_app_store",
                context=McpInvocationContext(
                    caller_kind="sandbox_agent",
                    workspace_id="default",
                    agent_id="tester",
                    effective_mode="sandbox",
                ),
                arguments={"action": "catalog"},
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )
            cli_payload = run_core_cli_command(
                command_id="app.app-store.app-store",
                context=CliInvocationContext(
                    caller_kind="operator",
                    workspace_id="default",
                    agent_id=None,
                    effective_mode=None,
                ),
                arguments={"action": "catalog"},
                app_store=state.app_store,
                workspace_id="default",
                start_path=repo_root,
            )

        self.assertEqual(mcp_payload["status_code"], 200)
        self.assertEqual(mcp_payload["items"][0]["app_id"], "notes")
        self.assertEqual(cli_payload["status_code"], 200)
        self.assertEqual(cli_payload["items"][0]["app_id"], "notes")


if __name__ == "__main__":
    unittest.main()
