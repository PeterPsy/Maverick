"""Tests for shell-facing core APIs used by base-shell."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
from unittest.mock import patch
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state


class ShellCoreApiTestCase(unittest.TestCase):
    """Verify the shell can use generic core APIs instead of static assumptions."""

    def make_repo_root(self) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        for name in ("core", "apps", "workspaces", "local-skills", "scripts"):
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
        shutil.copytree(source_apps_root / "chat", repo_root / "apps" / "chat")
        return repo_root

    def invoke(
        self,
        app,
        *,
        path: str,
        method: str = "GET",
        body: dict | None = None,
        cookie: str | None = None,
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

    def login(self, app) -> str:
        status, _payload, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "admin", "password": "maverick3"},
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
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)

        status_create, created, _headers = self.invoke(
            app,
            path="/api/workspaces",
            method="POST",
            body={"name": "Client Lab"},
            cookie=cookie,
        )
        status_list, workspaces, _list_headers = self.invoke(app, path="/api/workspaces", cookie=cookie)
        status_status, platform_status, _status_headers = self.invoke(app, path="/api/status", cookie=cookie)

        self.assertEqual(status_create, 201)
        self.assertEqual(created["workspace_id"], "client-lab")
        self.assertEqual(status_list, 200)
        self.assertEqual(workspaces["active_workspace_id"], "client-lab")
        self.assertEqual(status_status, 200)
        self.assertEqual(platform_status["workspace_id"], "client-lab")
        self.assertEqual({item["app_id"] for item in platform_status["apps"]}, {"base-shell", "chat"})

    def test_provider_runtime_settings_and_recovery_surfaces_are_shell_visible(self) -> None:
        state = bootstrap_platform_state(start_path=self.make_repo_root())
        app = PlatformHost(state, start_path=state.repository_root)
        cookie = self.login(app)
        self.invoke(app, path="/api/apps/chat/backend", method="POST", body={"action": "bootstrap"}, cookie=cookie)

        status_provider, provider, _provider_headers = self.invoke(app, path="/api/providers/active", cookie=cookie)
        status_runtime, runtime, _runtime_headers = self.invoke(app, path="/api/runtime/status", cookie=cookie)
        status_settings, settings, _settings_headers = self.invoke(app, path="/api/settings/platform", cookie=cookie)
        status_recovery, recovery, _recovery_headers = self.invoke(app, path="/api/recovery/status", cookie=cookie)

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

        with patch.dict("os.environ", {"MAVERICK3_RUNTIME_FAKE_RESPONSE": "hello from codex"}):
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
                body={"input_text": "hello"},
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
        self.assertIn("runtime.output.final", event_types)
        self.assertEqual(turn_payload["events"][2]["payload"]["text"], "hello from codex")


if __name__ == "__main__":
    unittest.main()
