"""Tests for admin identity surfaces and app visibility."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state


class UserAdminApiTestCase(unittest.TestCase):
    """Verify the core exposes app-agnostic user administration APIs."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "docs", "local-skills", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
        source_apps_root = Path(__file__).resolve().parents[1] / "apps"
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

    def login(self, app: PlatformHost, username: str = "admin", password: str = "maverick3") -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
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

        restarted_state = bootstrap_platform_state(start_path=repo_root)
        restarted_app = PlatformHost(restarted_state, start_path=restarted_state.repository_root)
        persistent_cookie = self.login(restarted_app, username="persistent", password="persistent-password")
        status_session, session, _headers = self.invoke(restarted_app, path="/api/session", cookie=persistent_cookie)

        self.assertEqual(status_session, 200)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["username"], "persistent")


if __name__ == "__main__":
    unittest.main()
