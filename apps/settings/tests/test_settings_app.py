"""Tests for admin identity surfaces and app visibility."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from tests.support.markers import slow_test_class


class SettingsFrontendDistTests(unittest.TestCase):
    """Verify the bundled Settings frontend keeps the Maverick glass theme."""

    def test_frontend_dist_uses_maverick_glass_theme(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        css_files = sorted((app_root / "frontend" / "dist" / "assets").glob("*.css"))
        self.assertTrue(css_files)
        frontend_css = "\n".join(path.read_text(encoding="utf-8") for path in css_files)
        frontend_html = (app_root / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")

        self.assertIn("Settings", frontend_html)
        self.assertIn("color-scheme:dark", frontend_css)
        self.assertIn("--maverick-glass-surface", frontend_css)
        self.assertIn("backdrop-filter:blur(26px)", frontend_css)
        self.assertIn("@keyframes settings-progress-sheen", frontend_css)
        self.assertIn("@keyframes settings-loading-skeleton-shimmer", frontend_css)
        self.assertIn(".settings-platform", frontend_css)
        self.assertNotIn("--settings-primary:#d72451", frontend_css)

    def test_settings_declares_shell_sidebar_widget(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        parsed = parse_app_contract_file(app_root)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        sidebar_widget = widgets["settings-sidebar"]
        vite_source = (app_root / "vite.config.ts").read_text(encoding="utf-8")
        sidebar_source = (app_root / "frontend" / "src" / "widgets" / "settings-sidebar" / "main.ts").read_text(encoding="utf-8")

        self.assertIn("widget", parsed.contract.provides[0].surfaces)
        self.assertEqual(sidebar_widget.host, "base-shell")
        self.assertEqual(sidebar_widget.content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(sidebar_widget.frontend.mount, "frontend/dist/widgets/settings-sidebar")
        self.assertTrue((app_root / "frontend" / "dist" / "widgets" / "settings-sidebar" / "index.html").is_file())
        self.assertIn("'widgets/settings-sidebar/index': 'frontend/widgets/settings-sidebar/index.html'", vite_source)
        self.assertIn("maverick.widget.open-app", sidebar_source)
        self.assertIn("maverick.shell.sidebar.close", sidebar_source)

    def test_settings_sidebar_uses_page_navigation(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        pages_source = (app_root / "frontend" / "src" / "pages.ts").read_text(encoding="utf-8")
        sidebar_source = (app_root / "frontend" / "src" / "widgets" / "settings-sidebar" / "main.ts").read_text(encoding="utf-8")

        self.assertIn("SETTINGS_PAGES", sidebar_source)
        self.assertIn("Search pages", sidebar_source)
        self.assertIn("page_id", sidebar_source)
        self.assertNotIn("loadUsers", sidebar_source)
        self.assertIn("workspace-access", pages_source)
        self.assertIn("selectedPageId", main_source)
        self.assertIn("activePageHtml(page, user)", main_source)

    def test_settings_embeds_platform_settings_panel(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        settings_source = (app_root / "frontend" / "src" / "settingsPanel.ts").read_text(encoding="utf-8")
        api_source = (app_root / "frontend" / "src" / "adminApi.ts").read_text(encoding="utf-8")

        self.assertIn("settingsPanelHtml(platformSettings, settingsPanelState)", main_source)
        self.assertIn("Platform settings", settings_source)
        self.assertIn("configureActiveProvider", api_source)
        self.assertIn("/api/settings/runtime-sessions/clear", api_source)

    def test_persistence_migration_requires_dry_run_and_explicit_cleanup(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        api_source = (app_root / "frontend" / "src" / "adminApi.ts").read_text(encoding="utf-8")
        bindings_source = (app_root / "frontend" / "src" / "bindEvents.ts").read_text(encoding="utf-8")
        controller_source = (app_root / "frontend" / "src" / "persistenceController.ts").read_text(encoding="utf-8")
        persistence_source = (app_root / "frontend" / "src" / "persistencePage.ts").read_text(encoding="utf-8")

        self.assertIn("/api/admin/persistence/migrations/dry-run", api_source)
        self.assertIn("/api/admin/persistence/migrations/apply", api_source)
        self.assertIn("dryRunPersistenceMigration(payload)", controller_source)
        self.assertIn("applyPersistenceMigrationRequest({", controller_source)
        self.assertIn("delete_source: deleteSourceAfterMigration", controller_source)
        self.assertNotIn("delete_source: true", main_source)
        self.assertNotIn("delete_source: true", controller_source)
        self.assertIn('id="settings-delete-source"', persistence_source)
        self.assertIn('id="validate-migration"', persistence_source)
        self.assertIn('data-migration-field="mongodb_username"', persistence_source)
        self.assertIn('data-migration-field="mongodb_password_ref"', persistence_source)
        self.assertIn("mongodb_username: draft.mongodb_username?.trim() || undefined", controller_source)
        self.assertIn("mongodb_password_ref: draft.mongodb_password_ref?.trim() || undefined", controller_source)
        self.assertIn("Schedule source cleanup after restart health check", persistence_source)
        self.assertIn("input', () => updateMigrationDraft(false)", bindings_source)
        self.assertIn("markMigrationDraftStale", bindings_source)

    def test_persistence_controller_requires_reviewed_dry_run_before_apply(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        typescript_root = app_root / "node_modules" / "typescript"
        if not typescript_root.exists():
            self.skipTest("settings frontend dependencies are not installed")
        node_script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require(process.argv[2]);

const appRoot = process.argv[3];
const outDir = process.argv[4];

function transpile(sourcePath, outFile) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const result = ts.transpileModule(source, {
    fileName: sourcePath,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      esModuleInterop: true,
      strict: true,
      skipLibCheck: true
    }
  });
  fs.writeFileSync(outFile, result.outputText);
}

transpile(path.join(appRoot, 'frontend/src/adminApi.ts'), path.join(outDir, 'adminApi.js'));
transpile(path.join(appRoot, 'frontend/src/persistenceController.ts'), path.join(outDir, 'persistenceController.js'));

const { createPersistenceController } = require(path.join(outDir, 'persistenceController.js'));
const sourceAdapter = {
  kind: 'json',
  json_root: 'data/control-plane/json',
  mongo_uri: null,
  mongo_database: 'maverick'
};
const calls = [];

function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    json: async () => payload
  };
}

global.fetch = async (url, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : {};
  calls.push({ url, body });
  if (url.endsWith('/dry-run')) {
    return jsonResponse({
      status: 'dry_run',
      source_adapter: sourceAdapter,
      target_adapter: {
        kind: body.kind,
        json_root: body.json_root,
        mongo_uri: body.mongodb_uri,
        mongo_database: body.mongodb_database
      },
      collections: [{ name: 'users', count: 2 }],
      target_collections: [],
      same_adapter: false,
      restart_required_for_cutover: true,
      env_file: '.env'
    });
  }
  if (url.endsWith('/apply')) {
    return jsonResponse({
      status: 'applied',
      source_adapter: sourceAdapter,
      target_adapter: {
        kind: body.kind,
        json_root: body.json_root,
        mongo_uri: body.mongodb_uri,
        mongo_database: body.mongodb_database
      },
      collections: [{ name: 'users', count: 2 }],
      target_collections: [],
      same_adapter: false,
      restart_required_for_cutover: true,
      backend_restart: { restarted: false, scheduled: true, detail: 'scheduled', method: 'signal', healthy: true },
      source_cleanup: { scheduled: body.delete_source, mode: body.delete_source ? 'post_health_check' : 'preserved' }
    });
  }
  throw new Error(`unexpected request ${url}`);
};
global.window = { setTimeout };

function requestCount(suffix) {
  return calls.filter((call) => call.url.endsWith(suffix)).length;
}

function lastRequest(suffix) {
  return calls.filter((call) => call.url.endsWith(suffix)).at(-1);
}

function makeController() {
  let activeAdapter = sourceAdapter;
  return createPersistenceController({
    getPersistence: () => ({
      active_adapter: activeAdapter,
      collections: [{ name: 'users', count: 2 }],
      restart_required_for_cutover: false
    }),
    render: () => {},
    requestPersistenceStatusQuiet: async () => ({
      active_adapter: {
        kind: 'mongo',
        json_root: 'data/control-plane/json',
        mongo_uri: 'mongodb://newhost:27017/maverick',
        mongo_database: 'maverick'
      },
      collections: [{ name: 'users', count: 2 }],
      restart_required_for_cutover: false
    }),
    setNotice: () => {},
    setPersistence: (status) => {
      activeAdapter = status.active_adapter;
    }
  });
}

(async () => {
  const controller = makeController();
  await controller.prepare('mongo');
  assert.equal(requestCount('/dry-run'), 0, 'opening the dialog must not dry-run immediately');
  assert.equal(controller.viewState().migrationTarget, 'mongo');
  assert.equal(controller.viewState().migrationPlan, null);

  await controller.validateDraft();
  assert.equal(requestCount('/dry-run'), 1);
  assert.equal(controller.viewState().migrationPlan.same_adapter, false);

  controller.updateDraft('mongodb_uri', 'mongodb://newhost:27017/maverick');
  assert.equal(controller.viewState().migrationPlan, null, 'editing the draft invalidates the reviewed plan');

  await controller.apply();
  assert.equal(requestCount('/dry-run'), 2, 'stale apply validates a fresh dry-run');
  assert.equal(requestCount('/apply'), 0, 'stale apply must not continue into apply in the same call');
  assert.equal(controller.viewState().migrationPlan.same_adapter, false);

  await controller.apply();
  assert.equal(requestCount('/apply'), 1);
  assert.equal(lastRequest('/apply').body.delete_source, false, 'source cleanup is opt-in');

  const cleanupController = makeController();
  await cleanupController.prepare('mongo');
  await cleanupController.validateDraft();
  cleanupController.setDeleteSource(true);
  await cleanupController.apply();
  assert.equal(requestCount('/apply'), 2);
  assert.equal(lastRequest('/apply').body.delete_source, true, 'checkbox enables source cleanup');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "persistence_controller_test.cjs"
            script_path.write_text(node_script, encoding="utf-8")
            result = subprocess.run(
                [
                    "node",
                    str(script_path),
                    str(typescript_root),
                    str(app_root),
                    temp_dir,
                ],
                cwd=app_root,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_settings_frontend_splits_page_renderers(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")

        for module_name in ("userPages.ts", "workspaceAppsPage.ts", "persistencePage.ts", "adminActions.ts", "persistenceController.ts", "bindEvents.ts"):
            self.assertTrue((app_root / "frontend" / "src" / module_name).is_file())
        self.assertLess(len(main_source.splitlines()), 600)
        self.assertNotIn("function persistenceHtml(", main_source)
        self.assertNotIn("function workspaceAppHtml(", main_source)
        self.assertNotIn("function membershipHtml(", main_source)
        self.assertNotIn("document.querySelectorAll<HTMLInputElement>('[data-app-toggle]')", main_source)

    def test_settings_app_uses_initial_skeleton_loader(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        main_source = (app_root / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")
        skeleton_source = (app_root / "frontend" / "src" / "appSkeleton.ts").read_text(encoding="utf-8")
        skeleton_css = (app_root / "frontend" / "src" / "styles" / "skeleton.css").read_text(encoding="utf-8")

        self.assertIn("settingsAppSkeletonHtml(page)", main_source)
        self.assertIn("let isLoading = true", main_source)
        self.assertIn('role="status"', skeleton_source)
        self.assertIn('aria-hidden="true"', skeleton_source)
        self.assertIn("@keyframes settings-loading-skeleton-shimmer", skeleton_css)


@slow_test_class("slow settings app integration suite; run with scripts/test_suite.py --level slow")
class SettingsApiTestCase(unittest.TestCase):
    """Verify the core exposes app-agnostic administration APIs."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "docs", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[3] / "apps"
        for app_id in ("base-shell", "chat", "agents", "settings"):
            source = source_apps_root / app_id
            if source.exists():
                shutil.copytree(source, repo_root / "apps" / app_id, ignore=shutil.ignore_patterns("node_modules"))
        return repo_root

    def invoke(
        self,
        app: PlatformHost,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(payload),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def invoke_raw(
        self,
        app: PlatformHost,
        *,
        path: str,
        cookie: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        headers: dict[str, str] = {}
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": "GET",
            "CONTENT_LENGTH": "0",
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "wsgi.input": BytesIO(b""),
        }
        if cookie is not None:
            environ["HTTP_COOKIE"] = cookie

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), body_bytes, headers

    def login(self, app: PlatformHost, username: str | None = None, password: str | None = None) -> str:
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

    def test_admin_can_create_user_and_assign_workspace(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_workspace, workspace, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Client Ops"},
            cookie=admin_cookie,
        )

        status_create, created, _create_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={
                "username": "operator",
                "password": "operator-password",
                "display_name": "Operator",
                "platform_role": "member",
            },
            cookie=admin_cookie,
        )
        status_assign, assigned, _assign_headers = self.invoke(
            app,
            path="/api/admin/users/user:operator/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": workspace["workspace_id"], "role": "member"}]},
            cookie=admin_cookie,
        )

        self.assertEqual(status_workspace, 201)
        self.assertEqual(status_create, 201)
        self.assertEqual(created["username"], "operator")
        self.assertEqual(status_assign, 200)
        self.assertIn(workspace["workspace_id"], {item["workspace_id"] for item in assigned["memberships"]})

    def test_admin_can_reset_another_users_password(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_create, created, _create_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "forgotten", "password": "initial-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )

        status_reset, reset, _reset_headers = self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}/password",
            method="POST",
            body={"password": "replacement-password"},
            cookie=admin_cookie,
        )
        status_old, old_login, _old_headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "forgotten", "password": "initial-password"},
        )
        replacement_cookie = self.login(app, username="forgotten", password="replacement-password")
        status_session, session, _session_headers = self.invoke(app, path="/api/session", cookie=replacement_cookie)

        self.assertEqual(status_create, 201)
        self.assertEqual(status_reset, 200)
        self.assertEqual(reset["status"], "updated")
        self.assertEqual(status_old, 401)
        self.assertEqual(old_login["error"], "invalid_credentials")
        self.assertEqual(status_session, 200)
        self.assertEqual(session["user"]["username"], "forgotten")

    def test_admin_can_delete_user_and_core_access_state(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_workspace, workspace, _workspace_headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Delete Target"},
            cookie=admin_cookie,
        )
        status_create, created, _create_headers = self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "delete-me", "password": "delete-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": workspace["workspace_id"], "role": "member"}]},
            cookie=admin_cookie,
        )
        deleted_user_cookie = self.login(app, username="delete-me", password="delete-password")

        status_delete, deleted, _delete_headers = self.invoke(
            app,
            path=f"/api/admin/users/{created['user_id']}",
            method="DELETE",
            cookie=admin_cookie,
        )
        status_session, session, _session_headers = self.invoke(app, path="/api/session", cookie=deleted_user_cookie)
        status_login, login_payload, _login_headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "delete-me", "password": "delete-password"},
        )

        self.assertEqual(status_workspace, 201)
        self.assertEqual(status_create, 201)
        self.assertEqual(status_delete, 200)
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(state.workspace_store.list_memberships_for_user(created["user_id"]), [])
        self.assertIsNone(state.workspace_store.get_active_workspace(created["user_id"]))
        self.assertEqual(status_session, 200)
        self.assertFalse(session["authenticated"])
        self.assertEqual(status_login, 401)
        self.assertEqual(login_payload["error"], "invalid_credentials")

    def test_admin_cannot_delete_self_or_final_active_admin(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)

        status_self, self_delete, _self_headers = self.invoke(
            app,
            path="/api/admin/users/user:admin",
            method="DELETE",
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "member-to-promote", "password": "member-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        status_demote, _demote, _demote_headers = self.invoke(
            app,
            path="/api/admin/users/user:admin",
            method="PATCH",
            body={"platform_role": "member"},
            cookie=admin_cookie,
        )

        self.assertEqual(status_self, 400)
        self.assertEqual(self_delete["error"], "cannot_delete_current_user")
        self.assertEqual(status_demote, 400)
        self.assertEqual(_demote["error"], "cannot_remove_last_admin")

    def test_member_cannot_use_admin_api_or_see_admin_app(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "viewer", "password": "viewer-password", "platform_role": "member"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/admin/users/user:viewer/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )
        member_cookie = self.login(app, username="viewer", password="viewer-password")

        status_admin_api, forbidden, _forbidden_headers = self.invoke(app, path="/api/admin/users", cookie=member_cookie)
        status_apps, apps, _apps_headers = self.invoke(app, path="/api/apps", cookie=member_cookie)
        status_direct, direct, _direct_headers = self.invoke(app, path="/apps/settings/", cookie=member_cookie)

        self.assertEqual(status_admin_api, 403)
        self.assertEqual(forbidden["error"], "admin_required")
        self.assertEqual(status_apps, 200)
        self.assertNotIn("settings", {item["app_id"] for item in apps["items"]})
        self.assertEqual(status_direct, 403)
        self.assertEqual(direct["error"], "app_forbidden")

    def test_local_identity_and_workspace_state_survives_bootstrap(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        self.invoke(
            app,
            path="/api/admin/users",
            method="POST",
            body={"username": "persistent", "password": "persistent-password"},
            cookie=admin_cookie,
        )
        self.invoke(
            app,
            path="/api/admin/users/user:persistent/workspaces",
            method="PUT",
            body={"memberships": [{"workspace_id": "default", "role": "member"}]},
            cookie=admin_cookie,
        )

        restarted_state = bootstrap_platform_state(start_path=repo_root)
        restarted_app = PlatformHost(restarted_state, start_path=restarted_state.repository_root)
        persistent_cookie = self.login(restarted_app, username="persistent", password="persistent-password")
        status_session, session, _headers = self.invoke(restarted_app, path="/api/session", cookie=persistent_cookie)

        self.assertEqual(status_session, 200)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["username"], "persistent")

    def test_persisted_active_workspace_gets_builtin_apps_after_restart(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_workspace, workspace, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "CEIDA"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_workspace, 201)

        restarted_state = bootstrap_platform_state(start_path=repo_root)
        restarted_app = PlatformHost(restarted_state, start_path=restarted_state.repository_root)
        status_apps, apps, _apps_headers = self.invoke(restarted_app, path="/api/apps", cookie=admin_cookie)
        status_admin_app, admin_body, _admin_headers = self.invoke_raw(restarted_app, path="/apps/settings/", cookie=admin_cookie)

        self.assertEqual(status_apps, 200)
        self.assertEqual(workspace["workspace_id"], "ceida")
        self.assertIn("settings", {item["app_id"] for item in apps["items"]})
        self.assertEqual(status_admin_app, 200)
        self.assertIn(b"Settings", admin_body)

    def test_admin_can_disable_and_enable_workspace_app_visibility(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)

        status_list, installed_apps, _list_headers = self.invoke(
            app,
            path="/api/admin/workspace-apps",
            cookie=admin_cookie,
        )
        status_disable, disabled, _disable_headers = self.invoke(
            app,
            path="/api/admin/workspace-apps/default/chat",
            method="PATCH",
            body={"status": "disabled"},
            cookie=admin_cookie,
        )
        status_apps_after_disable, visible_after_disable, _apps_disable_headers = self.invoke(
            app,
            path="/api/apps",
            cookie=admin_cookie,
        )
        status_direct_after_disable, direct_after_disable, _direct_disable_headers = self.invoke_raw(
            app,
            path="/apps/chat/",
            cookie=admin_cookie,
        )
        status_enable, enabled, _enable_headers = self.invoke(
            app,
            path="/api/admin/workspace-apps/default/chat",
            method="PATCH",
            body={"status": "enabled"},
            cookie=admin_cookie,
        )
        status_apps_after_enable, visible_after_enable, _apps_enable_headers = self.invoke(
            app,
            path="/api/apps",
            cookie=admin_cookie,
        )

        self.assertEqual(status_list, 200)
        self.assertIn(("default", "chat"), {(item["workspace_id"], item["app_id"]) for item in installed_apps["items"]})
        self.assertEqual(status_disable, 200)
        self.assertEqual(disabled["status"], "disabled")
        self.assertEqual(status_apps_after_disable, 200)
        self.assertNotIn("chat", {item["app_id"] for item in visible_after_disable["items"]})
        self.assertEqual(status_direct_after_disable, 404)
        self.assertIn(b"app_not_installed", direct_after_disable)
        self.assertEqual(status_enable, 200)
        self.assertEqual(enabled["status"], "enabled")
        self.assertEqual(status_apps_after_enable, 200)
        self.assertIn("chat", {item["app_id"] for item in visible_after_enable["items"]})


if __name__ == "__main__":
    unittest.main()
