from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import sys
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import create_user
from core.runtime.errors import RuntimeSessionNotFoundError
from core.runtime.runtime_threads import create_runtime_thread
from core.workspaces.service import ensure_workspace_membership
from tests.support.repo import link_app_sources, make_temp_repo_root


REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT_BACKEND_ROOT = REPO_ROOT / "apps" / "chat" / "backend"
sys.path.insert(0, str(CHAT_BACKEND_ROOT))

from chat_state import create_project, normalize_state  # noqa: E402


class ChatProjectDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_repo_root(self) -> Path:
        repo_root = make_temp_repo_root(self, include_core=True)
        link_app_sources(repo_root, ["chat"])
        return repo_root

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        headers: dict[str, str] = {}

        def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
            headers.update(dict(response_headers))
            headers["__status__"] = status

        result = b"".join(
            app(
                {
                    "PATH_INFO": path,
                    "REQUEST_METHOD": method,
                    "CONTENT_LENGTH": str(len(payload)),
                    "CONTENT_TYPE": "application/json",
                    "QUERY_STRING": "",
                    "wsgi.input": BytesIO(payload),
                    **({"HTTP_COOKIE": cookie} if cookie else {}),
                },
                start_response,
            )
        )
        return int(headers["__status__"].split()[0]), result, headers

    def login_as(self, app, *, username: str, password: str) -> str:
        status, _body, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def login(self, app) -> str:
        return self.login_as(
            app,
            username=os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
            password=os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
        )

    def create_project(self, app, cookie: str, name: str) -> str:
        status, body, _headers = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.create", "name": name},
            cookie=cookie,
        )
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 201)
        return payload["project"]["project_id"]

    def create_chat_thread(self, app, cookie: str, project_id: str) -> str:
        status, body, _headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat", "source_app_id": "chat", "project_id": project_id},
            cookie=cookie,
        )
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(status, 201)
        return payload["session_id"]

    def test_project_delete_cleans_linked_runtime_threads_before_project_commit(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        deleted_project_id = self.create_project(app, cookie, "Client work")
        kept_project_id = self.create_project(app, cookie, "Internal work")
        deleted_session_id = self.create_chat_thread(app, cookie, deleted_project_id)
        kept_session_id = self.create_chat_thread(app, cookie, kept_project_id)
        create_runtime_thread(
            state.runtime_store,
            workspace_id="default",
            thread_id="orphan-thread",
            runtime_session_id="missing-session",
            title="Orphaned chat",
            project_id=deleted_project_id,
            source_app_id="chat",
        )

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.delete", "project_id": deleted_project_id},
            cookie=cookie,
        )
        payload = json.loads(body.decode("utf-8"))
        remaining_threads = state.runtime_store.list_threads("default")

        self.assertEqual(status, 200)
        self.assertEqual([project["project_id"] for project in payload["projects"]], [kept_project_id])
        self.assertEqual([thread.project_id for thread in remaining_threads], [kept_project_id])
        self.assertEqual(remaining_threads[0].runtime_session_id, kept_session_id)
        with self.assertRaises(RuntimeSessionNotFoundError):
            state.runtime_store.get_session(deleted_session_id)

    def test_project_delete_commit_cannot_be_called_directly(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
        project_id = self.create_project(app, cookie, "Client work")
        session_id = self.create_chat_thread(app, cookie, project_id)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.delete.commit", "project_id": project_id},
            cookie=cookie,
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "project_delete_commit_forbidden")
        self.assertEqual(state.runtime_store.get_thread(session_id).project_id, project_id)
        self.assertEqual(state.runtime_store.get_session(session_id).session_id, session_id)

        list_status, list_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.list"},
            cookie=cookie,
        )
        list_payload = json.loads(list_body.decode("utf-8"))
        self.assertEqual(list_status, 200)
        self.assertEqual([project["project_id"] for project in list_payload["projects"]], [project_id])

    def test_project_delete_requires_runtime_cleanup_authority_for_linked_sessions(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        admin_cookie = self.login(app)
        project_id = self.create_project(app, admin_cookie, "Client work")
        session_id = self.create_chat_thread(app, admin_cookie, project_id)
        create_user(state.identity_store, username="member", password="member-pass", platform_role="member")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id="membership:member:default",
            workspace_id="default",
            user_id="user:member",
            role="member",
        )
        member_cookie = self.login_as(app, username="member", password="member-pass")

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.delete", "project_id": project_id},
            cookie=member_cookie,
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "runtime_session_cleanup_forbidden")
        self.assertEqual(state.runtime_store.get_thread(session_id).project_id, project_id)
        self.assertEqual(state.runtime_store.get_session(session_id).session_id, session_id)

        list_status, list_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.list"},
            cookie=admin_cookie,
        )
        list_payload = json.loads(list_body.decode("utf-8"))
        self.assertEqual(list_status, 200)
        self.assertEqual([project["project_id"] for project in list_payload["projects"]], [project_id])

    def test_normalize_state_repairs_non_list_projects_before_create(self) -> None:
        state = normalize_state({"projects": {"broken": True}, "preferences": {}})
        project = create_project(state, {"name": "Recovered"})

        self.assertEqual(len(state["projects"]), 1)
        self.assertEqual(project["name"], "Recovered")


if __name__ == "__main__":
    unittest.main()
