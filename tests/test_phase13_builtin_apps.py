"""Tests for the first hosted built-in apps and platform mount flow."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import parse_app_contract_file
from core.cli.service import list_core_cli_commands
from core.mcp.service import list_mcp_tools
from core.skills.service import list_visible_platform_skills


class Phase13BuiltinAppsTestCase(unittest.TestCase):
    """Verify first-boot built-in apps are mounted by the core host."""

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

    def invoke(self, app, *, path: str, method: str = "GET", body: dict | None = None) -> tuple[int, bytes, dict[str, str]]:
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
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
                },
                start_response,
            )
        )
        return int(headers["__status__"].split()[0]), result, headers

    def test_bootstrap_installs_base_shell_and_chat(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        versions = {binding.app_id: binding.active_version for binding in bindings}

        self.assertEqual(sorted(binding.app_id for binding in bindings), ["base-shell", "chat"])
        self.assertEqual(versions["base-shell"], "2.0.0")
        self.assertFalse((repo_root / "workspaces" / "default" / "apps" / "base-shell").exists())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "chat" / "conversations.json").is_file())

    def test_platform_host_mounts_root_shell_and_chat_frontend(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_root, body_root, _headers_root = self.invoke(app, path="/")
        status_chat, body_chat, _headers_chat = self.invoke(app, path="/apps/chat/")

        self.assertEqual(status_root, 200)
        self.assertEqual(status_chat, 200)
        self.assertIn(b'id="root"', body_root)
        self.assertIn(b"/apps/base-shell/assets/index-", body_root)
        self.assertNotIn(b"Base shell app mounted by the core", body_root)
        self.assertNotIn(b'src="/apps/chat/"', body_root)
        self.assertIn(b"Minimal built-in app mounted by the Maverick core", body_chat)

    def test_base_shell_contract_mounts_production_dist(self) -> None:
        repo_root = self.make_repo_root()

        parsed = parse_app_contract_file(repo_root / "apps" / "base-shell")

        self.assertEqual(parsed.app_id, "base-shell")
        self.assertEqual(parsed.contract.entrypoints.frontend, "frontend/dist")
        self.assertTrue((repo_root / "apps" / "base-shell" / "frontend" / "dist" / "index.html").is_file())

    def test_base_shell_is_v3_native_without_legacy_runtime_coupling(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_root, body_root, _headers_root = self.invoke(app, path="/")

        self.assertEqual(status_root, 200)
        self.assertNotIn(b'app_id === "chat"', body_root)
        self.assertNotIn(b"apps/base_shell", body_root)
        self.assertNotIn(b"app.manifest", body_root)
        self.assertNotIn(b"runtime_backend", body_root)
        self.assertNotIn(b"react-query", body_root)
        self.assertNotIn(b"Gallery", body_root)
        self.assertNotIn(b"App Studio", body_root)
        self.assertNotIn(b"Checklists", body_root)

    def test_app_registry_exposes_distribution_policy_for_shell(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status, body, _headers = self.invoke(app, path="/api/apps")
        payload = json.loads(body.decode("utf-8"))
        items = {item["app_id"]: item for item in payload["items"]}

        self.assertEqual(status, 200)
        self.assertEqual(items["base-shell"]["distribution_mode"], "sealed")
        self.assertEqual(items["base-shell"]["source_access"], "none")
        self.assertEqual(items["base-shell"]["description"], "Maverick v3 product shell app that hosts enabled app frontends through the platform registry.")
        self.assertEqual(items["base-shell"]["views"], ["shell"])
        self.assertEqual(
            set(items["base-shell"]),
            {
                "app_id",
                "name",
                "version",
                "description",
                "publisher",
                "status",
                "distribution_mode",
                "source_access",
                "views",
                "logo",
                "frontend_mount",
                "backend_mount",
            },
        )

    def test_base_shell_uses_registry_without_fake_static_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_index, body_index, _ = self.invoke(app, path="/apps/base-shell/")
        status_asset, logo_body, _ = self.invoke(app, path="/apps/base-shell/maverick-logo.png")
        script_path = next((repo_root / "apps" / "base-shell" / "frontend" / "dist" / "assets").glob("index-*.js")).name
        status_script, script_body, _ = self.invoke(app, path=f"/apps/base-shell/assets/{script_path}")

        self.assertEqual(status_index, 200)
        self.assertEqual(status_asset, 200)
        self.assertEqual(status_script, 200)
        self.assertGreater(len(logo_body), 100)
        self.assertLess(len(logo_body), 10_000)
        self.assertIn(b"/api/apps", script_body)
        self.assertIn(b"/api/status", script_body)
        self.assertIn(b"chat", script_body)
        self.assertNotIn(b"Gallery", script_body)
        self.assertNotIn(b"App Studio", script_body)
        self.assertNotIn(b"Checklists", script_body)
        self.assertIn(b"/apps/base-shell/assets/index-", body_index)

    def test_chat_backend_works_and_exposes_runtime_metadata(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_bootstrap, bootstrap_body, _ = self.invoke(app, path="/api/apps/chat/backend", method="POST", body={"action": "bootstrap"})
        status_send, send_body, _ = self.invoke(app, path="/api/apps/chat/backend", method="POST", body={"action": "send", "message": "hello"})

        bootstrap_payload = json.loads(bootstrap_body.decode("utf-8"))
        send_payload = json.loads(send_body.decode("utf-8"))

        self.assertEqual(status_bootstrap, 200)
        self.assertEqual(status_send, 200)
        self.assertEqual(bootstrap_payload["app_id"], "chat")
        self.assertEqual(send_payload["provider_id"], "codex")
        self.assertTrue(send_payload["runtime_session_id"].startswith("default:chat:ui"))
        self.assertGreaterEqual(len(send_payload["messages"]), 3)

    def test_chat_surfaces_are_visible_to_agents_and_operators(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_visible_platform_skills(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.chat.threads.list", [tool.tool_name for tool in tools])
        self.assertIn("app.chat.chat", [command.command_id for command in commands])
        self.assertIn("app.chat.chat-ops", [skill.skill_id for skill in skills])


if __name__ == "__main__":
    unittest.main()
