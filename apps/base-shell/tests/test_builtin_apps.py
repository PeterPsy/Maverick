"""Tests for the first hosted built-in apps and platform mount flow."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import json
import os
import shutil
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
from core.apps.models import WorkspaceAppBindingRecord
from core.apps.service import install_workspace_local_app, register_app_source_from_contract, register_workspace_local_app_project_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from core.cli.service import list_core_cli_commands
from core.mcp.service import list_mcp_tools
from core.providers.service import configure_workspace_provider
from core.recovery.backend_restart import BACKEND_RESTART_CONTINUATION_INPUT_TEXT
from core.runtime.errors import RuntimeSessionNotFoundError, RuntimeTurnNotFoundError
from core.runtime.service import (
    create_runtime_session,
    queue_runtime_turn,
    record_runtime_event,
    transition_runtime_session,
    transition_runtime_turn,
)
from core.skills.service import list_available_workspace_skills
from core.shared.in_memory_collection import InMemoryCollection
from core.workspaces.service import create_workspace, ensure_workspace_layout
from tests.support.markers import slow_test_class
from tests.support.repo import make_temp_repo_root, link_app_sources, write_synthetic_platform_app


def _is_noop_frontend_build_script(script: str) -> bool:
    normalized = script.replace(" ", "").replace("'", '"').lower()
    return "process.exit(0)" in normalized or "accesssync(\"frontend/dist/index.html\")" in normalized


@slow_test_class("slow builtin-app bootstrap suite; run with scripts/test_suite.py --level slow")
class BuiltinAppsTestCase(unittest.TestCase):
    """Verify first-boot built-in apps are mounted by the core host."""

    def make_repo_root(self) -> Path:
        repo_root = make_temp_repo_root(self, include_core=True)
        link_app_sources(repo_root, ["base-shell"])
        self.write_shell_dependency_apps(repo_root)
        return repo_root

    def make_product_repo_root(self) -> Path:
        repo_root = make_temp_repo_root(self, include_core=True)
        link_app_sources(repo_root, ["base-shell", "chat", "agents", "skills"])
        return repo_root

    def write_shell_dependency_apps(self, repo_root: Path) -> None:
        write_synthetic_platform_app(
            repo_root,
            app_id="chat",
            name="Chat",
            backend=True,
            cli_commands=["chat"],
            mcp_tools=["chat_reference_search"],
            skills=["chat-ops"],
            views=["chat"],
            runtime_create_sessions=True,
            widget_specs=[
                {
                    "widget_id": "chat-sidebar",
                    "host": "base-shell",
                    "content_kinds": ["shell.sidebar.primary"],
                    "mount": "frontend/dist/widgets/chat-sidebar",
                    "backend": True,
                },
                {
                    "widget_id": "chat-floating",
                    "host": "base-shell",
                    "content_kinds": ["shell.overlay.bottomright"],
                    "mount": "frontend/dist/widgets/chat-floating",
                    "backend": True,
                },
            ],
        )
        write_synthetic_platform_app(
            repo_root,
            app_id="agents",
            name="Agents",
            backend=True,
            cli_commands=["agents"],
            mcp_tools=["maverick_agents_app"],
            skills=["agents-ops"],
            views=["agents"],
        )
        write_synthetic_platform_app(
            repo_root,
            app_id="skills",
            name="Skills",
            backend=True,
            cli_commands=["skills"],
            mcp_tools=["maverick_skills_app"],
            skills=["skills-ops"],
            views=["skills"],
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
            body={
                "username": os.environ.get("MAVERICK_ADMIN_USERNAME", "admin"),
                "password": os.environ.get("MAVERICK_ADMIN_PASSWORD", "maverick"),
            },
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
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "chat" / ".maverick-app.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "agents" / ".maverick-app.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "default" / "data" / "skills" / ".maverick-app.json").is_file())

    def test_builtin_frontend_apps_have_honest_build_scripts(self) -> None:
        apps_root = Path(__file__).resolve().parents[3] / "apps"
        missing: list[str] = []
        noop_build_scripts: list[str] = []
        for contract_path in sorted(apps_root.glob("*/app_contract.json")):
            parsed = parse_app_contract_file(contract_path.parent)
            frontend = parsed.contract.entrypoints.frontend
            if frontend is None:
                continue
            package_roots = [contract_path.parent, contract_path.parent / frontend.split("/", 1)[0]]
            has_build_script = False
            for package_root in package_roots:
                package_path = package_root / "package.json"
                if not package_path.is_file():
                    continue
                package_payload = json.loads(package_path.read_text(encoding="utf-8"))
                scripts = package_payload.get("scripts") if isinstance(package_payload, dict) else None
                build_script = str(scripts.get("build") or "").strip() if isinstance(scripts, dict) else ""
                has_build_script = bool(build_script)
                if has_build_script:
                    if _is_noop_frontend_build_script(build_script):
                        noop_build_scripts.append(parsed.app_id)
                    break
            if not has_build_script:
                missing.append(parsed.app_id)

        self.assertEqual(missing, [])
        self.assertEqual(noop_build_scripts, [])

    def test_all_builtin_frontend_apps_expose_frontend_build_cli(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        source_apps_root = Path(__file__).resolve().parents[3] / "apps"
        app_store = AppDocumentStore(
            AppCollections(
                app_sources=InMemoryCollection(),
                workspace_local_app_projects=InMemoryCollection(),
                workspace_app_bindings=InMemoryCollection(),
                workspace_app_dependency_selections=InMemoryCollection(),
            )
        )
        for source_app_root in sorted(source_apps_root.iterdir()):
            if not source_app_root.is_dir() or not (source_app_root / "app_contract.json").is_file():
                continue
            source = register_app_source_from_contract(
                app_store,
                source_kind="platform",
                source_path=str(source_app_root),
            )
            app_store.save_workspace_app_binding(
                WorkspaceAppBindingRecord(
                    binding_id=f"default:{source.app_id}",
                    workspace_id="default",
                    app_id=source.app_id,
                    source_record_id=source.source_id,
                    source_kind=source.source_kind,
                    status="enabled",
                    active_version=source.version,
                    data_root=f"workspaces/default/data/{source.app_id}",
                    installed_at=source.created_at,
                    updated_at=source.updated_at,
                )
            )

        commands = {
            command.command_id
            for command in list_core_cli_commands(
                app_store=app_store,
                workspace_id="default",
                start_path=repo_root,
            )
        }
        expected = []
        for contract_path in sorted(source_apps_root.glob("*/app_contract.json")):
            parsed = parse_app_contract_file(contract_path.parent)
            if parsed.contract.entrypoints.frontend is not None:
                expected.append(f"app.{parsed.app_id}.frontend.build")

        missing = [command_id for command_id in expected if command_id not in commands]

        self.assertEqual(missing, [])

    def test_bootstrap_rebuilds_builtin_app_bindings_for_persisted_workspaces(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        workspace = create_workspace(initial_state.workspace_store, name="CEIDA", created_by_user_id="user:admin")
        ensure_workspace_layout(workspace.workspace_id, start_path=repo_root)

        restarted_state = bootstrap_platform_state(start_path=repo_root)

        bindings = restarted_state.app_store.list_workspace_app_bindings(workspace.workspace_id)
        self.assertEqual(sorted(binding.app_id for binding in bindings), ["agents", "base-shell", "chat", "skills"])
        self.assertTrue((repo_root / "workspaces" / "ceida" / "data" / "chat" / ".maverick-app.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "ceida" / "data" / "agents" / ".maverick-app.json").is_file())
        self.assertTrue((repo_root / "workspaces" / "ceida" / "data" / "skills" / ".maverick-app.json").is_file())

    def test_bootstrap_queues_resume_turn_for_running_session_interrupted_by_backend_restart(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        configure_workspace_provider(initial_state.provider_store, workspace_id="default", provider_id="codex")
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

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "resumed after restart"}):
            restarted_state = bootstrap_platform_state(start_path=repo_root, recover_backend_restart=True)
            for _attempt in range(100):
                turns = restarted_state.runtime_store.list_turns(session.session_id)
                if any(item.input_text == BACKEND_RESTART_CONTINUATION_INPUT_TEXT and item.status == "completed" for item in turns):
                    break
                time.sleep(0.05)

        turns = restarted_state.runtime_store.list_turns(session.session_id)
        interrupted = restarted_state.runtime_store.get_turn("interrupted-turn")
        resume_turns = [item for item in turns if item.input_text == BACKEND_RESTART_CONTINUATION_INPUT_TEXT]
        event_types = [event.event_type for event in restarted_state.runtime_store.list_events(session.session_id)]

        self.assertEqual(interrupted.status, "failed")
        self.assertEqual(len(resume_turns), 1)
        self.assertEqual(resume_turns[0].status, "completed")
        self.assertIn("runtime.recovery.resume_queued", event_types)
        self.assertIn("runtime.turn.failed", event_types)

    def test_regular_platform_bootstrap_does_not_recover_active_runtime_turns(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            initial_state.runtime_store,
            session_id="runtime-cli-bootstrap",
            workspace_id="default",
            agent_id="chat",
            governance=initial_state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(initial_state.runtime_store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(initial_state.runtime_store, turn_id="active-turn", session_id=session.session_id, input_text="active work")
        transition_runtime_turn(initial_state.runtime_store, turn_id=turn.turn_id, target_status="active")

        cli_state = bootstrap_platform_state(start_path=repo_root)

        event_types = [event.event_type for event in cli_state.runtime_store.list_events(session.session_id)]
        self.assertEqual(cli_state.runtime_store.get_turn(turn.turn_id).status, "active")
        self.assertNotIn("runtime.turn.failed", event_types)
        self.assertNotIn("runtime.recovery.resume_queued", event_types)

    def test_bootstrap_does_not_resume_turn_that_already_has_terminal_output(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            initial_state.runtime_store,
            session_id="runtime-terminal-event",
            workspace_id="default",
            agent_id="chat",
            governance=initial_state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(initial_state.runtime_store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(initial_state.runtime_store, turn_id="terminal-output-turn", session_id=session.session_id, input_text="done work")
        transition_runtime_turn(initial_state.runtime_store, turn_id=turn.turn_id, target_status="active")
        record_runtime_event(
            initial_state.runtime_store,
            event_id="terminal-output",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.output.final",
            payload={"text": "done", "exit_code": 0},
            event_bus=initial_state.runtime_event_bus,
        )

        restarted_state = bootstrap_platform_state(start_path=repo_root, recover_backend_restart=True)

        turns = restarted_state.runtime_store.list_turns(session.session_id)
        event_types = [event.event_type for event in restarted_state.runtime_store.list_events(session.session_id)]

        self.assertEqual(restarted_state.runtime_store.get_turn(turn.turn_id).status, "completed")
        self.assertFalse([item for item in turns if item.input_text == BACKEND_RESTART_CONTINUATION_INPUT_TEXT])
        self.assertIn("runtime.turn.completed", event_types)
        self.assertNotIn("runtime.recovery.resume_queued", event_types)

    def test_bootstrap_retries_interrupted_backend_restart_resume_turn_with_limit(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        configure_workspace_provider(initial_state.provider_store, workspace_id="default", provider_id="codex")
        session = create_runtime_session(
            initial_state.runtime_store,
            session_id="runtime-resume-loop",
            workspace_id="default",
            agent_id="chat",
            governance=initial_state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(initial_state.runtime_store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(
            initial_state.runtime_store,
            turn_id="resume-turn",
            session_id=session.session_id,
            input_text=BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
        )
        transition_runtime_turn(initial_state.runtime_store, turn_id=turn.turn_id, target_status="active")
        record_runtime_event(
            initial_state.runtime_store,
            event_id="resume-queued",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            plane="turn",
            event_type="runtime.turn.queued",
            payload={
                "input_text": BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
                "client_message_id": f"backend-restart-resume:{session.session_id}:1",
            },
            event_bus=initial_state.runtime_event_bus,
        )

        with patch.dict("os.environ", {"MAVERICK_RUNTIME_FAKE_RESPONSE": "resumed after interrupted resume"}):
            restarted_state = bootstrap_platform_state(start_path=repo_root, recover_backend_restart=True)
            for _attempt in range(100):
                turns = restarted_state.runtime_store.list_turns(session.session_id)
                if [item for item in turns if item.input_text == BACKEND_RESTART_CONTINUATION_INPUT_TEXT and item.status == "completed"]:
                    break
                time.sleep(0.05)

        turns = restarted_state.runtime_store.list_turns(session.session_id)
        event_types = [event.event_type for event in restarted_state.runtime_store.list_events(session.session_id)]
        resume_turns = [item for item in turns if item.input_text == BACKEND_RESTART_CONTINUATION_INPUT_TEXT]

        self.assertEqual(restarted_state.runtime_store.get_turn(turn.turn_id).status, "failed")
        self.assertEqual(len(resume_turns), 2)
        self.assertTrue(any(item.status == "completed" for item in resume_turns))
        self.assertIn("runtime.recovery.resume_queued", event_types)

    def test_bootstrap_stops_retrying_backend_restart_resume_turns_after_limit(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        configure_workspace_provider(initial_state.provider_store, workspace_id="default", provider_id="codex")
        session = create_runtime_session(
            initial_state.runtime_store,
            session_id="runtime-resume-limit",
            workspace_id="default",
            agent_id="chat",
            governance=initial_state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(initial_state.runtime_store, session_id=session.session_id, target_status="running")
        turn = queue_runtime_turn(
            initial_state.runtime_store,
            turn_id="resume-turn-limit",
            session_id=session.session_id,
            input_text=BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
        )
        transition_runtime_turn(initial_state.runtime_store, turn_id=turn.turn_id, target_status="active")
        for attempt in range(3):
            record_runtime_event(
                initial_state.runtime_store,
                event_id=f"resume-queued-{attempt}",
                session_id=session.session_id,
                turn_id=turn.turn_id,
                plane="turn",
                event_type="runtime.turn.queued",
                payload={
                    "input_text": BACKEND_RESTART_CONTINUATION_INPUT_TEXT,
                    "client_message_id": f"backend-restart-resume:{session.session_id}:{attempt}",
                },
                event_bus=initial_state.runtime_event_bus,
            )

        restarted_state = bootstrap_platform_state(start_path=repo_root, recover_backend_restart=True)

        turns = restarted_state.runtime_store.list_turns(session.session_id)
        event_types = [event.event_type for event in restarted_state.runtime_store.list_events(session.session_id)]

        self.assertEqual(restarted_state.runtime_store.get_turn(turn.turn_id).status, "failed")
        self.assertEqual([item.input_text for item in turns].count(BACKEND_RESTART_CONTINUATION_INPUT_TEXT), 1)
        self.assertNotIn("runtime.recovery.resume_queued", event_types)

    def test_bootstrap_closes_orphan_non_terminal_turn_events_after_backend_restart(self) -> None:
        repo_root = self.make_repo_root()
        initial_state = bootstrap_platform_state(start_path=repo_root)
        session = create_runtime_session(
            initial_state.runtime_store,
            session_id="runtime-orphan-event",
            workspace_id="default",
            agent_id="chat",
            governance=initial_state.workspace_store.get_governance("default"),
            platform_allows_full_access=True,
            start_path=repo_root,
        )
        transition_runtime_session(initial_state.runtime_store, session_id=session.session_id, target_status="running")
        record_runtime_event(
            initial_state.runtime_store,
            event_id="orphan-queued-event",
            session_id=session.session_id,
            turn_id="missing-turn",
            plane="turn",
            event_type="runtime.turn.queued",
            payload={"input_text": BACKEND_RESTART_CONTINUATION_INPUT_TEXT},
            event_bus=initial_state.runtime_event_bus,
        )

        restarted_state = bootstrap_platform_state(start_path=repo_root, recover_backend_restart=True)

        event_types = [event.event_type for event in restarted_state.runtime_store.list_events(session.session_id)]
        self.assertIn("runtime.turn.queued", event_types)
        self.assertIn("runtime.turn.cancelled", event_types)
        self.assertEqual(restarted_state.runtime_store.list_turns(session.session_id), [])

    def test_platform_host_mounts_root_shell_and_chat_frontend(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_root, body_root, _headers_root = self.invoke(app, path="/")
        status_shell_deep_link, body_shell_deep_link, _headers_shell_deep_link = self.invoke(app, path="/app/chat/threads/thread-123")
        status_chat, body_chat, _headers_chat = self.invoke(app, path="/apps/chat/", cookie=cookie)

        self.assertEqual(status_root, 200)
        self.assertEqual(status_shell_deep_link, 200)
        self.assertEqual(status_chat, 200)
        self.assertIn(b'id="root"', body_root)
        self.assertIn(b'id="root"', body_shell_deep_link)
        self.assertIn(b"/apps/base-shell/assets/index-", body_shell_deep_link)
        self.assertIn(b"/apps/base-shell/assets/index-", body_root)
        self.assertNotIn(b"Base shell app mounted by the core", body_root)
        self.assertNotIn(b'src="/apps/chat/"', body_root)
        self.assertIn(b'id="root"', body_chat)
        self.assertIn(b"/apps/chat/assets/app-", body_chat)

    def test_platform_host_serves_root_shell_pwa_assets_without_session(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_manifest, manifest_body, manifest_headers = self.invoke(app, path="/manifest.webmanifest")
        status_worker, worker_body, worker_headers = self.invoke(app, path="/sw.js")

        self.assertEqual(status_manifest, 200)
        self.assertEqual(status_worker, 200)
        self.assertEqual(manifest_headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(worker_headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(manifest_headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(worker_headers["Access-Control-Allow-Origin"], "*")
        self.assertIn(b'"name"', manifest_body)
        self.assertIn(b"maverick-base-shell", worker_body)

    def test_app_backend_calls_do_not_create_runtime_turns(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _headers = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.list"},
            cookie=cookie,
        )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("projects", payload)
        self.assertNotIn("threads", payload)
        self.assertFalse(any(session.session_id == "default:chat:ui" for session in state.runtime_store.list_sessions("default")))
        self.assertEqual(state.runtime_store.list_turns("default:chat:ui"), [])
        self.assertEqual(state.runtime_store.list_events("default:chat:ui"), [])

    def test_platform_host_uses_configured_root_shell_app(self) -> None:
        repo_root = self.make_repo_root()
        with patch.dict("os.environ", {"MAVERICK_ROOT_SHELL_APP_ID": "chat"}):
            state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        status_root, body_root, _headers_root = self.invoke(app, path="/")

        self.assertEqual(state.root_shell_app_id, "chat")
        self.assertEqual(status_root, 200)
        self.assertIn(b"/apps/chat/assets/app-", body_root)

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
        cookie = self.login(app)

        status, body, _headers = self.invoke(app, path="/api/apps", cookie=cookie)
        payload = json.loads(body.decode("utf-8"))
        items = {item["app_id"]: item for item in payload["items"]}

        self.assertEqual(status, 200)
        self.assertEqual(items["base-shell"]["distribution_mode"], "sealed")
        self.assertEqual(items["base-shell"]["source_access"], "none")
        self.assertEqual(items["base-shell"]["description"], "Maverick product shell app that hosts enabled app frontends through the platform registry.")
        self.assertEqual(items["base-shell"]["views"], ["shell"])
        self.assertEqual(items["base-shell"]["frontend_role"], "supporting")
        self.assertFalse(items["base-shell"]["frontend_launchable"])
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
                "provides",
                "requires",
                "logo",
                "frontend_mount",
                "frontend_role",
                "frontend_launchable",
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
        cookie = self.login(app)

        status, body, _headers = self.invoke(app, path="/api/apps", cookie=cookie)
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertNotIn("missing-local", {item["app_id"] for item in payload["items"]})
        self.assertIn("base-shell", {item["app_id"] for item in payload["items"]})

    def test_app_registry_skips_enabled_app_after_unexpected_surface_failure(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        real_bindings = state.app_store.list_workspace_app_bindings("default")
        target_binding = next(binding for binding in real_bindings if binding.app_id == "chat")

        def broken_enabled_bindings(_store, *, workspace_id: str):
            return real_bindings

        def broken_resolve_surface(_store, *, binding, start_path=None):
            if binding.app_id == target_binding.app_id:
                raise RuntimeError("unexpected parse failure")
            from core.apps.surfaces import resolve_workspace_app_surface as real_resolve_workspace_app_surface

            return real_resolve_workspace_app_surface(_store, binding=binding, start_path=start_path)

        with patch("core.api.app_registry.enabled_workspace_app_bindings", broken_enabled_bindings), patch(
            "core.api.app_registry.resolve_workspace_app_surface",
            broken_resolve_surface,
        ):
            status, body, _headers = self.invoke(app, path="/api/apps", cookie=cookie)

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertNotIn("chat", {item["app_id"] for item in payload["items"]})
        self.assertIn("base-shell", {item["app_id"] for item in payload["items"]})

    def test_root_shell_returns_service_unavailable_after_unexpected_frontend_failure(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        with patch("core.api.app_mounts.serve_frontend", side_effect=RuntimeError("frontend crash")):
            status, body, _headers = self.invoke(app, path="/")

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "shell_unavailable")

    def test_app_frontend_mount_returns_not_found_after_unexpected_frontend_failure(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        with patch("core.api.app_mounts.serve_frontend", side_effect=RuntimeError("frontend crash")):
            status, body, _headers = self.invoke(app, path="/apps/chat/", cookie=cookie)

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "app_unavailable")

    def test_platform_host_returns_internal_server_error_for_unhandled_route_exception(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        with patch("core.api.platform_host.handle_workspace_api", side_effect=RuntimeError("route crash")):
            status, body, _headers = self.invoke(app, path="/api/status")

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "internal_server_error")

    def test_base_shell_uses_registry_without_fake_static_apps(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_index, body_index, index_headers = self.invoke(app, path="/apps/base-shell/", cookie=cookie)
        status_asset, logo_body, _ = self.invoke(app, path="/apps/base-shell/maverick-logo.png", cookie=cookie)
        script_path = next((repo_root / "apps" / "base-shell" / "frontend" / "dist" / "assets").glob("index-*.js")).name
        status_script, script_body, script_headers = self.invoke(app, path=f"/apps/base-shell/assets/{script_path}", cookie=cookie)

        self.assertEqual(status_index, 200)
        self.assertEqual(status_asset, 200)
        self.assertEqual(status_script, 200)
        self.assertEqual(index_headers["Cache-Control"], "no-store")
        self.assertEqual(script_headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(script_headers["Access-Control-Allow-Origin"], "*")
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

    def test_app_frontend_assets_are_public_for_sandboxed_iframes(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)

        chat_script_path = next((repo_root / "apps" / "chat" / "frontend" / "dist" / "assets").glob("app-*.js")).name
        status_index, index_body, _index_headers = self.invoke(app, path="/apps/chat/")
        status_script, script_body, script_headers = self.invoke(app, path=f"/apps/chat/assets/{chat_script_path}")

        self.assertEqual(status_index, 401)
        self.assertIn(b"authentication_required", index_body)
        self.assertEqual(status_script, 200)
        self.assertEqual(script_headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(script_headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(script_headers["Cross-Origin-Resource-Policy"], "cross-origin")
        self.assertGreater(len(script_body), 100)

    def test_chat_backend_owns_projects_not_threads(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_list, list_body, _ = self.invoke(app, path="/api/apps/chat/backend", method="POST", body={"action": "projects.list"}, cookie=cookie)
        status_create, create_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.create", "name": "Client work"},
            cookie=cookie,
        )

        list_payload = json.loads(list_body.decode("utf-8"))
        create_payload = json.loads(create_body.decode("utf-8"))

        self.assertEqual(status_list, 200)
        self.assertEqual(status_create, 201)
        self.assertEqual(list_payload["projects"], [])
        self.assertEqual(create_payload["project"]["name"], "Client work")
        self.assertEqual(create_payload["projects"][0]["name"], "Client work")
        self.assertNotIn("threads", create_payload)

    def test_core_runtime_thread_stores_agent_metadata(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        session_status, session_body, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={
                "agent_id": "Backend Systems Engineer",
                "agent_type_id": "backend-systems-engineer",
                "agent_role_id": "backend-systems-engineer",
                "source_app_id": "agents",
                "title": "Backend Systems Engineer",
            },
            cookie=cookie,
        )
        session = json.loads(session_body.decode("utf-8"))
        status, body, _ = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={
                "runtime_session_id": session["session_id"],
                "title": "Backend Systems Engineer",
                "agent_label": "Backend Systems Engineer",
                "agent_type_id": "backend-systems-engineer",
                "agent_role_id": "backend-systems-engineer",
                "source_app_id": "agents",
            },
            cookie=cookie,
        )

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(session_status, 201)
        self.assertEqual(status, 201)
        self.assertEqual(payload["thread"]["title"], "Backend Systems Engineer")
        self.assertEqual(payload["thread"]["agent_label"], "Backend Systems Engineer")
        self.assertEqual(payload["thread"]["agent_type_id"], "backend-systems-engineer")
        self.assertEqual(payload["thread"]["agent_role_id"], "backend-systems-engineer")
        self.assertEqual(payload["thread"]["source_app_id"], "agents")

    def test_core_runtime_thread_stores_system_prompt(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status, body, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={
                "agent_id": "chat",
                "system_prompt": "Use the workspace common prompt.",
            },
            cookie=cookie,
        )

        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 201)
        self.assertEqual(payload["system_prompt"], "Use the workspace common prompt.")
        self.assertEqual(state.runtime_store.get_thread(payload["session_id"]).system_prompt, "Use the workspace common prompt.")

    def test_core_runtime_thread_create_reuses_existing_runtime_session(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        session_status, session_body, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat"},
            cookie=cookie,
        )
        session = json.loads(session_body.decode("utf-8"))
        first_status, first_body, _ = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": session["session_id"]},
            cookie=cookie,
        )
        second_status, second_body, _ = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": session["session_id"]},
            cookie=cookie,
        )

        first_payload = json.loads(first_body.decode("utf-8"))
        second_payload = json.loads(second_body.decode("utf-8"))

        self.assertEqual(session_status, 201)
        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertEqual(first_payload["thread"]["thread_id"], second_payload["thread"]["thread_id"])
        self.assertEqual(len(second_payload["threads"]), 1)

    def test_chat_surfaces_are_visible_to_agents_and_operators(self) -> None:
        repo_root = self.make_product_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)

        tools = list_mcp_tools(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        commands = list_core_cli_commands(app_store=state.app_store, workspace_id="default", start_path=repo_root)
        skills = list_available_workspace_skills(workspace_id="default", start_path=repo_root)

        self.assertIn("app.chat.chat_reference_search", [tool.tool_name for tool in tools])
        self.assertIn("app.chat.chat", [command.command_id for command in commands])
        self.assertIn("chat-ops", [skill.skill_id for skill in skills])

    def test_chat_declares_base_shell_widgets(self) -> None:
        repo_root = self.make_product_repo_root()
        parsed = parse_app_contract_file(repo_root / "apps" / "chat")
        self.assertIn("chat_set_view_filter", parsed.contract.capabilities.mcp_tools)
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].view_id, "chat")
        self.assertEqual(parsed.contract.capabilities.view_surfaces[0].entity_types, ["project"])
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}

        self.assertIn("chat-sidebar", widgets)
        self.assertEqual(widgets["chat-sidebar"].host, "base-shell")
        self.assertEqual(widgets["chat-sidebar"].content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(widgets["chat-sidebar"].frontend.mount, "frontend/dist/widgets/chat-sidebar")
        self.assertTrue((repo_root / "apps" / "chat" / "frontend" / "dist" / "widgets" / "chat-sidebar" / "index.html").is_file())
        self.assertIn("chat-floating", widgets)
        self.assertEqual(widgets["chat-floating"].host, "base-shell")
        self.assertEqual(widgets["chat-floating"].content_kinds, ["shell.overlay.bottomright"])
        self.assertEqual(widgets["chat-floating"].frontend.mount, "frontend/dist/widgets/chat-floating")
        self.assertTrue((repo_root / "apps" / "chat" / "frontend" / "dist" / "widgets" / "chat-floating" / "index.html").is_file())

    def test_base_shell_discovers_chat_widgets_without_source_paths(self) -> None:
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

        overlay_status, overlay_body, _overlay_headers = self.invoke(
            app,
            path="/api/apps/widgets",
            query_string="host=base-shell&content_kind=shell.overlay.bottomright",
            cookie=cookie,
        )
        overlay_payload = json.loads(overlay_body.decode("utf-8"))

        self.assertEqual(overlay_status, 200)
        self.assertEqual(overlay_payload["items"][0]["owner_app_id"], "chat")
        self.assertEqual(overlay_payload["items"][0]["widget_id"], "chat-floating")
        self.assertEqual(overlay_payload["items"][0]["frontend_mount"], "/api/apps/widgets/chat/chat-floating/frontend/")
        self.assertNotIn("source_root", overlay_payload["items"][0])
        self.assertNotIn("source_path", overlay_payload["items"][0])

    def test_chat_projects_and_core_threads_support_sidebar_settings(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)

        status_project, project_body, _ = self.invoke(
            app,
            path="/api/apps/chat/backend",
            method="POST",
            body={"action": "projects.create", "name": "Client work"},
            cookie=cookie,
        )
        project_payload = json.loads(project_body.decode("utf-8"))
        project_id = project_payload["project"]["project_id"]
        status_session, session_body, _ = self.invoke(
            app,
            path="/api/runtime/sessions",
            method="POST",
            body={"agent_id": "chat", "project_id": project_id},
            cookie=cookie,
        )
        session_payload = json.loads(session_body.decode("utf-8"))
        status_thread, thread_body, _ = self.invoke(
            app,
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": session_payload["session_id"], "project_id": project_id},
            cookie=cookie,
        )
        thread_payload = json.loads(thread_body.decode("utf-8"))
        thread_id = thread_payload["thread"]["thread_id"]
        status_rename, rename_body, _ = self.invoke(
            app,
            path=f"/api/runtime/threads/{thread_id}",
            method="PATCH",
            body={"title": "Audit plan", "project_id": ""},
            cookie=cookie,
        )
        rename_payload = json.loads(rename_body.decode("utf-8"))
        status_delete, delete_body, _ = self.invoke(
            app,
            path=f"/api/runtime/threads/{thread_id}",
            method="DELETE",
            cookie=cookie,
        )
        delete_payload = json.loads(delete_body.decode("utf-8"))

        self.assertEqual(status_project, 201)
        self.assertEqual(status_session, 201)
        self.assertEqual(status_thread, 201)
        self.assertEqual(status_rename, 200)
        self.assertEqual(status_delete, 200)
        self.assertEqual(rename_payload["thread"]["title"], "Audit plan")
        self.assertIsNone(rename_payload["thread"]["project_id"])
        self.assertEqual(delete_payload["threads"], [])

    def test_core_runtime_thread_delete_performs_server_side_runtime_cleanup(self) -> None:
        repo_root = self.make_repo_root()
        state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        cookie = self.login(app)
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
            path="/api/runtime/threads",
            method="POST",
            body={"runtime_session_id": session.session_id},
            cookie=cookie,
        )
        thread_payload = json.loads(thread_body.decode("utf-8"))
        thread_id = thread_payload["thread"]["thread_id"]

        status_delete, delete_body, _ = self.invoke(
            app,
            path=f"/api/runtime/threads/{thread_id}",
            method="DELETE",
            cookie=cookie,
        )
        delete_payload = json.loads(delete_body.decode("utf-8"))

        self.assertEqual(status_thread, 201)
        self.assertEqual(status_delete, 200)
        self.assertEqual(delete_payload["deleted_runtime_session_id"], session.session_id)
        self.assertEqual(delete_payload["runtime_cleanup"]["session_id"], session.session_id)
        cleanup_payload = delete_payload["runtime_cleanup"]
        self.assertEqual(cleanup_payload["session_id"], session.session_id)
        self.assertEqual(cleanup_payload["cancelled_turns"], 1)
        self.assertEqual(cleanup_payload["deleted"]["sessions"], 1)
        with self.assertRaises(RuntimeSessionNotFoundError):
            state.runtime_store.get_session(session.session_id)
        with self.assertRaises(RuntimeTurnNotFoundError):
            state.runtime_store.get_turn(turn.turn_id)


if __name__ == "__main__":
    unittest.main()
