"""Tests for the Maverick App Store app and install API."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from queue import Empty
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from threading import Thread
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.apps.errors import AppLifecycleError, WorkspaceAppBindingNotFoundError, WorkspaceLocalAppProjectNotFoundError
from core.apps.remote_store import RemoteAppVersion, _read_url_bytes, _validated_artifact_url, stage_remote_app_bundle
from core.apps.service import register_app_source_from_contract, register_workspace_local_app_project_from_contract
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool, list_mcp_tools
from tests.support.markers import full_test, integration_test
from tests.support.repo import make_temp_repo_root, link_app_sources


class AppStoreAppTestCase(unittest.TestCase):
    """Verify app-store surfaces and authenticated install behavior."""

    def make_repo_root(self) -> Path:
        repo_root = make_temp_repo_root(self)
        link_app_sources(repo_root, ["app-store"])
        self.write_remote_app_contract(repo_root / "apps" / "base-shell", app_id="base-shell", name="Base Shell", frontend_role="supporting")
        self.write_remote_app_contract(repo_root / "apps" / "chat", app_id="chat", name="Chat", frontend_role="workspace")
        self.write_remote_app_contract(repo_root / "apps" / "agents", app_id="agents", name="Agents", frontend_role="workspace")
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

    def login(self, app, *, username: str | None = None, password: str | None = None) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": username or os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": password or os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def create_user(
        self,
        app,
        admin_cookie: str,
        *,
        username: str,
        password: str,
        platform_role: str = "member",
        workspace_role: str = "member",
    ) -> str:
        status_user, user, _user_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": username, "password": password, "platform_role": platform_role},
            cookie=admin_cookie,
        )
        self.assertEqual(status_user, 201)
        status_workspace, _workspace, _workspace_headers = self.invoke(
            app,
            path=f"/api/admin/users/{user['user_id']}/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": workspace_role}]},
            cookie=admin_cookie,
        )
        self.assertEqual(status_workspace, 200)
        return self.login(app, username=username, password=password)

    def create_member_user(self, app, admin_cookie: str, *, username: str = "viewer") -> str:
        return self.create_user(
            app,
            admin_cookie,
            username=username,
            password="memberpass",
            platform_role="member",
            workspace_role="member",
        )

    def write_remote_app_contract(
        self,
        app_root: Path,
        *,
        app_id: str = "notes",
        name: str = "Notes",
        platform_roles: list[str] | None = None,
        frontend_role: str = "none",
    ) -> None:
        has_frontend = frontend_role in {"workspace", "supporting"}
        contract = {
            "app_id": app_id,
            "contract_version": "1.0",
            "name": name,
            "version": "1.0.0",
            "description": "Tiny notes app for app-store install tests.",
            "publisher": "maverick",
            "minimum_core_version": "0.1.0",
            "provides": [],
            "requires": [],
            "distribution": {"mode": "sealed", "source_access": "none"},
            **({"visibility": {"platform_roles": platform_roles}} if platform_roles is not None else {}),
            "presentation": {"frontend_role": frontend_role},
            "capabilities": {"mcp_tools": [], "cli_commands": [], "skills": [], "views": ["main"] if has_frontend else []},
            "entrypoints": {"frontend": "frontend/dist", "hooks": {}} if has_frontend else {"hooks": {}},
            "storage": {
                "storage_kind": "json",
                "data_schema_version": "1",
                "primary_paths": [f"data/{app_id}/state.json"],
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
        if has_frontend:
            frontend_root = app_root / "frontend" / "dist"
            frontend_root.mkdir(parents=True)
            (frontend_root / "index.html").write_text(f"<h1>{name}</h1>", encoding="utf-8")
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
            "provides": [],
            "requires": [],
            "distribution": {"mode": "workspace_local", "source_access": "editable"},
            **({"visibility": {"platform_roles": platform_roles}} if platform_roles is not None else {}),
            "presentation": {"frontend_role": "workspace" if frontend else "none"},
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
                    "publisher": "maverick",
                    "latest_version": "1.0.0",
                    "surfaces": [],
                    "versions": [
                        {
                            "app_id": "notes",
                            "name": "Notes",
                            "version": "1.0.0",
                            "description": "Tiny notes app for app-store install tests.",
                            "publisher": "maverick",
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
        parsed = parse_app_contract_file(Path(__file__).resolve().parents[1])

        self.assertEqual(parsed.app_id, "app-store")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertEqual(parsed.contract.entrypoints.backend, "backend/app_backend.py")
        self.assertIn("maverick_app_store", parsed.contract.capabilities.mcp_tools)
        self.assertIn("app_store_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertIn("app_store_reference_manifest", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.cli_commands, ["app-store"])
        self.assertIn("installed_app", {item.entity_type for item in parsed.contract.capabilities.reference_entities})
        self.assertEqual(parsed.contract.capabilities.skills, ["app-store-ops"])
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "app-store")
        self.assertEqual(
            [item.action for item in parsed.contract.capabilities.view_surfaces[0].state_actions],
            ["view_filter", "set_view_filter", "set_custom_view", "clear_custom_view"],
        )
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        self.assertEqual(widgets["app-shortcuts"].host, "base-shell")
        self.assertEqual(widgets["app-shortcuts"].content_kinds, ["shell.sidebar.apps", "shell.sidebar.primary"])
        self.assertEqual(widgets["app-shortcuts"].frontend.mount, "frontend/dist/widgets/app-shortcuts")

    def test_app_store_backend_does_not_fetch_remote_catalog_directly(self) -> None:
        service_source = (Path(__file__).resolve().parents[1] / "backend" / "service.py").read_text(encoding="utf-8")

        self.assertNotIn("urlopen", service_source)
        self.assertNotIn("urllib.request", service_source)
        self.assertNotIn("MAVERICK_APP_STORE_URL", service_source)
        self.assertNotIn("MAVERICK_PUBLIC_APP_STORE_URL", service_source)
        self.assertTrue(
            (Path(__file__).resolve().parents[1] / "frontend" / "dist" / "widgets" / "app-shortcuts" / "index.html").is_file()
        )

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_frontend_is_mounted_as_an_app(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, headers = self.invoke(app, path="/apps/app-store/", cookie=cookie)

        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"App Store", payload)
        self.assertIn(b"catalog-folder-section", payload)
        self.assertIn(b"stalePinsSection", payload)
        self.assertNotIn(b"Most Popular Apps", payload)
        self.assertNotIn(b"Manage Apps", payload)
        self.assertNotIn(b"Server Apps", payload)
        self.assertNotIn(b"Installed Apps", payload)
        self.assertNotIn(b"Local Apps", payload)
        self.assertIn(b'detail-header store-header', payload)
        self.assertIn(b'detail-title-separator', payload)
        self.assertNotIn(b'today-heading', payload)
        self.assertNotIn(b'todayLabel', payload)
        self.assertIn(b'type="module"', payload)
        self.assertIn(b"/apps/app-store/assets/app-", payload)
        self.assertNotIn(b"?v=", payload)

    def test_frontend_dist_separates_server_promotion_from_public_submission(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        frontend_js = (app_root / "frontend" / "src" / "assets" / "main.js").read_text(encoding="utf-8")
        frontend_html = (app_root / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Promote to server app", frontend_js)
        self.assertIn("Request public publication", frontend_js)
        self.assertIn("public_submissions.create", frontend_js)
        self.assertIn("public_submissions.read", frontend_js)
        self.assertIn("app-modal__form", frontend_js)
        self.assertIn("A public UUID will be generated", frontend_js)
        self.assertIn("Update public app", frontend_js)
        self.assertIn("publication_mode", frontend_js)
        self.assertIn("Forkable", frontend_js)
        self.assertNotIn("ZIP artifact", frontend_js)
        self.assertNotIn("Existing public UUID", frontend_js)
        self.assertNotIn("Publication Requests", frontend_html)
        self.assertNotIn('data-tab="public"', frontend_html)
        self.assertIn('<div class="app-modal__body"', frontend_html)
        self.assertIn("/api/app-store/install-server", frontend_js)

    def test_frontend_dist_uses_material_app_icons(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        icon_js = (app_root / "frontend" / "src" / "assets" / "app-icons.js").read_text(encoding="utf-8")
        frontend_js = (app_root / "frontend" / "src" / "assets" / "main.js").read_text(encoding="utf-8")
        frontend_css = (app_root / "frontend" / "src" / "assets" / "main.css").read_text(encoding="utf-8")

        self.assertIn('"storage": "cloud"', icon_js)
        self.assertIn('"app-store": "storefront"', icon_js)
        self.assertIn('"browser": "language"', icon_js)
        self.assertIn('"design-studio": "design_services"', icon_js)
        self.assertIn('"mail": "mail"', icon_js)
        self.assertIn('"speech": "record_voice_over"', icon_js)
        self.assertIn("mergeCatalogAndServerApps", frontend_js)
        self.assertIn("state.apps = mergeCatalogAndServerApps(state.catalogApps, state.serverApps)", frontend_js)
        self.assertIn('renderIcon(app, "app-row-icon", installation)', frontend_js)
        self.assertIn("frontendAvailabilityLabel", frontend_js)
        self.assertIn("isFrontendLaunchable", frontend_js)
        self.assertIn("function canTogglePinnedApp", frontend_js)
        self.assertIn("return installState.installedCount > 0 && installState.launchableCount > 0", frontend_js)
        self.assertIn("disabled: isPending || !canTogglePinnedApp(app, installState)", frontend_js)
        self.assertIn("function stalePinnedAppIds", frontend_js)
        self.assertIn("function renderStalePinnedShortcuts", frontend_js)
        self.assertIn("stale-pin-remove", frontend_js)
        self.assertIn(".stale-pins-section", frontend_css)
        self.assertIn("is-supporting-frontend", icon_js)
        self.assertIn("is-non-launchable", icon_js)
        self.assertIn(".app-row-icon.is-glyph.is-non-launchable", frontend_css)
        self.assertIn(".app-row-icon.is-glyph.is-supporting-frontend", frontend_css)
        self.assertNotIn("slice(0, 1).toUpperCase()", frontend_js)
        self.assertIn(".app-row-icon.is-glyph", frontend_css)

    def test_frontend_dist_groups_app_folders_by_all_declared_surfaces(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        folder_data_js = (app_root / "frontend" / "src" / "assets" / "app-folder-data.js").read_text(encoding="utf-8")
        folder_js = (app_root / "frontend" / "src" / "assets" / "app-folders.js").read_text(encoding="utf-8")
        folder_css = (app_root / "frontend" / "src" / "assets" / "app-folders.css").read_text(encoding="utf-8")
        frontend_js = (app_root / "frontend" / "src" / "assets" / "main.js").read_text(encoding="utf-8")
        frontend_css = (app_root / "frontend" / "src" / "assets" / "main.css").read_text(encoding="utf-8")
        lightbox_css = (app_root / "frontend" / "src" / "assets" / "app-folder-lightbox.css").read_text(encoding="utf-8")
        frontend_html = (app_root / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")

        self.assertIn("function folderIdsForApp", folder_data_js)
        self.assertIn("Platform Extensions", folder_data_js)
        self.assertIn("supporting_frontend", folder_data_js)
        self.assertIn("No App View", (app_root / "frontend" / "src" / "assets" / "app-folder-lightbox.js").read_text(encoding="utf-8"))
        self.assertIn("matchedFolderIds", folder_data_js)
        self.assertIn("folderIdsForApp(app, activeSurface).forEach", folder_data_js)
        self.assertIn("shouldUseTwoStepFolderOpen", folder_js)
        self.assertIn("primeFolderFan", folder_js)
        self.assertIn('card.classList.add("is-hovered")', folder_js)
        self.assertIn('card.classList.contains("is-touch-primed")', folder_js)
        self.assertIn("renderPreviewIcon", folder_js)
        self.assertIn("app-folder-preview-icon", folder_js)
        self.assertIn("app-folder-preview-icon", folder_css)
        self.assertIn("folderAppCount", folder_js)
        self.assertNotIn("appImage", folder_js)
        self.assertNotIn("app-folder-preview-shade", folder_js)
        self.assertNotIn("app-folder-preview-shade", folder_css)
        self.assertNotIn(".app-folder-preview img", folder_css)
        self.assertNotIn("folderIdForApp", folder_data_js)
        self.assertNotIn("renderCount", folder_data_js)
        self.assertNotIn("renderCount", folder_js)
        self.assertNotIn("Hover", folder_js)
        self.assertNotIn("Empty", folder_js)
        self.assertNotIn("apps in folders", frontend_js)
        self.assertNotIn("refreshButton", frontend_js)
        self.assertNotIn("refreshButton", frontend_html)
        self.assertNotIn("statusText", frontend_js)
        self.assertNotIn("statusText", frontend_html)
        self.assertNotIn("action-group", frontend_html)
        self.assertNotIn(".action-group", frontend_css)
        self.assertNotIn(".status-pill", frontend_css)
        self.assertNotIn(".icon-button", frontend_css)
        card_rule = re.search(r"\.app-folder-card \{(?P<body>.*?)\n\}", folder_css, re.DOTALL)
        self.assertIsNotNone(card_rule)
        self.assertNotIn("overflow: hidden", card_rule.group("body"))
        heavy_weight_rules = []
        for name, css in {
            "main.css": frontend_css,
            "app-folders.css": folder_css,
            "app-folder-lightbox.css": lightbox_css,
        }.items():
            for match in re.finditer(r"(?P<selectors>[^{}]+)\{[^{}]*font-weight:\s*(?P<weight>bold|[789][0-9]{2})\s*;", css, re.DOTALL):
                heavy_weight_rules.append((name, " ".join(match.group("selectors").split()), match.group("weight")))
        self.assertEqual(heavy_weight_rules, [("app-folder-lightbox.css", ".folder-lightbox-copy h3", "900")])

    def test_frontend_presentation_helper_drives_foldering_and_installed_launchability(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        script = f"""
