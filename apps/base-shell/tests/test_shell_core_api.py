"""Tests for shell-facing core APIs used by base-shell."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import base64
import json
import os
import time
from unittest.mock import patch
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import build_app_contract, build_app_distribution, build_app_entrypoints, build_parsed_app_contract, write_app_contract_file
from core.apps.service import install_workspace_local_app, register_workspace_local_app_project_from_contract
from core.identity.service import create_user
from core.providers.service import configure_workspace_provider
from core.workspaces.service import ensure_workspace_membership
from tests.support.markers import slow_test_class
from tests.support.repo import make_temp_repo_root, link_app_sources, write_synthetic_platform_app


@slow_test_class("slow shell/core API integration suite; run with scripts/test_suite.py --level slow")
class ShellCoreApiTestCase(unittest.TestCase):
    """Verify the shell can use generic core APIs instead of static assumptions."""

    def configure_default_provider(self, state) -> None:
        configure_workspace_provider(state.provider_store, workspace_id="default", provider_id="codex")

    def make_repo_root(self) -> Path:
        repo_root = make_temp_repo_root(self)
        link_app_sources(repo_root, ["base-shell"])
        self.write_shell_dependency_apps(repo_root)
        return repo_root

    def write_shell_dependency_apps(self, repo_root: Path) -> None:
        write_synthetic_platform_app(
            repo_root,
            app_id="chat",
            name="Chat",
            backend=True,
            cli_commands=["chat"],
            mcp_tools=["chat_reference_search"],
            views=["chat"],
            runtime_create_sessions=True,
        )
        write_synthetic_platform_app(
            repo_root,
            app_id="agents",
            name="Agents",
            backend=True,
            cli_commands=["agents"],
            mcp_tools=["maverick_agents_app"],
            views=["agents"],
        )

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
        query_string: str = "",
    ) -> tuple[int, dict, dict[str, str]]:
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
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

        body_bytes = b"".join(app(environ, start_response))
        return int(headers["__status__"].split()[0]), json.loads(body_bytes.decode("utf-8")), headers

    def login(self, app) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def login_as(self, app, *, username: str, password: str) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": username, "password": password},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_session_login_and_logout_are_exposed(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)

        status_guest, guest_payload, _guest_headers = self.invoke(app, path="/api/session")
        cookie = self.login(app)
        status_user, user_payload, _user_headers = self.invoke(app, path="/api/session", cookie=cookie)
        status_logout, logout_payload, logout_headers = self.invoke(app, path="/api/auth/logout", method="POST", cookie=cookie)

        self.assertEqual(status_guest, 200)
        self.assertFalse(guest_payload["authenticated"])
        self.assertEqual(status_user, 200)
        self.assertTrue(user_payload["authenticated"])
        self.assertEqual(user_payload["user"]["username"], "admin")
        self.assertEqual(user_payload["workspace_id"], "default")
        self.assertEqual(status_logout, 200)
        self.assertFalse(logout_payload["authenticated"])
        self.assertIn("Max-Age=0", logout_headers["Set-Cookie"])

    def test_workspace_registry_and_app_mounts_require_authenticated_session(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)

        status_status, status_payload, _ = self.invoke(app, path="/api/status")
        apps_status, apps_payload, _ = self.invoke(app, path="/api/apps")
        frontend_status, frontend_payload, _ = self.invoke(app, path="/apps/chat/")
        backend_status, backend_payload, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.list"},
        )
        cookie = self.login(app)
        authed_status, authed_payload, _ = self.invoke(app, path="/api/status", cookie=cookie)

        self.assertEqual(status_status, 401)
        self.assertEqual(status_payload["error"], "authentication_required")
        self.assertEqual(apps_status, 401)
        self.assertEqual(apps_payload["error"], "authentication_required")
        self.assertEqual(frontend_status, 401)
        self.assertEqual(frontend_payload["error"], "authentication_required")
        self.assertEqual(backend_status, 401)
        self.assertEqual(backend_payload["error"], "authentication_required")
        self.assertEqual(authed_status, 200)
        self.assertEqual(authed_payload["workspace_id"], "default")

    def test_app_backend_media_subroute_resolves_app_id_before_backend_segment(self) -> None:
        repo_root = self.make_repo_root()
        media_app_root = write_synthetic_platform_app(
            repo_root,
            app_id="media-backend",
            name="Media Backend",
            frontend=False,
            backend=True,
        )
        (media_app_root / "backend" / "app_backend.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "result = {\n"
            "    'status_code': 200,\n"
            "    'json': {\n"
            "        'app_id': payload.get('app_id'),\n"
            "        'method': payload.get('method'),\n"
            "        'route_path': payload.get('route_path'),\n"
            "        'query': payload.get('query') or {},\n"
            "    },\n"
            "}\n"
            "json.dump(result, sys.stdout)\n",
            encoding="utf-8",
        )
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        media_status, media_payload, _ = self.invoke(
            app,
            path="/api/apps/media-backend/backend/media",
            method="GET",
            query_string="preview_id=preview_1&path=assets%2Fimage.webp",
            cookie=cookie,
        )
        legacy_status, legacy_payload, _ = self.invoke(
            app,
            path="/api/apps/media-backend/media",
            method="GET",
            query_string="preview_id=preview_2&path=assets%2Flegacy.webp",
            cookie=cookie,
        )

        self.assertEqual(media_status, 200)
        self.assertEqual(media_payload["app_id"], "media-backend")
        self.assertEqual(media_payload["method"], "GET")
        self.assertEqual(media_payload["route_path"], "/api/apps/media-backend/backend/media")
        self.assertEqual(media_payload["query"]["preview_id"], "preview_1")
        self.assertEqual(media_payload["query"]["path"], "assets/image.webp")
        self.assertEqual(legacy_status, 200)
        self.assertEqual(legacy_payload["app_id"], "media-backend")
        self.assertEqual(legacy_payload["method"], "GET")
        self.assertEqual(legacy_payload["route_path"], "/api/apps/media-backend/media")
        self.assertEqual(legacy_payload["query"]["preview_id"], "preview_2")
        self.assertEqual(legacy_payload["query"]["path"], "assets/legacy.webp")

    def test_workspace_local_backend_requires_workspace_admin(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_root = repo_root / "workspaces" / "default" / "apps" / "local-backend"
        (local_root / "backend").mkdir(parents=True)
        (local_root / "backend" / "app_backend.py").write_text(
            "import json, sys\njson.dump({'json': {'ok': True}}, sys.stdout)\n",
            encoding="utf-8",
        )
        write_app_contract_file(
            local_root,
            build_parsed_app_contract(
                app_id="local-backend",
                name="Local Backend",
                version="1.0.0",
                description="Workspace-local backend test app.",
                publisher="workspace",
                contract=build_app_contract(
                    distribution=build_app_distribution(mode="workspace_local", source_access="editable"),
                    entrypoints=build_app_entrypoints(backend="backend/app_backend.py"),
                ),
            ),
        )
        register_workspace_local_app_project_from_contract(
            state.app_store,
            workspace_id="default",
            project_root=str(local_root),
        )
        install_workspace_local_app(state.app_store, workspace_id="default", app_id="local-backend", start_path=repo_root)
        create_user(state.identity_store, username="member", password="member-pass", platform_role="member")
        ensure_workspace_membership(
            state.workspace_store,
            membership_id="membership:member:default",
            workspace_id="default",
            user_id="user:member",
            role="member",
        )
        app = PlatformHost(state, start_path=state.repository_root)
        member_cookie = self.login_as(app, username="member", password="member-pass")
        admin_cookie = self.login(app)

        member_status, member_payload, _ = self.invoke(
            app,
            path="/api/apps/local-backend/backend",
            method="POST",
            body={},
            cookie=member_cookie,
        )
        admin_status, admin_payload, _ = self.invoke(
            app,
            path="/api/apps/local-backend/backend",
            method="POST",
            body={},
            cookie=admin_cookie,
        )

        self.assertEqual(member_status, 403)
        self.assertEqual(member_payload["error"], "workspace_local_backend_forbidden")
        self.assertEqual(admin_status, 200)
        self.assertEqual(admin_payload["ok"], True)

    def test_workspace_selector_can_create_and_switch_active_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        status_default_session, default_session, _default_session_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat", "source_app_id": "chat", "title": "Default workspace thread"},
            cookie=cookie,
        )
        status_default_thread, default_thread, _default_thread_headers = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": default_session["session_id"], "title": "Default workspace thread", "source_app_id": "chat"},
            cookie=cookie,
        )
        status_create, created, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Client Lab"},
            cookie=cookie,
        )
        status_list, workspaces, _list_headers = self.invoke(app, path="/api/workspaces", cookie=cookie)
        status_status, platform_status, _status_headers = self.invoke(app, path="/api/status", cookie=cookie)
        status_new_chat, new_chat, _new_chat_headers = self.invoke(
            app,
            path="/api/runtime/threads",
            cookie=cookie,
        )

        self.assertEqual(status_default_session, 201)
        self.assertEqual(status_default_thread, 201)
        self.assertEqual(default_thread["thread"]["title"], "Default workspace thread")
        self.assertEqual(status_create, 201)
        self.assertEqual(created["workspace_id"], "client-lab")
        self.assertEqual(status_list, 200)
        self.assertEqual(workspaces["active_workspace_id"], "client-lab")
        self.assertEqual(status_status, 200)
        self.assertEqual(platform_status["workspace_id"], "client-lab")
        self.assertEqual({item["app_id"] for item in platform_status["apps"]}, {"agents", "base-shell", "chat"})
        self.assertEqual(status_new_chat, 200)
        self.assertEqual(new_chat["threads"], [])
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "chat" / ".maverick-app.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "client-lab" / "data" / "chat" / ".maverick-app.json").is_file())

    def test_member_without_saved_workspace_selection_falls_back_to_own_workspace_only(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_create, created, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "CEIDA"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)

        member = create_user(
            state.identity_store,
            username="ceida.member",
            password="member-pass",
            platform_role="member",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{created['workspace_id']}:{member.user_id}",
            workspace_id=created["workspace_id"],
            user_id=member.user_id,
            role="member",
        )
        member_cookie = self.login_as(app, username="ceida.member", password="member-pass")

        status_session, session, _session_headers = self.invoke(app, path="/api/session", cookie=member_cookie)
        status_workspaces, workspaces, _workspace_headers = self.invoke(app, path="/api/workspaces", cookie=member_cookie)
        status_runtime, runtime_session, _runtime_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=member_cookie,
        )

        self.assertEqual(status_session, 200)
        self.assertEqual(session["workspace_id"], "ceida")
        self.assertEqual(status_workspaces, 200)
        self.assertEqual(workspaces["active_workspace_id"], "ceida")
        self.assertEqual([item["workspace_id"] for item in workspaces["items"]], ["ceida"])
        self.assertEqual(status_runtime, 201)
        self.assertEqual(runtime_session["workspace_id"], "ceida")
        self.assertEqual(runtime_session["effective_mode"], "sandbox")

    def test_runtime_session_creation_requires_explicit_agent_id(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        status_runtime, runtime_payload, _runtime_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={},
            cookie=cookie,
        )

        self.assertEqual(status_runtime, 400)
        self.assertEqual(runtime_payload["error"], "agent_id_required")

    def test_provider_status_reports_no_configured_provider(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        status_provider, provider, _provider_headers = self.invoke(app, path="/api/providers/active", cookie=cookie)

        self.assertEqual(status_provider, 200)
        self.assertFalse(provider["configured"])
        self.assertIsNone(provider["active_provider"])
        self.assertIsNone(provider["model_settings"])
        self.assertEqual(provider["blocked_reason"], "no_provider_configured")

    def test_runtime_turn_without_provider_returns_recoverable_error(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        _status_session, session, _session_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=cookie,
        )
        status_turn, turn_payload, _turn_headers = self.invoke(
            app,
            path=f"/api/runtime/sessions/{session['session_id']}/turns",
            method="POST",
            body={"input_text": "hello"},
            cookie=cookie,
        )

        self.assertEqual(status_turn, 409)
        self.assertEqual(turn_payload["error"], "provider_unavailable")
        self.assertEqual(turn_payload["blocked_reason"], "no_provider_configured")

    def test_member_cannot_create_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)
        status_create, created, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "CEIDA"},
            cookie=admin_cookie,
        )
        self.assertEqual(status_create, 201)

        member = create_user(
            state.identity_store,
            username="workspace.member",
            password="member-pass",
            platform_role="member",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{created['workspace_id']}:{member.user_id}",
            workspace_id=created["workspace_id"],
            user_id=member.user_id,
            role="member",
        )
        member_cookie = self.login_as(app, username="workspace.member", password="member-pass")

        status_forbidden, forbidden, _forbidden_headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Forbidden Workspace"},
            cookie=member_cookie,
        )
        status_workspaces, workspaces, _workspace_headers = self.invoke(app, path="/api/workspaces", cookie=member_cookie)

        self.assertEqual(status_forbidden, 403)
        self.assertEqual(forbidden["error"], "admin_required")
        self.assertEqual(status_workspaces, 200)
        self.assertNotIn("forbidden-workspace", {item["workspace_id"] for item in workspaces["items"]})

    def test_provider_runtime_settings_and_recovery_surfaces_are_shell_visible(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        self.configure_default_provider(state)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)
        create_status, created_session, _create_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=cookie,
        )
        status_create_workspace, created_workspace, _workspace_headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Runtime Lab"},
            cookie=cookie,
        )
        create_other_status, other_session, _other_create_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "worker"},
            cookie=cookie,
        )
        self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": other_session["session_id"], "title": "Runtime lab thread"},
            cookie=cookie,
        )
        switch_status, _switch_payload, _switch_headers = self.invoke(
            app,
            path="/api/workspaces/active",
            method="POST",
            body={"workspace_id": "default"},
            cookie=cookie,
        )
        self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": created_session["session_id"], "title": "Default thread"},
            cookie=cookie,
        )
        Path(state.runtime_store.get_session(created_session["session_id"]).runtime_root).mkdir(parents=True, exist_ok=True)
        Path(state.runtime_store.get_session(other_session["session_id"]).runtime_root).mkdir(parents=True, exist_ok=True)

        status_provider, provider, _provider_headers = self.invoke(app, path="/api/providers/active", cookie=cookie)
        model_id = provider["model_settings"]["selected_model_id"]
        model_option = next(option for option in provider["model_settings"]["available_models"] if option["model_id"] == model_id)
        reasoning_effort = model_option["supported_reasoning_efforts"][-1]["effort"]
        status_model_update, model_update, _model_update_headers = self.invoke(
            app,
            path="/api/providers/active",
            method="POST",
            body={"provider_id": "codex", "model_id": model_id, "model_reasoning_effort": reasoning_effort},
            cookie=cookie,
        )
        status_runtime, runtime, _runtime_headers = self.invoke(app, path="/api/runtime/status", cookie=cookie)
        status_settings, settings, _settings_headers = self.invoke(app, path="/api/settings/platform", cookie=cookie)
        status_provider_setup, provider_setup, _provider_setup_headers = self.invoke(
            app,
            path="/api/settings/provider-setup",
            cookie=cookie,
        )
        status_runtime_inventory, runtime_inventory, _inventory_headers = self.invoke(
            app,
            path="/api/settings/runtime-sessions",
            cookie=cookie,
        )
        status_clear, clear_result, _clear_headers = self.invoke(
            app,
            path="/api/settings/runtime-sessions/clear",
            method="POST",
            body={"reason": "settings_clear_test"},
            cookie=cookie,
        )
        status_recovery, recovery, _recovery_headers = self.invoke(app, path="/api/recovery/status", cookie=cookie)

        self.assertEqual(create_status, 201)
        self.assertEqual(status_create_workspace, 201)
        self.assertEqual(created_workspace["workspace_id"], "runtime-lab")
        self.assertEqual(create_other_status, 201)
        self.assertEqual(other_session["workspace_id"], "runtime-lab")
        self.assertEqual(switch_status, 200)
        self.assertEqual(status_provider, 200)
        self.assertEqual(provider["active_provider"]["provider_id"], "codex")
        self.assertEqual(provider["model_settings"]["selected_model_id"], model_id)
        self.assertTrue(provider["model_settings"]["available_models"])
        self.assertEqual(status_model_update, 200)
        self.assertEqual(model_update["selection"]["model_id"], model_id)
        self.assertEqual(model_update["selection"]["model_reasoning_effort"], reasoning_effort)
        self.assertEqual(status_runtime, 200)
        self.assertGreaterEqual(len(runtime["sessions"]), 1)
        self.assertEqual(status_settings, 200)
        self.assertEqual(settings["provider"]["active_provider"]["label"], "Codex")
        self.assertEqual(settings["workspace"]["workspace_id"], "default")
        self.assertTrue(settings["runtime"]["cleanup_allowed"])
        self.assertEqual(settings["runtime"]["cleanup_scope"], "server")
        self.assertNotIn("all_sessions", settings["runtime"])
        self.assertEqual(status_provider_setup, 200)
        self.assertEqual(provider_setup["provider"]["active_provider"]["label"], "Codex")
        self.assertEqual(provider_setup["workspace"]["workspace_id"], "default")
        self.assertNotIn("runtime", provider_setup)
        self.assertNotIn("recovery", provider_setup)
        self.assertEqual(status_runtime_inventory, 200)
        self.assertEqual({item["workspace_id"] for item in runtime_inventory["items"]}, {"default", "runtime-lab"})
        self.assertEqual(status_clear, 200)
        self.assertEqual(clear_result["cleared_sessions"], 2)
        self.assertEqual(clear_result["deleted_threads"], 2)
        self.assertEqual(clear_result["runtime_roots_deleted"], 2)
        self.assertEqual(clear_result["sessions"], [])
        self.assertEqual(state.runtime_store.list_all_sessions(), [])
        self.assertEqual(state.runtime_store.list_threads("default"), [])
        self.assertEqual(state.runtime_store.list_threads("runtime-lab"), [])
        self.assertFalse(Path(created_session["runtime_root"]).exists())
        self.assertFalse(Path(other_session["runtime_root"]).exists())
        self.assertEqual(status_recovery, 200)
        self.assertEqual(recovery["workspace_id"], "default")

    def test_core_runtime_thread_delete_removes_linked_runtime_session(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        session_status, session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=cookie,
        )
        Path(session["runtime_root"]).mkdir(parents=True, exist_ok=True)
        Path(session["runtime_root"], "marker.txt").write_text("delete me\n", encoding="utf-8")
        create_status, created, _ = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"title": "Delete me", "runtime_session_id": session["session_id"]},
            cookie=cookie,
        )
        thread_id = created["thread"]["thread_id"]

        delete_status, deleted, _ = self.invoke(
            app,
            path=f"/api/runtime/threads/{thread_id}",
            method="DELETE",
            cookie=cookie,
        )
        missing_status, missing, _ = self.invoke(
            app,
            path=f"/api/runtime/sessions/{session['session_id']}",
            cookie=cookie,
        )

        self.assertEqual(session_status, 201)
        self.assertEqual(create_status, 201)
        self.assertEqual(delete_status, 200)
        self.assertEqual(deleted["deleted_thread_id"], thread_id)
        self.assertEqual(deleted["removed_thread_id"], thread_id)
        self.assertEqual(deleted["deleted_runtime_session_id"], session["session_id"])
        self.assertNotIn("threads", deleted)
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing["error"], "runtime_session_not_found")
        self.assertFalse(Path(session["runtime_root"]).exists())

    def test_workspace_admin_cleanup_is_limited_to_active_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        admin_cookie = self.login(app)

        default_status, default_session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=admin_cookie,
        )
        create_workspace_status, created_workspace, _ = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Scoped Runtime Lab"},
            cookie=admin_cookie,
        )
        workspace_session_status, workspace_session, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "worker"},
            cookie=admin_cookie,
        )
        self.assertEqual(default_status, 201)
        self.assertEqual(create_workspace_status, 201)
        self.assertEqual(workspace_session_status, 201)

        workspace_admin = create_user(
            state.identity_store,
            username="workspace.admin",
            password="workspace-admin-pass",
            platform_role="member",
        )
        ensure_workspace_membership(
            state.workspace_store,
            membership_id=f"{created_workspace['workspace_id']}:{workspace_admin.user_id}",
            workspace_id=created_workspace["workspace_id"],
            user_id=workspace_admin.user_id,
            role="admin",
        )
        workspace_admin_cookie = self.login_as(app, username="workspace.admin", password="workspace-admin-pass")

        status_settings, settings, _ = self.invoke(app, path="/api/settings/platform", cookie=workspace_admin_cookie)
        status_provider_setup, provider_setup, _ = self.invoke(
            app,
            path="/api/settings/provider-setup",
            cookie=workspace_admin_cookie,
        )
        status_runtime_inventory, runtime_inventory, _ = self.invoke(app, path="/api/settings/runtime-sessions", cookie=workspace_admin_cookie)
        status_clear, clear_result, _ = self.invoke(
            app,
            path="/api/settings/runtime-sessions/clear",
            method="POST",
            body={"reason": "workspace_admin_cleanup"},
            cookie=workspace_admin_cookie,
        )

        self.assertEqual(status_settings, 200)
        self.assertEqual(settings["workspace"]["workspace_id"], created_workspace["workspace_id"])
        self.assertTrue(settings["runtime"]["cleanup_allowed"])
        self.assertEqual(settings["runtime"]["cleanup_scope"], "workspace")
        self.assertNotIn("all_sessions", settings["runtime"])
        self.assertEqual(status_provider_setup, 200)
        self.assertEqual(provider_setup["workspace"]["workspace_id"], created_workspace["workspace_id"])
        self.assertNotIn("runtime", provider_setup)
        self.assertEqual(status_runtime_inventory, 200)
        self.assertEqual({item["workspace_id"] for item in runtime_inventory["items"]}, {created_workspace["workspace_id"]})
        self.assertEqual(status_clear, 200)
        self.assertEqual(clear_result["cleared_sessions"], 1)
        self.assertEqual(clear_result["results"][0]["workspace_id"], created_workspace["workspace_id"])
        self.assertIsNotNone(state.runtime_store.get_session(default_session["session_id"]))
        self.assertEqual(state.runtime_store.list_sessions(created_workspace["workspace_id"]), [])

    def test_runtime_turn_api_executes_selected_provider_and_records_events(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        self.configure_default_provider(state)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        fake_events = json.dumps(
            [
                {"event_type": "runtime.step.updated", "payload": {"label": "Reading workspace"}},
                {"event_type": "runtime.tool_call.started", "payload": {"name": "core.workspaces.list"}},
                {"event_type": "runtime.tool_call.completed", "payload": {"name": "core.workspaces.list"}},
                {"event_type": "runtime.output.delta", "payload": {"text": "Working"}},
            ]
        )
        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "hello from codex", "MAVERICK_RUNTIME_FAKE_EVENTS": fake_events}):
            status_session, session, _session_headers = self.invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={"agent_id": "chat"},
                cookie=cookie,
            )
            status_turn, turn_payload, _turn_headers = self.invoke(
                app,
                path=f"/api/runtime/sessions/{session['session_id']}/turns",
                method="POST",
                body={"input_text": "hello", "client_message_id": "client-message-1"},
                cookie=cookie,
            )
            status_events, events, _events_headers = self.invoke(
                app,
                path=f"/api/runtime/sessions/{session['session_id']}/events",
                cookie=cookie,
            )
            status_threads, threads, _thread_headers = self.invoke(app, path="/api/runtime/threads", cookie=cookie)

        self.assertEqual(status_session, 201)
        self.assertEqual(session["provider_id"], "codex")
        self.assertEqual(status_turn, 201)
        self.assertEqual(turn_payload["turn"]["status"], "completed")
        self.assertEqual(status_events, 200)
        self.assertEqual(status_threads, 200)
        self.assertEqual(threads["threads"][0]["runtime_session_id"], session["session_id"])
        self.assertEqual(threads["threads"][0]["availability"], "free")
        self.assertIsNotNone(threads["threads"][0]["last_user_message_at"])
        event_types = [event["event_type"] for event in events["items"]]
        self.assertIn("runtime.turn.queued", event_types)
        self.assertIn("runtime.step.updated", event_types)
        self.assertIn("runtime.tool_call.started", event_types)
        self.assertIn("runtime.tool_call.completed", event_types)
        self.assertIn("runtime.output.delta", event_types)
        self.assertIn("runtime.output.final", event_types)
        self.assertEqual(turn_payload["events"][0]["payload"]["client_message_id"], "client-message-1")
        final_event = next(event for event in events["items"] if event["event_type"] == "runtime.output.final")
        self.assertEqual(final_event["payload"]["text"], "hello from codex")

    def test_runtime_events_api_can_limit_recent_events(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        self.configure_default_provider(state)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "hello from codex"}):
            _status_session, session, _session_headers = self.invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={"agent_id": "chat"},
                cookie=cookie,
            )
            self.invoke(
                app,
                path=f"/api/runtime/sessions/{session['session_id']}/turns",
                method="POST",
                body={"input_text": "hello", "client_message_id": "client-message-1"},
                cookie=cookie,
            )
            status_events, events, _events_headers = self.invoke(
                app,
                path=f"/api/runtime/sessions/{session['session_id']}/events",
                query_string="limit=2",
                cookie=cookie,
            )

        self.assertEqual(status_events, 200)
        self.assertEqual(len(events["items"]), 2)
        self.assertEqual(events["items"][-1]["event_type"], "runtime.turn.completed")

    def test_runtime_turn_api_can_queue_async_turn_and_complete(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        self.configure_default_provider(state)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "async hello"}):
            _status_session, session, _session_headers = self.invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={"agent_id": "chat"},
                cookie=cookie,
            )
            status_turn, turn_payload, _turn_headers = self.invoke(
                app,
                path=f"/api/runtime/sessions/{session['session_id']}/turns",
                method="POST",
                body={"input_text": "hello", "client_message_id": "client-message-async", "async": True},
                cookie=cookie,
            )

            self.assertEqual(status_turn, 202)
            self.assertEqual(turn_payload["turn"]["status"], "queued")
            for _attempt in range(20):
                _status_events, events, _events_headers = self.invoke(
                    app,
                    path=f"/api/runtime/sessions/{session['session_id']}/events",
                    cookie=cookie,
                )
                event_types = [event["event_type"] for event in events["items"]]
                if "runtime.turn.completed" in event_types:
                    break
                time.sleep(0.05)
            self.assertIn("runtime.turn.completed", event_types)
            self.assertIn("runtime.output.final", event_types)
            status_threads, threads, _thread_headers = self.invoke(app, path="/api/runtime/threads", cookie=cookie)

            self.assertEqual(status_threads, 200)
            self.assertEqual(threads["threads"][0]["runtime_session_id"], session["session_id"])
            self.assertEqual(threads["threads"][0]["availability"], "free")

    def test_runtime_session_creation_can_queue_initial_async_turn(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        self.configure_default_provider(state)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "async hello"}):
            status, payload, _headers = self.invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "title": "New chat",
                    "input_text": "ho un problema con il drag and drop nello storage",
                    "client_message_id": "client-message-initial",
                    "async": True,
                },
                cookie=cookie,
            )
            for _attempt in range(20):
                _status_events, events, _events_headers = self.invoke(
                    app,
                    path=f"/api/runtime/sessions/{payload['session']['session_id']}/events",
                    cookie=cookie,
                )
                event_types = [event["event_type"] for event in events["items"]]
                if "runtime.turn.completed" in event_types:
                    break
                time.sleep(0.05)

        self.assertEqual(status, 202)
        self.assertEqual(payload["turn"]["status"], "queued")
        self.assertEqual(payload["turn"]["session_id"], payload["session"]["session_id"])
        self.assertEqual(payload["thread"]["runtime_session_id"], payload["session"]["session_id"])
        self.assertEqual(payload["thread"]["title"], "Problema Drag Drop Storage")
        self.assertIn("runtime.turn.completed", event_types)
        queued_event = next(event for event in payload["events"] if event["event_type"] == "runtime.turn.queued")
        self.assertEqual(queued_event["payload"]["client_message_id"], "client-message-initial")

    def test_workspace_file_upload_persists_under_workspace_storage(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        status, payload, _headers = self.invoke(
            app,
            path="/api/workspace-files/uploads",
            method="POST",
            body={
                "filename": "brief.txt",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(b"brief").decode("ascii"),
            },
            cookie=cookie,
        )

        self.assertEqual(status, 201)
        relative_path = payload["file"]["relative_path"]
        self.assertTrue(relative_path.startswith("storage/uploaded/"))
        self.assertEqual((repo_root / "workspaces" / "default" / relative_path).read_text(encoding="utf-8"), "brief")

    def test_runtime_turn_accepts_attachment_only_input(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        self.configure_default_provider(state)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "saw attachment"}):
            _status_session, session, _session_headers = self.invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={"agent_id": "chat"},
                cookie=cookie,
            )
            status_turn, turn_payload, _turn_headers = self.invoke(
                app,
                path=f"/api/runtime/sessions/{session['session_id']}/turns",
                method="POST",
                body={
                    "input_text": "",
                    "attachments": [
                        {
                            "name": "ChatGPT Image.png",
                            "type": "image/png",
                            "size": 1600000,
                            "relativePath": "storage/uploaded/file-1/ChatGPT-Image.png",
                        }
                    ],
                },
                cookie=cookie,
            )

        self.assertEqual(status_turn, 201)
        self.assertEqual(turn_payload["turn"]["status"], "completed")
        queued_event = next(event for event in turn_payload["events"] if event["event_type"] == "runtime.turn.queued")
        self.assertEqual(queued_event["payload"]["attachments"][0]["relativePath"], "storage/uploaded/file-1/ChatGPT-Image.png")


if __name__ == "__main__":
    unittest.main()
