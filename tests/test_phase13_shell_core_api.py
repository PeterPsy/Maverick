"""Tests for shell-facing core APIs used by base-shell."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import base64
import json
import os
import time
from unittest.mock import patch
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.identity.service import create_user
from core.workspaces.service import ensure_workspace_membership


class ShellCoreApiTestCase(unittest.TestCase):
    """Verify the shell can use generic core APIs instead of static assumptions."""

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
        shutil.copytree(
            source_apps_root / "base-shell",
            repo_root / "apps" / "base-shell",
            ignore=shutil.ignore_patterns("node_modules"),
        )
        shutil.copytree(source_apps_root / "chat", repo_root / "apps" / "chat", ignore=shutil.ignore_patterns("node_modules"))
        shutil.copytree(source_apps_root / "agents", repo_root / "apps" / "agents", ignore=shutil.ignore_patterns("node_modules"))
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
                "username": os.environ.get("MAVERICK3_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK3_ADMIN_PASSWORD", "maverick3"),
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

    def test_workspace_selector_can_create_and_switch_active_workspace(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        status_default_thread, default_thread, _default_thread_headers = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.create", "title": "Default workspace thread"},
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
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.list"},
            cookie=cookie,
        )

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
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "chat" / "threads.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "client-lab" / "data" / "chat" / "threads.json").is_file())
        self.assertNotEqual(
            (repo_root / "workspaces" / "default" / "data" / "chat" / "threads.json").read_text(encoding="utf-8"),
            (repo_root / "workspaces" / "client-lab" / "data" / "chat" / "threads.json").read_text(encoding="utf-8"),
        )

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
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)
        create_status, _created_session, _create_headers = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=cookie,
        )

        status_provider, provider, _provider_headers = self.invoke(app, path="/api/providers/active", cookie=cookie)
        status_runtime, runtime, _runtime_headers = self.invoke(app, path="/api/runtime/status", cookie=cookie)
        status_settings, settings, _settings_headers = self.invoke(app, path="/api/settings/platform", cookie=cookie)
        status_recovery, recovery, _recovery_headers = self.invoke(app, path="/api/recovery/status", cookie=cookie)

        self.assertEqual(create_status, 201)
        self.assertEqual(status_provider, 200)
        self.assertEqual(provider["active_provider"]["provider_id"], "codex")
        self.assertEqual(status_runtime, 200)
        self.assertGreaterEqual(len(runtime["sessions"]), 1)
        self.assertEqual(status_settings, 200)
        self.assertEqual(settings["provider"]["active_provider"]["label"], "Codex")
        self.assertEqual(settings["workspace"]["workspace_id"], "default")
        self.assertEqual(status_recovery, 200)
        self.assertEqual(recovery["workspace_id"], "default")

    def test_runtime_turn_api_executes_selected_provider_and_records_events(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
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
        with patch.dict("os.environ", {"MAVERICK3_RUNTIME_FAKE_RESPONSE": "hello from codex", "MAVERICK3_RUNTIME_FAKE_EVENTS": fake_events}):
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

        self.assertEqual(status_session, 201)
        self.assertEqual(session["provider_id"], "codex")
        self.assertEqual(status_turn, 201)
        self.assertEqual(turn_payload["turn"]["status"], "completed")
        self.assertEqual(status_events, 200)
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
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK3_RUNTIME_FAKE_RESPONSE": "hello from codex"}):
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
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK3_RUNTIME_FAKE_RESPONSE": "async hello"}):
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
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        with patch.dict("os.environ", {"MAVERICK3_RUNTIME_FAKE_RESPONSE": "saw attachment"}):
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
