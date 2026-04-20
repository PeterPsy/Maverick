"""Tests for the first hosted built-in apps and platform mount flow."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.contracts import (
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_lifecycle,
    build_parsed_app_contract,
    parse_app_contract_file,
    write_app_contract_file,
)
from core.apps.service import install_workspace_local_app, register_workspace_local_app_project_from_contract
from core.cli.service import list_core_cli_commands
from core.mcp.service import list_mcp_tools
from core.runtime.service import create_runtime_session, queue_runtime_turn, transition_runtime_session, transition_runtime_turn
from core.skills.service import list_visible_platform_skills
from core.workspaces.service import create_workspace, ensure_workspace_layout


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
        shutil.copytree(source_apps_root / "agents", repo_root / "apps" / "agents", ignore=shutil.ignore_patterns("node_modules"))
        shutil.copytree(source_apps_root / "skills", repo_root / "apps" / "skills", ignore=shutil.ignore_patterns("node_modules"))
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
    ) -> tuple[int, bytes, dict[str, str]]:
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
                    "QUERY_STRING": query_string,
                    "wsgi.input": BytesIO(payload),
                    **({"HTTP_COOKIE": cookie} if cookie else {}),
                },
                start_response,
            )
        )
        return int(headers["__status__"].split()[0]), result, headers

    def login(self, app) -> str:
        status, _body, headers = self.invoke(
            app,
            path="/api/auth/login",
            method="POST",
            body={"username": "admin", "password": "maverick3"},
        )
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_bootstrap_installs_base_shell_and_chat(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        bindings = state.app_store.list_workspace_app_bindings("default")
        versions = {binding.app_id: binding.active_version for binding in bindings}

        self.assertEqual(sorted(binding.app_id for binding in bindings), ["agents", "base-shell", "chat", "skills"])
        self.assertEqual(versions["base-shell"], "2.0.0")
        self.assertFalse((repo_root / "workspaces" / "default" / "apps" / "base-shell").exists())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "chat" / "threads.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "agents" / "agent_types.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / "state.json").is_file())

    def test_bootstrap_rebuilds_builtin_app_bindings_for_persisted_workspaces(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        workspace = create_workspace(initial_state.workspace_store, name="CEIDA", created_by_user_id="user:admin")
        ensure_workspace_layout(workspace.workspace_id, start_path=repo_root)

        restarted_state = bootstrap_platform_state(start_path=repo_root)

        bindings = restarted_state.app_store.list_workspace_app_bindings(workspace.workspace_id)
        self.assertEqual(sorted(binding.app_id for binding in bindings), ["agents", "base-shell", "chat", "skills"])
        self.assertTrue((repo_root / "workspaces" / "ceida" / "data" / "chat" / "threads.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "ceida" / "data" / "agents" / "agent_types.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "ceida" / "data" / "skills" / "state.json").is_file())

    def test_bootstrap_queues_resume_turn_for_running_session_interrupted_by_backend_restart(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            initial_state.runtime_store,
            session_id="runtime-restart",
            workspace_id="default",
            agent_id="chat",
            governance=initial_state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(initial_state.runtime_store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(initial_state.runtime_store, turn_id="interrupted-turn", session_id=session.session_id, input_text="long work")
        transition_runtime_turn(initial_state.runtime_store, turn_id=turn.turn_id, target_status="active")

        with patch.dict("os.environ", {"MAVERICK3_RUNTIME_FAKE_RESPONSE": "resumed after restart"}):
            restarted_state = bootstrap_platform_state(start_path=repo_root)
            for _attempt in range(20):
                turns = restarted_state.runtime_store.list_turns(session.session_id)
                if any(item.input_text == "resume" and item.status == "completed" for item in turns):
                    break
                time.sleep(0.05)

        turns = restarted_state.runtime_store.list_turns(session.session_id)
        interrupted = restarted_state.runtime_store.get_turn("interrupted-turn")
        resume_turns = [item for item in turns if item.input_text == "resume"]
        event_types = [event.event_type for event in restarted_state.runtime_store.list_events(session.session_id)]

        self.assertEqual(interrupted.status, "failed")
        self.assertEqual(len(resume_turns), 1)
        self.assertEqual(resume_turns[0].status, "completed")
        self.assertIn("runtime.recovery.resume_queued", event_types)
        self.assertIn("runtime.turn.failed", event_types)

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
        self.assertIn(b'id="root"', body_chat)
        self.assertIn(b"/apps/chat/assets/app-", body_chat)

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

    def test_app_registry_skips_enabled_workspace_local_app_with_missing_source(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        local_root = repo_root / "workspaces" / "default" / "apps" / "missing-local"
        parsed = build_parsed_app_contract(
            app_id="missing-local",
            name="Missing Local",
            version="1.0.0",
            description="Workspace-local app whose source was removed.",
            publisher="workspace",
            contract=build_app_contract(
                distribution=build_app_distribution(mode="workspace_local", source_access="editable"),
                lifecycle=build_app_lifecycle(health_check=False),
                entrypoints=build_app_entrypoints(frontend="frontend/dist"),
            ),
        )
        (local_root / "frontend" / "dist").mkdir(parents=True)
        (local_root / "frontend" / "dist" / "index.html").write_text("<div>Missing local</div>", encoding="utf-8")
        write_app_contract_file(local_root, parsed)
        register_workspace_local_app_project_from_contract(
            state.app_store,
            workspace_id="default",
            project_root=str(local_root),
        )
        install_workspace_local_app(state.app_store, workspace_id="default", app_id="missing-local", start_path=repo_root)
        shutil.rmtree(local_root)
        app = PlatformHost(state, start_path=repo_root)

        status, body, _headers = self.invoke(app, path="/api/apps")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertNotIn("missing-local", {item["app_id"] for item in payload["items"]})
        self.assertIn("base-shell", {item["app_id"] for item in payload["items"]})

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
        self.assertNotIn(b"bs-app-topbar", script_body)
        self.assertNotIn(b"TopBar", script_body)
        self.assertNotIn(b"Gallery", script_body)
        self.assertNotIn(b"App Studio", script_body)
        self.assertNotIn(b"Checklists", script_body)
        self.assertIn(b"/apps/base-shell/assets/index-", body_index)

    def test_chat_backend_works_and_exposes_runtime_metadata(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_list, list_body, _ = self.invoke(app, path="/api/apps/chat/backend", method="POST", body={"action": "threads.list"})
        status_create, create_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.create", "runtime_session_id": "runtime-session"},
        )

        list_payload = json.loads(list_body.decode("utf-8"))
        create_payload = json.loads(create_body.decode("utf-8"))

        self.assertEqual(status_list, 200)
        self.assertEqual(status_create, 201)
        self.assertEqual(list_payload["threads"], [])
        self.assertEqual(create_payload["thread"]["runtime_session_id"], "runtime-session")
        self.assertEqual(create_payload["threads"][0]["title"], "New chat")

    def test_chat_backend_stores_runtime_session_agent_metadata(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status, body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={
                "action": "threads.create",
                "runtime_session_id": "runtime-session",
                "title": "Backend Systems Engineer",
                "agent_label": "Backend Systems Engineer",
                "agent_type_id": "backend-systems-engineer",
                "agent_role_id": "backend-systems-engineer",
                "source_app_id": "agents",
            },
        )

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 201)
        self.assertEqual(payload["thread"]["title"], "Backend Systems Engineer")
        self.assertEqual(payload["thread"]["agent_label"], "Backend Systems Engineer")
        self.assertEqual(payload["thread"]["agent_type_id"], "backend-systems-engineer")
        self.assertEqual(payload["thread"]["agent_role_id"], "backend-systems-engineer")
        self.assertEqual(payload["thread"]["source_app_id"], "agents")

    def test_chat_backend_stores_thread_system_prompt(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status, body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={
                "action": "threads.create",
                "runtime_session_id": "",
                "system_prompt": "Use the workspace common prompt.",
            },
        )

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 201)
        self.assertEqual(payload["thread"]["runtime_session_id"], "")
        self.assertEqual(payload["thread"]["system_prompt"], "Use the workspace common prompt.")

    def test_chat_thread_create_reuses_existing_runtime_session(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        first_status, first_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.create", "runtime_session_id": "runtime-session"},
        )
        second_status, second_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.create", "runtime_session_id": "runtime-session"},
        )

        first_payload = json.loads(first_body.decode("utf-8"))
        second_payload = json.loads(second_body.decode("utf-8"))

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(first_payload["thread"]["thread_id"], second_payload["thread"]["thread_id"])
        self.assertEqual(len(second_payload["threads"]), 1)

    def test_chat_surfaces_are_visible_to_agents_and_operators(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_visible_platform_skills(app_store=state.app_store, workspace_id="default", start_path=repo_root)

        self.assertIn("app.chat.threads.list", [tool.tool_name for tool in tools])
        self.assertIn("app.chat.chat", [command.command_id for command in commands])
        self.assertIn("app.chat.chat-ops", [skill.skill_id for skill in skills])

    def test_chat_declares_base_shell_sidebar_widget(self) -> None:
        repo_root = self.make_repo_root()
        parsed = parse_app_contract_file(repo_root / "apps" / "chat")
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}

        self.assertIn("chat-sidebar", widgets)
        self.assertEqual(widgets["chat-sidebar"].host, "base-shell")
        self.assertEqual(widgets["chat-sidebar"].content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(widgets["chat-sidebar"].frontend.mount, "frontend/dist/widgets/chat-sidebar")
        self.assertTrue((repo_root / "apps" / "chat" / "frontend" / "dist" / "widgets" / "chat-sidebar" / "index.html").is_file())

    def test_base_shell_discovers_chat_sidebar_widget_without_source_paths(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=base-shell&content_kind=shell.sidebar.primary",
            cookie=cookie,
        )
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["owner_app_id"], "chat")
        self.assertEqual(payload["items"][0]["widget_id"], "chat-sidebar")
        self.assertEqual(payload["items"][0]["frontend_mount"], "/api/apps/widgets/chat/chat-sidebar/frontend/")
        self.assertNotIn("source_root", payload["items"][0])
        self.assertNotIn("source_path", payload["items"][0])

    def test_chat_sidebar_backend_supports_project_and_thread_settings(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_project, project_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.create", "name": "Client work"},
        )
        project_payload = json.loads(project_body.decode("utf-8"))
        project_id = project_payload["project"]["project_id"]
        status_thread, thread_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.create", "project_id": project_id},
        )
        thread_payload = json.loads(thread_body.decode("utf-8"))
        thread_id = thread_payload["thread"]["thread_id"]
        status_rename, rename_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.update", "thread_id": thread_id, "title": "Audit plan", "project_id": ""},
        )
        rename_payload = json.loads(rename_body.decode("utf-8"))
        status_delete, delete_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.delete", "thread_id": thread_id},
        )
        delete_payload = json.loads(delete_body.decode("utf-8"))

        self.assertEqual(status_project, 201)
        self.assertEqual(status_thread, 201)
        self.assertEqual(status_rename, 200)
        self.assertEqual(status_delete, 200)
        self.assertEqual(rename_payload["thread"]["title"], "Audit plan")
        self.assertIsNone(rename_payload["thread"]["project_id"])
        self.assertEqual(delete_payload["threads"], [])

    def test_chat_thread_delete_stops_linked_runtime_session(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        session = create_runtime_session(
            state.runtime_store,
            session_id="runtime-to-delete",
            workspace_id="default",
            agent_id="chat",
            governance=state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(state.runtime_store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(state.runtime_store, turn_id="turn-to-delete", session_id=session.session_id, input_text="work")
        transition_runtime_turn(state.runtime_store, turn_id=turn.turn_id, target_status="active")
        status_thread, thread_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.create", "runtime_session_id": session.session_id},
        )
        thread_payload = json.loads(thread_body.decode("utf-8"))
        thread_id = thread_payload["thread"]["thread_id"]

        status_delete, delete_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "threads.delete", "thread_id": thread_id},
        )
        delete_payload = json.loads(delete_body.decode("utf-8"))

        self.assertEqual(status_thread, 201)
        self.assertEqual(status_delete, 200)
        self.assertEqual(delete_payload["deleted_runtime_session_id"], session.session_id)
        self.assertEqual(delete_payload["runtime_termination"]["session_id"], session.session_id)
        self.assertEqual(delete_payload["runtime_termination"]["cancelled_turns"], 1)
        self.assertEqual(state.runtime_store.get_session(session.session_id).status, "stopped")
        self.assertEqual(state.runtime_store.get_turn(turn.turn_id).status, "cancelled")


if __name__ == "__main__":
    unittest.main()
