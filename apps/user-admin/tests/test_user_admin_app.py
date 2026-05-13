"""Tests for admin identity surfaces and app visibility."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from tests.support.markers import slow_test_class


class UserAdminFrontendDistTests(unittest.TestCase):
    """Verify the bundled User Admin frontend keeps the Maverick glass theme."""

    def test_frontend_dist_uses_maverick_glass_theme(self) -> None:
        app_root = Path(__file__).resolve().parents[1]
        css_files = sorted((app_root / "frontend" / "dist" / "assets").glob("index-*.css"))
        self.assertTrue(css_files)
        frontend_css = css_files[-1].read_text(encoding="utf-8")
        frontend_html = (app_root / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")

        self.assertIn("User Admin", frontend_html)
        self.assertIn("color-scheme:dark", frontend_css)
        self.assertIn("--maverick-glass-surface", frontend_css)
        self.assertIn("backdrop-filter:blur(26px)", frontend_css)
        self.assertIn("@keyframes ua-progress-sheen", frontend_css)
        self.assertNotIn("--ua-primary:#d72451", frontend_css)


@slow_test_class("slow user-admin app integration suite; run with scripts/test_suite.py --level slow")
class UserAdminApiTestCase(unittest.TestCase):
    """Verify the core exposes app-agnostic user administration APIs."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick"
        for name in ("core", "apps", "workspaces", "docs", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[3] / "apps"
        for app_id in ("base-shell", "chat", "agents", "user-admin"):
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
        status_direct, direct, _direct_headers = self.invoke(app, path="/apps/user-admin/", cookie=member_cookie)

        self.assertEqual(status_admin_api, 403)
        self.assertEqual(forbidden["error"], "admin_required")
        self.assertEqual(status_apps, 200)
        self.assertNotIn("user-admin", {item["app_id"] for item in apps["items"]})
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
        status_admin_app, admin_body, _admin_headers = self.invoke_raw(restarted_app, path="/apps/user-admin/", cookie=admin_cookie)

        self.assertEqual(status_apps, 200)
        self.assertEqual(workspace["workspace_id"], "ceida")
        self.assertIn("user-admin", {item["app_id"] for item in apps["items"]})
        self.assertEqual(status_admin_app, 200)
        self.assertIn(b"User Admin", admin_body)

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
