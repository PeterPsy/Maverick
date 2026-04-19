"""Tests for app-hosting control-plane behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import (
    build_app_capabilities,
    build_app_compatibility,
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_failure_semantics,
    build_app_health_contract,
    build_app_hook_timeouts,
    build_app_lifecycle,
    build_app_rollback_support,
    build_app_storage,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.errors import (
    AppCompatibilityError,
    AppLifecycleError,
    WorkspaceAppBindingNotFoundError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.service import (
    fork_store_app_to_workspace,
    install_store_app,
    install_workspace_local_app,
    purge_workspace_app_data,
    register_app_source_from_contract,
    register_workspace_local_app_project_from_contract,
    reinstall_workspace_app,
    transition_workspace_app_status,
    uninstall_workspace_app,
    upgrade_workspace_app,
)
from core.apps.store import AppCollections, MongoAppStore


class FakeCollection:
    """Small in-memory collection for app store tests."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    def find(self, query: dict) -> list[dict]:
        return [dict(document) for document in self.documents if all(document.get(key) == value for key, value in query.items())]

    def update_one(self, query: dict, update: dict, *, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents[index] = {**document, **payload}
                return
        if upsert:
            self.documents.append({**query, **payload})

    def delete_one(self, query: dict) -> None:
        for index, document in enumerate(self.documents):
            if all(document.get(key) == value for key, value in query.items()):
                self.documents.pop(index)
                return


class Phase4AppHostingTestCase(unittest.TestCase):
    """Verify app-hosting control-plane behavior for installed and local apps."""

    def make_store(self) -> MongoAppStore:
        return MongoAppStore(
            AppCollections(
                app_sources=FakeCollection(),
                workspace_local_app_projects=FakeCollection(),
                workspace_app_bindings=FakeCollection(),
            )
        )

    def make_repo_root(self, temp_dir: str) -> Path:
        root = Path(temp_dir)
        (root / "AGENTS.md").write_text("test", encoding="utf-8")
        (root / "IMPLEMENTATION_TASKLIST.md").write_text("test", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname = "maverick-v3"\nversion = "0.1.0"\n',
            encoding="utf-8",
        )
        for name in ("core", "apps", "workspaces", "docs", "local-skills", "scripts", "tests"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def write_contract(
        self,
        app_root: Path,
        *,
        app_id: str,
        name: str | None = None,
        version: str = "1.0.0",
        publisher: str = "maverick",
        contract=None,
    ) -> None:
        parsed = build_parsed_app_contract(
            app_id=app_id,
            name=name or app_id.title(),
            version=version,
            description=f"{app_id} app",
            publisher=publisher,
            contract=contract or build_app_contract(),
        )
        write_app_contract_file(app_root, parsed)

    def test_store_app_install_creates_workspace_binding_without_source_copy(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "checklists"
            self.write_contract(app_root, app_id="checklists", name="Checklists")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )

            binding = install_store_app(
                store,
                source_id=source.source_id,
                workspace_id="default",
                start_path=repo_root,
                now=now,
            )

            self.assertEqual(binding.status, "enabled")
            self.assertEqual(binding.source_kind, "platform")
            self.assertTrue((repo_root / "workspaces" / "default" / "data" / "checklists").is_dir())
            self.assertFalse((repo_root / "workspaces" / "default" / "apps" / "checklists").exists())

    def test_source_available_store_app_can_be_forked_into_workspace(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "customizable"
            (app_root / "frontend").mkdir(parents=True, exist_ok=True)
            (app_root / "frontend" / "index.html").write_text("<main>Customizable</main>", encoding="utf-8")
            self.write_contract(
                app_root,
                app_id="customizable",
                name="Customizable",
                contract=build_app_contract(
                    distribution=build_app_distribution(
                        mode="source_available",
                        source_access="forkable",
                        modifiable_by_agents=True,
                    ),
                    entrypoints=build_app_entrypoints(frontend="frontend"),
                ),
            )
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )

            project = fork_store_app_to_workspace(
                store,
                source_id=source.source_id,
                workspace_id="acme",
                start_path=repo_root,
                now=now,
            )

            fork_root = repo_root / "workspaces" / "acme" / "apps" / "customizable"
            self.assertEqual(project.project_root, str(fork_root))
            self.assertEqual(project.forked_from_source_id, source.source_id)
            self.assertEqual(project.contract.distribution.mode, "workspace_local")
            self.assertTrue((fork_root / "frontend" / "index.html").is_file())

            binding = install_workspace_local_app(
                store,
                workspace_id="acme",
                app_id="customizable",
                start_path=repo_root,
                now=now,
            )
            self.assertEqual(binding.source_kind, "workspace_local_project")

    def test_sealed_store_app_cannot_be_forked_by_default(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "sealed-app"
            self.write_contract(app_root, app_id="sealed-app", name="Sealed App")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )

            with self.assertRaises(AppLifecycleError):
                fork_store_app_to_workspace(
                    store,
                    source_id=source.source_id,
                    workspace_id="acme",
                    start_path=repo_root,
                    now=now,
                )

            self.assertFalse((repo_root / "workspaces" / "acme" / "apps" / "sealed-app").exists())

    def test_workspace_local_app_can_only_install_into_its_own_workspace(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            project_root = repo_root / "workspaces" / "acme" / "apps" / "notes"
            self.write_contract(
                project_root,
                app_id="notes",
                name="Notes",
                publisher="workspace-user",
                contract=build_app_contract(
                    distribution=build_app_distribution(
                        mode="workspace_local",
                        source_access="editable",
                        modifiable_by_agents=True,
                    ),
                ),
            )
            record = register_workspace_local_app_project_from_contract(
                store,
                workspace_id="acme",
                project_root=str(project_root),
                now=now,
            )

            binding = install_workspace_local_app(store, workspace_id="acme", app_id="notes", start_path=repo_root, now=now)
            self.assertEqual(binding.source_kind, "workspace_local_project")
            self.assertEqual(record.workspace_id, "acme")

            with self.assertRaises(WorkspaceLocalAppProjectNotFoundError):
                install_workspace_local_app(store, workspace_id="other", app_id="notes", start_path=repo_root, now=now)

    def test_uninstall_preserves_data_and_removes_binding(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "crm"
            self.write_contract(app_root, app_id="crm", name="CRM")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            data_root = repo_root / "workspaces" / "default" / "data" / "crm"
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
            (data_root / "records.json").write_text("{}", encoding="utf-8")

            uninstall_workspace_app(store, workspace_id="default", app_id="crm")

            self.assertTrue(data_root.is_dir())
            with self.assertRaises(WorkspaceAppBindingNotFoundError):
                store.get_workspace_app_binding(workspace_id="default", app_id="crm")

    def test_purge_data_is_separate_from_uninstall(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            data_root = repo_root / "workspaces" / "default" / "data" / "reports"
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "snapshot.json").write_text("{}", encoding="utf-8")

            removed_root = purge_workspace_app_data(workspace_id="default", app_id="reports", start_path=repo_root)

            self.assertEqual(removed_root, data_root)
            self.assertFalse(data_root.exists())

    def test_reinstall_reattaches_to_existing_data(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "memory"
            self.write_contract(app_root, app_id="memory", name="Memory")
            register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            data_root = repo_root / "workspaces" / "default" / "data" / "memory"
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "existing.json").write_text("{}", encoding="utf-8")

            result = reinstall_workspace_app(store, workspace_id="default", app_id="memory", start_path=repo_root, now=now)

            self.assertTrue(result.reused_existing_data_root)
            self.assertEqual(result.binding.status, "enabled")
            self.assertTrue((data_root / "existing.json").exists())

    def test_reinstall_runs_requested_migrate_validate_and_repair_hooks(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "repairable"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "install.py").write_text("print('install')\n", encoding="utf-8")
            (lifecycle_root / "migrate.py").write_text(
                "from pathlib import Path\nPath('migrate-ran.txt').write_text('ok', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (lifecycle_root / "validate.py").write_text(
                "from pathlib import Path\nPath('validate-ran.txt').write_text('ok', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (lifecycle_root / "repair.py").write_text(
                "from pathlib import Path\nPath('repair-ran.txt').write_text('ok', encoding='utf-8')\n",
                encoding="utf-8",
            )
            contract = build_app_contract(
                lifecycle=build_app_lifecycle(
                    migrate=True,
                    validate_after_import=True,
                    repair_after_import=True,
                ),
                entrypoints=build_app_entrypoints(
                    hooks={
                        "install": "backend/lifecycle/install.py",
                        "migrate": "backend/lifecycle/migrate.py",
                        "validate_after_import": "backend/lifecycle/validate.py",
                        "repair_after_import": "backend/lifecycle/repair.py",
                    }
                ),
            )
            self.write_contract(app_root, app_id="repairable", name="Repairable", contract=contract)
            register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            data_root = repo_root / "workspaces" / "default" / "data" / "repairable"
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "existing.json").write_text("{}", encoding="utf-8")

            result = reinstall_workspace_app(
                store,
                workspace_id="default",
                app_id="repairable",
                start_path=repo_root,
                now=now,
                validate_existing_data=True,
                repair_existing_data=True,
                migration_required=True,
            )

            self.assertTrue(result.reused_existing_data_root)
            self.assertTrue((app_root / "migrate-ran.txt").exists())
            self.assertTrue((app_root / "validate-ran.txt").exists())
            self.assertTrue((app_root / "repair-ran.txt").exists())

    def test_reinstall_skips_validation_when_contract_does_not_support_it(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "simple"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "install.py").write_text("print('install')\n", encoding="utf-8")
            contract = build_app_contract(
                entrypoints=build_app_entrypoints(hooks={"install": "backend/lifecycle/install.py"}),
            )
            self.write_contract(app_root, app_id="simple", name="Simple", contract=contract)
            register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            data_root = repo_root / "workspaces" / "default" / "data" / "simple"
            data_root.mkdir(parents=True, exist_ok=True)
            result = reinstall_workspace_app(
                store,
                workspace_id="default",
                app_id="simple",
                start_path=repo_root,
                now=now,
                validate_existing_data=True,
            )

            self.assertEqual(result.binding.status, "enabled")

    def test_compatibility_checks_reject_invalid_contract_and_workspace_mode(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            bad_root = repo_root / "apps" / "_bundles" / "unsafe" / "1.0.0"
            good_root = repo_root / "apps" / "_bundles" / "operator-tools" / "1.0.0"
            self.write_contract(
                bad_root,
                app_id="unsafe",
                name="Unsafe",
                publisher="vendor",
                contract=build_app_contract(
                    compatibility=build_app_compatibility(contract_version="2.0"),
                ),
            )
            self.write_contract(
                good_root,
                app_id="operator-tools",
                name="Operator Tools",
                publisher="vendor",
                contract=build_app_contract(
                    compatibility=build_app_compatibility(supported_workspace_modes=["full-access"]),
                ),
            )
            bad_contract = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(bad_root),
                now=now,
            )
            full_access_only = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(good_root),
                now=now,
            )
            with self.assertRaises(AppCompatibilityError):
                install_store_app(store, source_id=bad_contract.source_id, workspace_id="default", start_path=repo_root, now=now)
            with self.assertRaises(AppCompatibilityError):
                install_store_app(store, source_id=full_access_only.source_id, workspace_id="acme", start_path=repo_root, now=now)

    def test_cannot_enable_before_install_and_can_transition_installed_to_enabled(self) -> None:
        store = self.make_store()
        with self.assertRaises(WorkspaceAppBindingNotFoundError):
            transition_workspace_app_status(store, workspace_id="default", app_id="mail", target_status="enabled")

        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "mail"
            self.write_contract(app_root, app_id="mail", name="Mail")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            install_store_app(
                store,
                source_id=source.source_id,
                workspace_id="default",
                enabled=False,
                start_path=repo_root,
                now=now,
            )
            enabled = transition_workspace_app_status(
                store,
                workspace_id="default",
                app_id="mail",
                target_status="enabled",
                now=now,
            )

            self.assertEqual(enabled.status, "enabled")

    def test_invalid_transition_raises_lifecycle_error(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "widgets"
            self.write_contract(app_root, app_id="widgets", name="Widgets")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
            with self.assertRaises(AppLifecycleError):
                transition_workspace_app_status(
                    store,
                    workspace_id="default",
                    app_id="widgets",
                    target_status="rolled_back",
                    now=now,
                )

    def test_trusted_bundle_must_live_under_installation_managed_root(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            rogue_bundle = repo_root / "workspaces" / "default" / "apps" / "rogue"
            self.write_contract(rogue_bundle, app_id="rogue", name="Rogue", publisher="vendor")
            source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(rogue_bundle),
                now=now,
            )

            with self.assertRaises(AppLifecycleError):
                install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

    def test_install_hook_runs_and_health_failure_marks_binding_failed(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "hooks-app"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "install.py").write_text(
                "from pathlib import Path\nPath('install-ran.txt').write_text('ok', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (lifecycle_root / "health.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
            contract = build_app_contract(
                entrypoints=build_app_entrypoints(
                    hooks={
                        "install": "backend/lifecycle/install.py",
                        "health_check": "backend/lifecycle/health.py",
                    }
                ),
                lifecycle=build_app_lifecycle(health_check=True),
                health_contract=build_app_health_contract(mode="hook", degraded_on_failure=True),
                failure_semantics=build_app_failure_semantics(install_failure="block_activation"),
            )
            self.write_contract(app_root, app_id="hooks-app", name="Hooks App", contract=contract)
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )

            binding = install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

            self.assertTrue((app_root / "install-ran.txt").exists())
            self.assertEqual(binding.status, "failed")

    def test_install_hook_timeout_is_enforced(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "timeout-app"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "install.py").write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
            contract = build_app_contract(
                entrypoints=build_app_entrypoints(hooks={"install": "backend/lifecycle/install.py"}),
                hook_timeouts=build_app_hook_timeouts(install_seconds=1),
            )
            self.write_contract(app_root, app_id="timeout-app", name="Timeout App", contract=contract)
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )

            with self.assertRaises(AppLifecycleError):
                install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

    def test_upgrade_workspace_app_runs_upgrade_and_migrate_and_updates_data_schema_version(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            initial_root = repo_root / "apps" / "_bundles" / "reports" / "1.0.0"
            upgraded_root = repo_root / "apps" / "_bundles" / "reports" / "2.0.0"
            self.write_contract(
                initial_root,
                app_id="reports",
                contract=build_app_contract(storage=build_app_storage(data_schema_version="1")),
            )
            lifecycle_root = upgraded_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "upgrade.py").write_text(
                "from pathlib import Path\nPath('upgrade-ran.txt').write_text('ok', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (lifecycle_root / "migrate.py").write_text(
                "from pathlib import Path\nPath('migrate-ran.txt').write_text('ok', encoding='utf-8')\n",
                encoding="utf-8",
            )
            self.write_contract(
                upgraded_root,
                app_id="reports",
                version="2.0.0",
                contract=build_app_contract(
                    storage=build_app_storage(data_schema_version="2"),
                    lifecycle=build_app_lifecycle(upgrade=True, migrate=True),
                    entrypoints=build_app_entrypoints(
                        hooks={
                            "upgrade": "backend/lifecycle/upgrade.py",
                            "migrate": "backend/lifecycle/migrate.py",
                        }
                    ),
                ),
            )
            initial_source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(initial_root),
                now=now,
            )
            target_source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(upgraded_root),
                now=now,
            )
            install_store_app(store, source_id=initial_source.source_id, workspace_id="default", start_path=repo_root, now=now)

            result = upgrade_workspace_app(
                store,
                workspace_id="default",
                app_id="reports",
                target_source_id=target_source.source_id,
                start_path=repo_root,
                now=now,
            )

            self.assertEqual(result.binding.active_version, "2.0.0")
            self.assertTrue((upgraded_root / "upgrade-ran.txt").exists())
            self.assertTrue((upgraded_root / "migrate-ran.txt").exists())
            metadata = (repo_root / "workspaces" / "default" / "data" / "reports" / ".maverick-app.json").read_text(
                encoding="utf-8"
            )
            self.assertIn('"data_schema_version": "2"', metadata)

    def test_upgrade_rolls_back_bundle_when_supported(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            initial_root = repo_root / "apps" / "_bundles" / "planner" / "1.0.0"
            broken_root = repo_root / "apps" / "_bundles" / "planner" / "2.0.0"
            self.write_contract(initial_root, app_id="planner")
            lifecycle_root = broken_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "upgrade.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
            self.write_contract(
                broken_root,
                app_id="planner",
                version="2.0.0",
                contract=build_app_contract(
                    lifecycle=build_app_lifecycle(upgrade=True),
                    entrypoints=build_app_entrypoints(hooks={"upgrade": "backend/lifecycle/upgrade.py"}),
                    rollback_support=build_app_rollback_support(bundle=True),
                ),
            )
            initial_source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(initial_root),
                now=now,
            )
            broken_source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(broken_root),
                now=now,
            )
            install_store_app(store, source_id=initial_source.source_id, workspace_id="default", start_path=repo_root, now=now)

            result = upgrade_workspace_app(
                store,
                workspace_id="default",
                app_id="planner",
                target_source_id=broken_source.source_id,
                start_path=repo_root,
                now=now,
            )

            self.assertTrue(result.rolled_back)
            self.assertEqual(result.binding.status, "rolled_back")
            self.assertEqual(result.binding.active_version, "1.0.0")


if __name__ == "__main__":
    unittest.main()
