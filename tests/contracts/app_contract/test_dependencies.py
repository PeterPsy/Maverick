from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import (
    build_app_contract,
    build_app_lifecycle,
    build_parsed_app_contract,
    build_provided_interface_declaration,
    build_required_interface_declaration,
    write_app_contract_file,
)
from core.apps.dependencies import resolve_app_dependencies, save_app_dependency_selection
from core.apps.errors import AppHostingError
from core.apps.hook_payloads import build_app_health_hook_payload
from core.apps.service import install_store_app, register_app_source_from_contract, transition_workspace_app_status
from core.cli.models import CliInvocationContext
from core.cli.service import list_core_cli_commands, run_core_cli_command
from tests.support.app_hosting import AppHostingTestBase


class AppDependenciesTest(AppHostingTestBase):
    def _write_app(self, root: Path, *, app_id: str, contract) -> Path:
        app_root = root / "apps" / app_id
        parsed = build_parsed_app_contract(
            app_id=app_id,
            name=app_id.title(),
            version="1.0.0",
            description=f"{app_id} app.",
            publisher="vendor",
            contract=contract,
        )
        write_app_contract_file(app_root, parsed)
        return app_root

    def _register_and_install(self, store, app_root: Path, *, workspace_id: str, start_path: Path) -> None:
        source = register_app_source_from_contract(
            store,
            source_kind="platform",
            source_path=str(app_root),
        )
        install_store_app(store, source_id=source.source_id, workspace_id=workspace_id, start_path=start_path)

    def test_resolves_selected_provider_by_interface_not_app_id(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            store = self.make_store()
            provider_root = self._write_app(
                repo_root,
                app_id="provider-one",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="agent.catalog",
                            description="Agent catalog.",
                            surfaces=[],
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            consumer_root = self._write_app(
                repo_root,
                app_id="consumer-one",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="agent-provider",
                            interface="agent.catalog",
                            description="Agent provider.",
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            self._register_and_install(store, provider_root, workspace_id="default", start_path=repo_root)
            self._register_and_install(store, consumer_root, workspace_id="default", start_path=repo_root)

            unresolved = resolve_app_dependencies(
                store,
                workspace_id="default",
                consumer_app_id="consumer-one",
                start_path=repo_root,
            )
            self.assertEqual(unresolved["status"], "blocked")
            self.assertEqual(unresolved["dependencies"][0]["status"], "unresolved")
            self.assertEqual(unresolved["dependencies"][0]["candidates"][0]["app_id"], "provider-one")

            resolved = save_app_dependency_selection(
                store,
                workspace_id="default",
                consumer_app_id="consumer-one",
                alias="agent-provider",
                provider_app_ids=["provider-one"],
                start_path=repo_root,
            )
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["dependencies"][0]["selected_provider_app_ids"], ["provider-one"])

            commands = list_core_cli_commands(app_store=store, workspace_id="default", start_path=repo_root)
            self.assertIn("app.consumer-one.dependencies", [command.command_id for command in commands])
            cli_payload = run_core_cli_command(
                command_id="app.consumer-one.dependencies",
                context=CliInvocationContext(
                    caller_kind="sandbox_agent",
                    workspace_id="default",
                    agent_id="agent-1",
                    effective_mode="sandbox",
                ),
                app_store=store,
                workspace_id="default",
                start_path=repo_root,
            )
            self.assertEqual(cli_payload["status"], "resolved")

    def test_health_hook_payload_includes_dependency_resolution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            store = self.make_store()
            provider_root = self._write_app(
                repo_root,
                app_id="provider-one",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="agent.catalog",
                            description="Agent catalog.",
                            surfaces=[],
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            consumer_root = self._write_app(
                repo_root,
                app_id="consumer-one",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="agent-provider",
                            interface="agent.catalog",
                            description="Agent provider.",
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            self._register_and_install(store, provider_root, workspace_id="default", start_path=repo_root)
            self._register_and_install(store, consumer_root, workspace_id="default", start_path=repo_root)
            save_app_dependency_selection(
                store,
                workspace_id="default",
                consumer_app_id="consumer-one",
                alias="agent-provider",
                provider_app_ids=["provider-one"],
                start_path=repo_root,
            )

            payload = build_app_health_hook_payload(
                store,
                workspace_id="default",
                app_id="consumer-one",
                start_path=repo_root,
            )

            self.assertEqual(payload["hook_name"], "health_check")
            self.assertEqual(payload["app_dependencies"]["status"], "resolved")
            self.assertEqual(
                payload["app_dependencies"]["dependencies"][0]["selected_provider_app_ids"],
                ["provider-one"],
            )

    def test_crm_dependencies_resolve_provider_candidates_for_settings_app_links(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            store = self.make_store()
            mail_root = self._write_app(
                repo_root,
                app_id="mail",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="mail.workspace",
                            description="Mail workspace.",
                            surfaces=["backend", "mcp", "cli"],
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            calendar_root = self._write_app(
                repo_root,
                app_id="calendar",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="calendar.events",
                            description="Calendar events.",
                            surfaces=["backend", "mcp", "cli"],
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            storage_root = self._write_app(
                repo_root,
                app_id="storage",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="file.catalog",
                            description="File catalog.",
                            surfaces=["backend", "mcp", "cli"],
                        ),
                        build_provided_interface_declaration(
                            interface="file.preview",
                            description="File preview.",
                            surfaces=["backend", "mcp"],
                        ),
                        build_provided_interface_declaration(
                            interface="file.content.write",
                            description="File writes.",
                            surfaces=["backend", "mcp", "cli"],
                        ),
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            crm_root = self._write_app(
                repo_root,
                app_id="crm",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(alias="mail", interface="mail.workspace", required=False, description="CRM mail provider."),
                        build_required_interface_declaration(alias="calendar", interface="calendar.events", required=False, description="CRM calendar provider."),
                        build_required_interface_declaration(alias="files", interface="file.catalog", required=False, description="CRM file catalog provider."),
                        build_required_interface_declaration(alias="file-preview", interface="file.preview", required=False, description="CRM file preview provider."),
                        build_required_interface_declaration(alias="file-write", interface="file.content.write", required=False, description="CRM file write provider."),
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            for app_root in (mail_root, calendar_root, storage_root, crm_root):
                self._register_and_install(store, app_root, workspace_id="default", start_path=repo_root)

            payload = resolve_app_dependencies(
                store,
                workspace_id="default",
                consumer_app_id="crm",
                start_path=repo_root,
            )

            self.assertEqual(payload["status"], "resolved")
            candidates_by_alias = {
                item["alias"]: [candidate["app_id"] for candidate in item["candidates"]]
                for item in payload["dependencies"]
            }
            self.assertEqual(candidates_by_alias["mail"], ["mail"])
            self.assertEqual(candidates_by_alias["calendar"], ["calendar"])
            self.assertEqual(candidates_by_alias["files"], ["storage"])
            self.assertEqual(candidates_by_alias["file-preview"], ["storage"])
            self.assertEqual(candidates_by_alias["file-write"], ["storage"])

    def test_reports_stale_selection_when_provider_is_disabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            store = self.make_store()
            provider_root = self._write_app(
                repo_root,
                app_id="provider-one",
                contract=build_app_contract(
                    provides=[
                        build_provided_interface_declaration(
                            interface="file.catalog",
                            description="File catalog.",
                            surfaces=[],
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            consumer_root = self._write_app(
                repo_root,
                app_id="consumer-one",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="file-provider",
                            interface="file.catalog",
                            description="File provider.",
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            self._register_and_install(store, provider_root, workspace_id="default", start_path=repo_root)
            self._register_and_install(store, consumer_root, workspace_id="default", start_path=repo_root)
            save_app_dependency_selection(
                store,
                workspace_id="default",
                consumer_app_id="consumer-one",
                alias="file-provider",
                provider_app_ids=["provider-one"],
                start_path=repo_root,
            )
            transition_workspace_app_status(
                store,
                workspace_id="default",
                app_id="provider-one",
                target_status="disabled",
            )

            payload = resolve_app_dependencies(
                store,
                workspace_id="default",
                consumer_app_id="consumer-one",
                start_path=repo_root,
            )
            self.assertEqual(payload["dependencies"][0]["status"], "stale")
            self.assertEqual(payload["dependencies"][0]["stale_provider_app_ids"], ["provider-one"])

    def test_reports_missing_provider_and_rejects_invalid_selection(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            store = self.make_store()
            consumer_root = self._write_app(
                repo_root,
                app_id="consumer-one",
                contract=build_app_contract(
                    requires=[
                        build_required_interface_declaration(
                            alias="file-provider",
                            interface="file.catalog",
                            description="File provider.",
                        )
                    ],
                    lifecycle=build_app_lifecycle(install=False),
                ),
            )
            self._register_and_install(store, consumer_root, workspace_id="default", start_path=repo_root)

            payload = resolve_app_dependencies(
                store,
                workspace_id="default",
                consumer_app_id="consumer-one",
                start_path=repo_root,
            )
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["dependencies"][0]["status"], "missing_provider")
            with self.assertRaises(AppHostingError):
                save_app_dependency_selection(
                    store,
                    workspace_id="default",
                    consumer_app_id="consumer-one",
                    alias="file-provider",
                    provider_app_ids=["not-a-provider"],
                    start_path=repo_root,
                )


if __name__ == "__main__":
    unittest.main()
