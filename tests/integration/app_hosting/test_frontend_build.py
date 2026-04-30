from __future__ import annotations

from datetime import UTC, datetime
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core.api.app_mounts import handle_app_frontend_build
from core.api.app_events import AppEventBus
from core.apps.contracts import build_app_contract, build_app_entrypoints
from core.apps.service import install_store_app, register_app_source_from_contract
from core.cli.models import CliInvocationContext
from core.cli.errors import CliInvocationNotAllowedError
from core.cli.service import list_core_cli_commands, run_core_cli_command
from core.identity.models import UserRecord
from tests.support.app_hosting import AppHostingTestBase


class AppFrontendBuildTests(AppHostingTestBase):
    def operator_context(self) -> CliInvocationContext:
        return CliInvocationContext(
            caller_kind="operator",
            workspace_id="default",
            agent_id=None,
            effective_mode="full-access",
        )

    def full_access_agent_context(self) -> CliInvocationContext:
        return CliInvocationContext(
            caller_kind="full_access_agent",
            workspace_id="default",
            agent_id="sess-1",
            effective_mode="full-access",
        )

    def sandbox_agent_context(self) -> CliInvocationContext:
        return CliInvocationContext(
            caller_kind="sandbox_agent",
            workspace_id="default",
            agent_id="sess-1",
            effective_mode="sandbox",
        )

    def write_buildable_app(self, repo_root, app_id: str = "buildable"):
        app_root = repo_root / "apps" / app_id
        (app_root / "frontend" / "dist").mkdir(parents=True)
        (app_root / "frontend" / "package.json").write_text('{"scripts":{"build":"vite build"}}', encoding="utf-8")
        (app_root / "frontend" / "dist" / "index.html").write_text("<main>Before</main>", encoding="utf-8")
        self.write_contract(
            app_root,
            app_id=app_id,
            contract=build_app_contract(
                entrypoints=build_app_entrypoints(frontend="frontend/dist"),
            ),
        )
        return app_root

    def test_frontend_build_command_runs_declared_app_build_and_publishes_event(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = self.write_buildable_app(repo_root)
            store = self.make_store()
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            event_bus = AppEventBus()
            app_events = event_bus.subscribe()
            self.addCleanup(lambda: event_bus.unsubscribe(app_events))

            commands = list_core_cli_commands(
                app_store=store,
                app_event_bus=event_bus,
                workspace_id="default",
                start_path=repo_root,
            )
            self.assertIn("app.buildable.frontend.build", {command.command_id for command in commands})

            with patch("core.apps.frontend_build.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(["npm", "run", "build"], 0, stdout="ok", stderr="")
                result = run_core_cli_command(
                    command_id="app.buildable.frontend.build",
                    context=self.operator_context(),
                    app_store=store,
                    app_event_bus=event_bus,
                    workspace_id="default",
                    start_path=repo_root,
                    arguments={},
                )

            self.assertEqual(result["status"], "built")
            self.assertEqual(result["app_id"], "buildable")
            self.assertEqual(result["workspace_id"], "default")
            self.assertEqual(result["frontend_mount"], "frontend/dist")
            build_calls = [call for call in run.call_args_list if call.args and call.args[0] == ["npm", "run", "build"]]
            self.assertEqual(len(build_calls), 1)
            self.assertEqual(build_calls[0].kwargs["cwd"], app_root / "frontend")

            event = app_events.get_nowait()
            self.assertEqual(
                event,
                {
                    "type": "maverick.app.frontend-changed",
                    "workspace_id": "default",
                    "owner_app_id": "buildable",
                    "resource": "frontend",
                },
            )

    def test_frontend_build_command_allows_full_access_runtime_agent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = self.write_buildable_app(repo_root)
            store = self.make_store()
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

            with patch("core.apps.frontend_build.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(["npm", "run", "build"], 0, stdout="ok", stderr="")
                result = run_core_cli_command(
                    command_id="app.buildable.frontend.build",
                    context=self.full_access_agent_context(),
                    app_store=store,
                    workspace_id="default",
                    start_path=repo_root,
                    arguments={},
                )

            self.assertEqual(result["status"], "built")
            run.assert_called_once()

    def test_frontend_build_command_denies_sandbox_runtime_agent(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = self.write_buildable_app(repo_root)
            store = self.make_store()
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

            with patch("core.apps.frontend_build.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(["npm", "run", "build"], 0, stdout="ok", stderr="")
                with self.assertRaises(CliInvocationNotAllowedError):
                    run_core_cli_command(
                        command_id="app.buildable.frontend.build",
                        context=self.sandbox_agent_context(),
                        app_store=store,
                        workspace_id="default",
                        start_path=repo_root,
                        arguments={},
                    )

            run.assert_not_called()

    def test_frontend_build_command_is_not_exposed_without_build_script(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = self.write_buildable_app(repo_root)
            (app_root / "frontend" / "package.json").unlink()
            store = self.make_store()
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)

            commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)

            self.assertNotIn("app.buildable.frontend.build", {command.command_id for command in commands})

    def test_hosted_frontend_build_route_publishes_on_server_event_bus(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = self.write_buildable_app(repo_root)
            store = self.make_store()
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(app_root))
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            event_bus = AppEventBus()
            app_events = event_bus.subscribe()
            self.addCleanup(lambda: event_bus.unsubscribe(app_events))
            state = type("State", (), {"app_store": store, "app_event_bus": event_bus})()
            user = UserRecord(
                user_id="admin",
                username="admin",
                email=None,
                display_name=None,
                account_type="standard",
                platform_role="admin",
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            status_holder: dict[str, str] = {}

            def start_response(status: str, _headers: list[tuple[str, str]]) -> None:
                status_holder["status"] = status

            with patch("core.apps.frontend_build.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(["npm", "run", "build"], 0, stdout="ok", stderr="")
                handle_app_frontend_build(
                    state,
                    workspace_id="default",
                    app_id="buildable",
                    user=user,
                    start_path=repo_root,
                    start_response=start_response,
                )

            self.assertEqual(status_holder["status"], "200 OK")
            self.assertEqual(app_events.get_nowait()["type"], "maverick.app.frontend-changed")


if __name__ == "__main__":
    unittest.main()