const fs = require("fs");
const vm = require("vm");
const root = {json.dumps(str(app_root))};
function createElement(tagName) {{
  return {{
    tagName,
    children: [],
    className: "",
    textContent: "",
    classList: {{
      classes: [],
      add(name) {{ this.classes.push(name); }},
    }},
    setAttribute() {{}},
    append(...nodes) {{ this.children.push(...nodes); }},
  }};
}}
const context = {{ window: {{}}, document: {{ createElement }} }};
vm.createContext(context);
vm.runInContext(fs.readFileSync(`${{root}}/frontend/src/assets/frontend-presentation.js`, "utf8"), context);
vm.runInContext(fs.readFileSync(`${{root}}/frontend/src/assets/app-icons.js`, "utf8"), context);
vm.runInContext(fs.readFileSync(`${{root}}/frontend/src/assets/app-folder-data.js`, "utf8"), context);
const presentation = context.window.MaverickFrontendPresentation;
const icons = context.window.MaverickAppIcons;
const foldersApi = context.window.MaverickAppFolderData;
function assert(condition, message) {{
  if (!condition) throw new Error(message);
}}
const supporting = presentation.frontendPresentation({{
  app_id: "developer-kit",
  frontend_role: "supporting",
  surfaces: [],
}});
assert(supporting.launchable === false, "supporting apps are not launchable");
assert(supporting.surfaces.includes("supporting_frontend"), "supporting role synthesizes supporting_frontend");
const folders = foldersApi.buildFolders([{{
  app_id: "developer-kit",
  frontend_role: "supporting",
  surfaces: [],
}}], "");
const platformExtensions = folders.find((folder) => folder.id === "supporting_frontend");
assert(platformExtensions.apps.some((app) => app.app_id === "developer-kit"), "supporting apps land in Platform Extensions");
const installed = presentation.frontendPresentation(
  {{ app_id: "reporter", frontend_role: "workspace", frontend_launchable: true, surfaces: ["frontend"] }},
  {{ app_id: "reporter", frontend_role: "supporting", frontend_launchable: false, surfaces: [] }},
);
assert(installed.launchable === false, "installed binding launchability overrides catalog latest");
assert(installed.role === "supporting", "installed binding role overrides catalog latest");
assert(icons.glyphName({{ app_id: "browser", frontend_role: "workspace", surfaces: ["frontend"] }}) === "language", "browser app uses material language icon");
assert(icons.glyphName({{ app_id: "design-studio", frontend_role: "workspace", surfaces: ["frontend"] }}) === "design_services", "Design Studio uses material design services icon");
assert(icons.glyphName({{ app_id: "mail", frontend_role: "workspace", surfaces: ["frontend"] }}) === "mail", "mail app uses material mail icon");
const icon = icons.renderIcon(
  {{ app_id: "reporter", frontend_role: "workspace", frontend_launchable: true, surfaces: ["frontend"] }},
  "test-icon",
  {{ app_id: "reporter", frontend_role: "supporting", frontend_launchable: false, surfaces: [] }},
);
assert(icon.classList.classes.includes("is-supporting-frontend"), "icons use installed binding role");
assert(icon.classList.classes.includes("is-non-launchable"), "icons use installed binding launchability");
"""
        result = subprocess.run(["node", "-e", script], check=False, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frontend_dist_has_skeleton_loading_states(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        frontend_js = (app_root / "frontend" / "src" / "assets" / "main.js").read_text(encoding="utf-8")
        frontend_css = (app_root / "frontend" / "src" / "assets" / "main.css").read_text(encoding="utf-8")
        folder_css = (app_root / "frontend" / "src" / "assets" / "app-folders.css").read_text(encoding="utf-8")
        shortcut_js = (app_root / "frontend" / "src" / "widgets" / "app-shortcuts" / "main.js").read_text(encoding="utf-8")
        shortcut_css = (app_root / "frontend" / "src" / "widgets" / "app-shortcuts" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("renderLoading", frontend_js)
        self.assertIn("renderFolderGridSkeleton", frontend_js)
        self.assertIn("app-folder-card--skeleton", frontend_js)
        self.assertIn('aria-busy", "true"', frontend_js)
        self.assertIn("width: min(100%, 1440px)", frontend_css)
        self.assertIn("max-width: 1440px", frontend_css)
        self.assertIn("store-loading-skeleton-shimmer", frontend_css)
        self.assertIn(".app-folder-grid--skeleton", folder_css)
        self.assertIn(".store-loading-skeleton__line--folder-title", folder_css)
        self.assertIn("renderSkeleton", shortcut_js)
        self.assertIn("app-shortcuts__row--skeleton", shortcut_js)
        self.assertIn("app-shortcuts-skeleton-shimmer", shortcut_css)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_public_submission_transport_actions_are_core_owned(self) -> None:
        repo_root = self.make_repo_root()
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        identity_status, identity_payload, _identity_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={
                "action": "public_submissions.identity",
                "source_kind": "workspace_local",
                "source_app_id": "local-notes",
                "source_workspace_id": "default",
            },
            cookie=cookie,
        )
        self.assertEqual(identity_status, 200)
        self.assertEqual(identity_payload["identity"]["app_id"], "local-notes")
        self.assertFalse(identity_payload["identity"]["has_public_identity"])

        create_status, create_payload, _create_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={
                "action": "public_submissions.create",
                "source_kind": "workspace_local",
                "source_app_id": "local-notes",
                "source_workspace_id": "default",
            },
            cookie=cookie,
        )
        read_status, read_payload, _read_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "public_submissions.read", "submission_id": "sub_test"},
            cookie=cookie,
        )

        self.assertEqual(create_status, 400)
        self.assertEqual(create_payload["error"], "validation_error")
        self.assertIn("core-owned API surface", create_payload["detail"])
        self.assertEqual(read_status, 400)
        self.assertEqual(read_payload["error"], "validation_error")
        self.assertIn("core-owned API surface", read_payload["detail"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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
        status_primary, primary, _primary_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=base-shell&content_kind=shell.sidebar.primary",
            cookie=cookie,
        )
        if isinstance(filtered, bytes):
            filtered = json.loads(filtered.decode("utf-8"))
        if isinstance(primary, bytes):
            primary = json.loads(primary.decode("utf-8"))
        status_widget, widget_body, widget_headers = self.invoke(
            app,
            path="/api/apps/widgets/app-store/app-shortcuts/frontend/",
            cookie=cookie,
        )

        self.assertEqual(status_filtered, 200)
        self.assertEqual(filtered["items"][0]["owner_app_id"], "app-store")
        self.assertEqual(filtered["items"][0]["widget_id"], "app-shortcuts")
        self.assertEqual(filtered["items"][0]["frontend_mount"], "/api/apps/widgets/app-store/app-shortcuts/frontend/")
        self.assertEqual(status_primary, 200)
        self.assertIn("app-shortcuts", {item["widget_id"] for item in primary["items"] if item["owner_app_id"] == "app-store"})
        self.assertEqual(status_widget, 200)
        self.assertIn("text/html", widget_headers["Content-Type"])
        self.assertIn(b"App shortcuts", widget_body)
        self.assertIn(b'type="module"', widget_body)
        self.assertIn(b"/apps/app-store/assets/widgets/app-shortcuts/index-", widget_body)
        self.assertNotIn(b"?v=", widget_body)
        shortcut_script = (
            Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "app-shortcuts" / "main.js"
        ).read_text()
        icon_script = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "assets" / "app-icons.js").read_text()
        shortcut_styles = (
            Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "app-shortcuts" / "styles.css"
        ).read_text()
        self.assertIn("MaverickAppIcons.renderIcon", shortcut_script)
        self.assertIn("logo?.kind === \"image\"", icon_script)
        self.assertIn("logo?.kind === \"glyph\"", icon_script)
        self.assertIn('"fitness-coach": "fitness_center"', icon_script)
        self.assertIn("pinned_apps.toggle", shortcut_script)
        self.assertIn("state.apps = registry.items || []", shortcut_script)
        self.assertIn("state.apps.filter(isFrontendLaunchable).map", shortcut_script)
        self.assertNotIn("state.apps = (registry.items || []).filter(isFrontendLaunchable)", shortcut_script)
        self.assertIn("row.classList.add(\"is-not-pinnable\")", shortcut_script)
        self.assertIn("button.disabled = true", shortcut_script)
        self.assertIn("row.append(button);", shortcut_script)
        self.assertIn(".app-shortcuts__icon img", shortcut_styles)
        self.assertIn(".app-shortcuts__search-frame", shortcut_styles)
        self.assertIn(".app-shortcuts__row.is-not-pinnable", shortcut_styles)
        self.assertIn(".app-shortcuts__button:disabled", shortcut_styles)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_catalog_and_install_require_maverick_authentication(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        catalog_status, catalog_payload, _catalog_headers = self.invoke(app, path="/api/app-store/apps")
        server_apps_status, server_apps_payload, _server_apps_headers = self.invoke(app, path="/api/app-store/server-apps")
        install_status, install_payload, _install_headers = self.invoke(
            app,
            path="/api/app-store/install",
            method="POST",
            body={"app_id": "notes", "workspace_ids": ["default"]},
        )
        server_install_status, server_install_payload, _server_install_headers = self.invoke(
            app,
            path="/api/app-store/install-server",
            method="POST",
            body={"app_id": "notes", "workspace_ids": ["default"]},
        )

        self.assertEqual(catalog_status, 401)
        self.assertEqual(catalog_payload["error"], "authentication_required")
        self.assertEqual(server_apps_status, 401)
        self.assertEqual(server_apps_payload["error"], "authentication_required")
        self.assertEqual(install_status, 401)
        self.assertEqual(install_payload["error"], "authentication_required")
        self.assertEqual(server_install_status, 401)
        self.assertEqual(server_install_payload["error"], "authentication_required")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_server_apps_api_reports_uninstalled_server_sources(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        notes_root = repo_root / "apps" / "notes"
        self.write_remote_app_contract(notes_root)
        register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(notes_root),
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(app, path="/api/app-store/server-apps", cookie=cookie)
        installations_status, installations, _installations_headers = self.invoke(
            app,
            path="/api/app-store/installations",
            cookie=cookie,
        )

        self.assertEqual(status, 200)
        self.assertEqual(installations_status, 200)
        server_app_ids = {item["app_id"] for item in payload["items"]}
        installed_app_ids = {item["app_id"] for item in installations["items"]}
        notes = next(item for item in payload["items"] if item["app_id"] == "notes")
        self.assertIn("notes", server_app_ids)
        self.assertNotIn("notes", installed_app_ids)
        self.assertEqual(notes["source_kind"], "platform")
        self.assertEqual(notes["latest_version"], "1.0.0")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_authenticated_install_server_app_enables_registered_source(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        notes_root = repo_root / "apps" / "notes"
        self.write_remote_app_contract(notes_root)
        register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(notes_root),
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        install_status, install, _headers = self.invoke(
            app,
            path="/api/app-store/install-server",
            method="POST",
            body={"app_id": "notes", "source_id": "platform:notes:1.0.0", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        installations_status, installations, _installations_headers = self.invoke(
            app,
            path="/api/app-store/installations",
            cookie=cookie,
        )

        binding = state.app_store.get_workspace_app_binding(workspace_id="default", app_id="notes")
        self.assertEqual(install_status, 201)
        self.assertEqual(install["status"], "installed")
        self.assertEqual(install["source_id"], "platform:notes:1.0.0")
        self.assertEqual(install["source_kind"], "platform")
        self.assertEqual(binding.status, "enabled")
        self.assertEqual(binding.source_record_id, "platform:notes:1.0.0")
        self.assertEqual(installations_status, 200)
        installed = {(item["workspace_id"], item["app_id"]) for item in installations["items"]}
        self.assertIn(("default", "notes"), installed)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_server_apps_api_hides_admin_only_sources_from_members(self) -> None:
        repo_root = self.make_repo_root()
        self.write_remote_app_contract(repo_root / "apps" / "member-visible-source", app_id="member-visible-source", name="Member Visible")
        self.write_remote_app_contract(
            repo_root / "apps" / "admin-only-source",
            app_id="admin-only-source",
            name="Admin Only",
            platform_roles=["admin"],
        )
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)

        status, payload, _headers = self.invoke(app, path="/api/app-store/server-apps", cookie=member_cookie)

        self.assertEqual(status, 200)
        server_app_ids = {item["app_id"] for item in payload["items"]}
        self.assertIn("member-visible-source", server_app_ids)
        self.assertNotIn("admin-only-source", server_app_ids)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

        with patch("core.api.app_store_http.fetch_remote_catalog", return_value=catalog):
            admin_status, admin_payload, _admin_headers = self.invoke(app, path="/api/app-store/apps", cookie=admin_cookie)
            member_status, member_payload, _member_headers = self.invoke(app, path="/api/app-store/apps", cookie=member_cookie)

        self.assertEqual(admin_status, 200)
        self.assertEqual(member_status, 200)
        self.assertIn("admin-panel", {item["app_id"] for item in admin_payload["items"]})
        self.assertNotIn("admin-panel", {item["app_id"] for item in member_payload["items"]})
        self.assertEqual(member_payload["count"], 1)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_catalog_api_normalizes_frontend_presentation_metadata(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        catalog = {
            "count": 2,
            "items": [
                {
                    "app_id": "developer-kit",
                    "name": "Developer Kit",
                    "presentation": {"frontend_role": "supporting"},
                    "surfaces": [],
                    "versions": [{"version": "1.0.0", "surfaces": []}],
                },
                {
                    "app_id": "notes",
                    "name": "Notes",
                    "surfaces": ["frontend", "mcp"],
                    "versions": [{"version": "1.0.0", "surfaces": ["frontend"]}],
                },
            ],
        }

        with patch("core.api.app_store_http.fetch_remote_catalog", return_value=catalog):
            status, payload, _headers = self.invoke(app, path="/api/app-store/apps", cookie=cookie)

        self.assertEqual(status, 200)
        items = {item["app_id"]: item for item in payload["items"]}
        self.assertEqual(items["developer-kit"]["frontend_role"], "supporting")
        self.assertFalse(items["developer-kit"]["frontend_launchable"])
        self.assertEqual(items["developer-kit"]["presentation"], {"frontend_role": "supporting"})
        self.assertIn("supporting_frontend", items["developer-kit"]["surfaces"])
        self.assertIn("supporting_frontend", items["developer-kit"]["versions"][0]["surfaces"])
        self.assertEqual(items["notes"]["frontend_role"], "workspace")
        self.assertTrue(items["notes"]["frontend_launchable"])
        self.assertIn("frontend", items["notes"]["surfaces"])
        self.assertIn("mcp", items["notes"]["surfaces"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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
        base_shell = next(item for item in payload["items"] if item["app_id"] == "base-shell")
        chat = next(item for item in payload["items"] if item["app_id"] == "chat")
        self.assertEqual(base_shell["presentation"], {"frontend_role": "supporting"})
        self.assertFalse(base_shell["frontend_launchable"])
        self.assertIn("supporting_frontend", base_shell["surfaces"])
        self.assertEqual(chat["presentation"], {"frontend_role": "workspace"})
        self.assertTrue(chat["frontend_launchable"])
        self.assertIn("frontend", chat["surfaces"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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
        self.assertNotIn("settings", installed_app_ids)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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
        local_item = next(item for item in payload["local_apps"] if item["app_id"] == "local-notes")
        self.assertTrue(local_item["can_promote"])
        self.assertEqual(local_item["promotion_kind"], "promote")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_member_installations_api_marks_local_app_promotion_unavailable(self) -> None:
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
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=member_cookie)

        self.assertEqual(status, 200)
        local_item = next(item for item in payload["local_apps"] if item["app_id"] == "local-notes")
        self.assertFalse(local_item["can_promote"])
        self.assertEqual(local_item["promotion_kind"], "blocked")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_installations_api_reports_invalid_workspace_local_app_projects(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        invalid_app_root = repo_root / "workspaces" / "default" / "apps" / "broken-local"
        invalid_app_root.mkdir(parents=True)
        (invalid_app_root / "app_contract.json").write_text(
            json.dumps(
                {
                    "app_id": "broken-local",
                    "contract_version": "1.0",
                    "name": "Broken Local",
                    "version": "0.1.0",
                    "description": "Invalid local app.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=cookie)

        self.assertEqual(status, 200)
        invalid_items = [item for item in payload["local_apps"] if item["app_id"] == "broken-local"]
        self.assertEqual(len(invalid_items), 1)
        self.assertEqual(invalid_items[0]["status"], "invalid")
        self.assertIn("non-empty string", invalid_items[0]["validation_error"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_register_local_api_reports_contract_validation_errors(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        invalid_app_root = repo_root / "workspaces" / "default" / "apps" / "broken-local"
        invalid_app_root.mkdir(parents=True)
        (invalid_app_root / "app_contract.json").write_text("{}", encoding="utf-8")
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "broken-local", "workspace_ids": ["default"]},
            cookie=cookie,
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "register_failed")
        self.assertIn("app_id", payload["detail"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_member_can_register_and_install_workspace_local_app_when_custom_apps_allowed(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)

        register_status, registered, _register_headers = self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=member_cookie,
        )
        install_status, installed, _install_headers = self.invoke(
            app,
            path="/api/app-store/install-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=member_cookie,
        )
        mount_status, mount_body, _mount_headers = self.invoke(app, path="/apps/local-notes/", cookie=member_cookie)

        self.assertEqual(register_status, 201)
        self.assertEqual(registered["status"], "registered")
        self.assertEqual(install_status, 201)
        self.assertEqual(installed["source_kind"], "workspace_local_project")
        self.assertEqual(mount_status, 200)
        self.assertIn(b"Local Notes", mount_body)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_member_cannot_delete_workspace_local_app_project(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=member_cookie,
        )

        delete_status, delete_payload, _headers = self.invoke(
            app,
            path="/api/app-store/delete-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=member_cookie,
        )

        self.assertEqual(delete_status, 403)
        self.assertEqual(delete_payload["error"], "workspace_admin_required")
        self.assertTrue(local_app_root.exists())

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_platform_admin_can_promote_workspace_local_app_as_forkable(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        (local_app_root / ".env").write_text("TOKEN=secret", encoding="utf-8")
        (local_app_root / "node_modules").mkdir()
        (local_app_root / "node_modules" / "large.js").write_text("junk", encoding="utf-8")
        outside_secret = repo_root / "outside-secret.txt"
        outside_secret.write_text("outside", encoding="utf-8")
        (local_app_root / "outside-link.txt").symlink_to(outside_secret)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        promote_status, promoted, _headers = self.invoke(
            app,
            path="/api/app-store/promote-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"], "promotion_mode": "forkable"},
            cookie=cookie,
        )

        promoted_root = repo_root / "apps" / "local-notes"
        promoted_contract = parse_app_contract_file(promoted_root)
        local_contract = parse_app_contract_file(local_app_root)
        source = state.app_store.get_app_source("platform:local-notes:0.1.0")

        self.assertEqual(promote_status, 201)
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(promoted["source_kind"], "platform")
        self.assertTrue(promoted_root.is_dir())
        self.assertFalse((promoted_root / ".env").exists())
        self.assertFalse((promoted_root / "node_modules").exists())
        self.assertFalse((promoted_root / "outside-link.txt").exists())
        self.assertEqual(promoted_contract.contract.distribution.mode, "source_available")
        self.assertEqual(promoted_contract.contract.distribution.source_access, "forkable")
        self.assertEqual(local_contract.contract.distribution.mode, "workspace_local")
        self.assertEqual(local_contract.contract.distribution.source_access, "editable")
        self.assertEqual(source.source_kind, "platform")
        self.assertEqual(source.source_path, str(promoted_root))
        self.assertEqual(source.owner_user_id, "user:admin")
        self.assertEqual(source.owner_username, "admin")
        self.assertEqual(source.promoted_from_workspace_id, "default")
        self.assertEqual(source.promoted_from_project_id, "default:local-notes")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_platform_admin_owner_can_publish_update_for_promoted_local_app(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )
        self.invoke(
            app,
            path="/api/app-store/promote-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"], "promotion_mode": "forkable"},
            cookie=cookie,
        )
        contract = json.loads((local_app_root / "app_contract.json").read_text(encoding="utf-8"))
        contract["version"] = "0.2.0"
        contract["description"] = "Workspace-local notes app updated."
        (local_app_root / "app_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=cookie,
        )

        installations_status, installations_payload, _headers = self.invoke(
            app,
            path="/api/app-store/installations",
            cookie=cookie,
        )
        update_item = next(item for item in installations_payload["local_apps"] if item["app_id"] == "local-notes")
        promote_status, promoted, _headers = self.invoke(
            app,
            path="/api/app-store/promote-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"], "promotion_mode": "sealed"},
            cookie=cookie,
        )

        updated_source = state.app_store.get_app_source("platform:local-notes:0.2.0")
        self.assertEqual(installations_status, 200)
        self.assertTrue(update_item["can_promote"])
        self.assertEqual(update_item["promotion_kind"], "update")
        self.assertEqual(promote_status, 201)
        self.assertEqual(promoted["status"], "updated")
        self.assertEqual(updated_source.owner_user_id, "user:admin")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_other_platform_admin_cannot_publish_update_for_promoted_local_app(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        other_admin_cookie = self.create_user(
            app,
            admin_cookie,
            username="operator",
            password="operatorpass",
            platform_role="admin",
            workspace_role="admin",
        )

        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/app-store/promote-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"], "promotion_mode": "forkable"},
            cookie=admin_cookie,
        )
        contract = json.loads((local_app_root / "app_contract.json").read_text(encoding="utf-8"))
        contract["version"] = "0.2.0"
        (local_app_root / "app_contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=admin_cookie,
        )

        status, payload, _headers = self.invoke(app, path="/api/app-store/installations", cookie=other_admin_cookie)
        local_item = next(item for item in payload["local_apps"] if item["app_id"] == "local-notes")
        promote_status, promote_payload, _headers = self.invoke(
            app,
            path="/api/app-store/promote-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"], "promotion_mode": "sealed"},
            cookie=other_admin_cookie,
        )

        self.assertEqual(status, 200)
        self.assertFalse(local_item["can_promote"])
        self.assertEqual(local_item["promotion_kind"], "blocked")
        self.assertIn("original app owner", local_item["promotion_detail"])
        self.assertEqual(promote_status, 400)
        self.assertEqual(promote_payload["error"], "promotion_failed")
        self.assertIn("Only the original app owner", promote_payload["detail"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_member_cannot_promote_workspace_local_app(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_app_root = repo_root / "workspaces" / "default" / "apps" / "local-notes"
        self.write_workspace_local_app_contract(local_app_root, frontend=True)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        member_cookie = self.create_member_user(app, admin_cookie)

        self.invoke(
            app,
            path="/api/app-store/register-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"]},
            cookie=admin_cookie,
        )
        promote_status, promote_payload, _headers = self.invoke(
            app,
            path="/api/app-store/promote-local",
            method="POST",
            body={"app_id": "local-notes", "workspace_ids": ["default"], "promotion_mode": "sealed"},
            cookie=member_cookie,
        )

        self.assertEqual(promote_status, 403)
        self.assertEqual(promote_payload["error"], "platform_admin_required")
        self.assertFalse((repo_root / "apps" / "local-notes").exists())

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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
        status_set, ordered, _ordered_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.set", "app_ids": ["agents", "chat", "agents", "", "base-shell"]},
            cookie=cookie,
        )

        self.assertEqual(status_initial, 200)
        self.assertEqual(initial["pinned_apps"], ["chat"])
        self.assertEqual(status_toggle, 200)
        self.assertEqual(toggled["state"]["pinned_apps"], ["chat", "agents"])
        self.assertEqual(status_set, 200)
        self.assertEqual(ordered["state"]["pinned_apps"], ["agents", "chat"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_pinned_apps_set_deduplicates_retried_mutations_by_exact_fingerprint(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        idempotency_key = "pinned-apps:retry-contract-0001"
        requested_app_ids = ["agents", "chat"]
        serialized = json.dumps(
            {"action": "pinned_apps.set", "app_ids": requested_app_ids},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = f"sha256:{hashlib.sha256(serialized).hexdigest()}"
        request = {
            "action": "pinned_apps.set",
            "app_ids": requested_app_ids,
            "idempotency_key": idempotency_key,
            "request_fingerprint": fingerprint,
        }
        app_events = state.app_event_bus.subscribe()
        self.addCleanup(lambda: state.app_event_bus.unsubscribe(app_events))

        first_status, first, _first_headers = self.invoke(
            app, path="/api/apps/app-store/backend", method="POST", body=request, cookie=cookie
        )
        first_event = app_events.get_nowait()
        ordinary_status, _ordinary, _ordinary_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.set", "app_ids": ["chat"]},
            cookie=cookie,
        )
        ordinary_event = app_events.get_nowait()
        replay_status, replay, _replay_headers = self.invoke(
            app, path="/api/apps/app-store/backend", method="POST", body=request, cookie=cookie
        )
        current_status, current, _current_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.list"},
            cookie=cookie,
        )

        conflicting_ids = ["chat"]
        conflicting_serialized = json.dumps(
            {"action": "pinned_apps.set", "app_ids": conflicting_ids},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        conflict_status, conflict, _conflict_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={
                "action": "pinned_apps.set",
                "app_ids": conflicting_ids,
                "idempotency_key": idempotency_key,
                "request_fingerprint": f"sha256:{hashlib.sha256(conflicting_serialized).hexdigest()}",
            },
            cookie=cookie,
        )

        self.assertEqual(first_status, 200)
        self.assertEqual(first["state"]["pinned_apps"], requested_app_ids)
        self.assertEqual(ordinary_status, 200)
        self.assertEqual(replay_status, 200)
        self.assertEqual(replay["state"]["pinned_apps"], requested_app_ids)
        self.assertEqual(current_status, 200)
        self.assertEqual(current["pinned_apps"], ["chat"])
        self.assertEqual(conflict_status, 400)
        self.assertIn("already bound", conflict["detail"])
        expected_event = {
            "type": "maverick.app.data-changed",
            "workspace_id": "default",
            "owner_app_id": "app-store",
            "resource": "state",
        }
        self.assertEqual(first_event, expected_event)
        self.assertEqual(ordinary_event, expected_event)
        self.assertTrue(app_events.empty())

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_app_store_backend_rejects_non_launchable_pin_but_removes_stale_pin(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_reject, rejected, _reject_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.toggle", "app_id": "base-shell"},
            cookie=cookie,
        )

        app_store_binding = state.app_store.get_workspace_app_binding(workspace_id="default", app_id="app-store")
        data_root = Path(app_store_binding.data_root)
        state_path = data_root / "state.json"
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        state_payload["pinned_apps"] = ["chat", "base-shell"]
        state_path.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
        app_events = state.app_event_bus.subscribe()
        self.addCleanup(lambda: state.app_event_bus.unsubscribe(app_events))
        status_repair, repaired, _repair_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.list"},
            cookie=cookie,
        )
        state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(status_repair, 200)
        self.assertEqual(repaired["pinned_apps"], ["chat"])
        self.assertEqual(state_payload["pinned_apps"], ["chat"])
        self.assertEqual(
            app_events.get_nowait(),
            {
                "type": "maverick.app.data-changed",
                "workspace_id": "default",
                "owner_app_id": "app-store",
                "resource": "state",
            },
        )

        status_noop_repair, noop_repaired, _noop_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.list"},
            cookie=cookie,
        )
        self.assertEqual(status_noop_repair, 200)
        self.assertEqual(noop_repaired["pinned_apps"], ["chat"])
        with self.assertRaises(Empty):
            app_events.get_nowait()

        state_payload["pinned_apps"] = ["chat", "base-shell"]
        state_path.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
        status_remove, removed, _remove_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.toggle", "app_id": "base-shell"},
            cookie=cookie,
        )
        status_set, filtered, _set_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "pinned_apps.set", "app_ids": ["chat", "base-shell", "agents"]},
            cookie=cookie,
        )

        self.assertEqual(status_reject, 400)
        self.assertEqual(rejected["error"], "validation_error")
        self.assertIn("launchable workspace frontend", rejected["detail"])
        self.assertEqual(status_remove, 200)
        self.assertEqual(removed["state"]["pinned_apps"], ["chat"])
        self.assertEqual(status_set, 200)
        self.assertEqual(filtered["state"]["pinned_apps"], ["chat", "agents"])
        service_py = (Path(__file__).resolve().parents[1] / "backend" / "service.py").read_text(encoding="utf-8")
        self.assertIn("repair_pinned_apps(data_root, launchable_app_ids)", service_py)
        self.assertIn("def _launchable_pinned_app_ids(app_ids: list[str], launchable_app_ids: list[str])", service_py)
        self.assertNotIn("return app_ids\n    launchable = _launchable_app_id_set(launchable_app_ids)", service_py)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_app_store_backend_persists_catalog_view_state(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        filtered_status, filtered, _filtered_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "set_view_filter", "query": "records", "scope": "installed"},
            cookie=cookie,
        )
        custom_status, custom, _custom_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={
                "action": "set_custom_view",
                "title": "Core apps",
                "refs": [{"entity_type": "installed_app", "entity_id": "chat"}],
            },
            cookie=cookie,
        )
        view_status, view_state, _view_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "view_filter"},
            cookie=cookie,
        )
        cleared_status, cleared, _cleared_headers = self.invoke(
            app,
            path="/api/apps/app-store/backend",
            method="POST",
            body={"action": "clear_custom_view"},
            cookie=cookie,
        )

        self.assertEqual(filtered_status, 200)
        self.assertEqual(filtered["state"]["view_filter"]["query"], "records")
        self.assertEqual(filtered["state"]["view_filter"]["scope"], "installed")
        self.assertEqual(custom_status, 200)
        self.assertEqual(custom["state"]["view_filter"]["mode"], "custom")
        self.assertEqual(custom["state"]["view_filter"]["refs"], [{"entity_type": "installed_app", "entity_id": "chat"}])
        self.assertEqual(view_status, 200)
        self.assertEqual(view_state["state"]["view_filter"]["mode"], "custom")
        self.assertEqual(cleared_status, 200)
        self.assertEqual(cleared["state"]["view_filter"]["mode"], "search")

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_app_store_backend_uses_official_catalog_by_default(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {}, clear=True):
            status, payload, _headers = self.invoke(
                app,
                path="/api/apps/app-store/backend",
                method="POST",
                body={"action": "state"},
                cookie=cookie,
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["core_catalog_endpoint"], "/api/app-store/apps")
        self.assertNotIn("catalog_url", payload)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @full_test("full app-store remote/public flow; run with scripts/test_suite.py --level full")
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

    def test_remote_bundle_staging_rejects_unsafe_catalog_path_segments_before_download(self) -> None:
        repo_root = self.make_repo_root()
        unsafe = RemoteAppVersion(
            app_id="../escape",
            version="1.0.0",
            name="Escape",
            artifact_url="https://catalog.example/escape.tar.gz",
            sha256="0" * 64,
        )

        with patch("core.apps.remote_store.resolve_remote_app_version", return_value=unsafe), patch(
            "core.apps.remote_store._read_url_bytes",
            side_effect=AssertionError("download should not start"),
        ):
            with self.assertRaisesRegex(AppLifecycleError, "app_id"):
                stage_remote_app_bundle(
                    base_url="https://catalog.example",
                    app_id="escape",
                    version="1.0.0",
                    start_path=repo_root,
                )

    def test_remote_artifact_url_requires_https_catalog_origin_or_allowlist(self) -> None:
        with self.assertRaisesRegex(AppLifecycleError, "https"):
            _validated_artifact_url("https://catalog.example", "http://catalog.example/app.tar.gz")
        with self.assertRaisesRegex(AppLifecycleError, "catalog origin"):
            _validated_artifact_url("https://catalog.example", "https://cdn.example/app.tar.gz")
        with patch.dict("os.environ", {"MAVERICK_APP_STORE_ARTIFACT_HOSTS": "cdn.example"}):
            self.assertEqual(
                _validated_artifact_url("https://catalog.example", "https://cdn.example/app.tar.gz"),
                "https://cdn.example/app.tar.gz",
            )

    def test_remote_artifact_download_enforces_max_bytes(self) -> None:
        class OversizeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self, size: int) -> bytes:
                return b"abcdef"

        with patch("core.apps.remote_store.urlopen", return_value=OversizeResponse()):
            with self.assertRaisesRegex(AppLifecycleError, "maximum size"):
                _read_url_bytes("https://catalog.example/app.tar.gz", max_bytes=5)

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
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

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_do_not_fetch_remote_catalog_directly(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

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

        self.assertEqual(mcp_payload["status_code"], 400)
        self.assertEqual(mcp_payload["error"], "validation_error")
        self.assertIn("core `/api/app-store/apps` API", mcp_payload["detail"])
        self.assertEqual(cli_payload["status_code"], 400)
        self.assertEqual(cli_payload["error"], "validation_error")
        self.assertIn("core `/api/app-store/apps` API", cli_payload["detail"])

    @integration_test("app-store platform integration suite; run with scripts/test_suite.py --level integration")
    def test_mcp_and_cli_reject_pinned_app_mutations_without_registry_context(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        mcp_payload = call_mcp_tool(
            tool_name="app.app-store.maverick_app_store",
            context=McpInvocationContext(
                caller_kind="sandbox_agent",
                workspace_id="default",
                agent_id="tester",
                effective_mode="sandbox",
            ),
            arguments={"action": "pinned_apps.toggle", "app_id": "base-shell"},
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
            arguments={"action": "pinned_apps.toggle", "app_id": "base-shell"},
            app_store=state.app_store,
            workspace_id="default",
            start_path=repo_root,
        )

        self.assertEqual(mcp_payload["status_code"], 400)
        self.assertEqual(mcp_payload["error"], "validation_error")
        self.assertIn("registry context", mcp_payload["detail"])
        self.assertEqual(cli_payload["status_code"], 400)
        self.assertEqual(cli_payload["error"], "validation_error")
        self.assertIn("registry context", cli_payload["detail"])


if __name__ == "__main__":
    unittest.main()
