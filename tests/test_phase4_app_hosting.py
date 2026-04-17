"""Tests for Phase 4 app-hosting control-plane behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.errors import (
    AppCompatibilityError,
    AppLifecycleError,
    WorkspaceAppBindingNotFoundError,
    WorkspaceLocalAppProjectNotFoundError,
)
from core.apps.service import (
    build_app_compatibility,
    build_app_contract,
    build_app_entrypoints,
    build_app_failure_semantics,
    build_app_health_contract,
    build_app_hook_timeouts,
    build_app_rollback_support,
    build_app_source_record,
    build_workspace_local_app_project_record,
    install_external_app,
    install_workspace_local_app,
    purge_workspace_app_data,
    register_app_source,
    register_workspace_local_app_project,
    reinstall_workspace_app,
    transition_workspace_app_status,
    uninstall_workspace_app,
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
    """Verify app-hosting control-plane behavior for Phase 4."""

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

    def test_external_app_install_creates_workspace_binding_and_data_root(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        source = build_app_source_record(
            app_id="checklists",
            name="Checklists",
            version="1.0.0",
            description="Checklist app",
            publisher="maverick",
            source_kind="platform",
            source_path=str(Path("/tmp") / "unused"),
            contract=build_app_contract(),
            now=now,
        )

        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "checklists"
            app_root.mkdir(parents=True, exist_ok=True)
            source = build_app_source_record(
                app_id="checklists",
                name="Checklists",
                version="1.0.0",
                description="Checklist app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=build_app_contract(),
                now=now,
            )
            register_app_source(store, source)

            binding = install_external_app(
                store,
                source_id=source.source_id,
                workspace_id="default",
                start_path=repo_root,
                now=now,
            )

            self.assertEqual(binding.status, "enabled")
            self.assertTrue((repo_root / "workspaces" / "default" / "data" / "checklists").is_dir())

    def test_workspace_local_app_can_only_install_into_its_own_workspace(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            project_root = repo_root / "workspaces" / "acme" / "apps" / "notes"
            project_root.mkdir(parents=True, exist_ok=True)
            record = build_workspace_local_app_project_record(
                workspace_id="acme",
                app_id="notes",
                name="Notes",
                version="1.0.0",
                description="Notes app",
                publisher="workspace-user",
                project_root=str(project_root),
                contract=build_app_contract(),
                now=now,
            )
            register_workspace_local_app_project(store, record)

            binding = install_workspace_local_app(store, workspace_id="acme", app_id="notes", start_path=repo_root, now=now)
            self.assertEqual(binding.source_kind, "workspace_local_project")

            with self.assertRaises(WorkspaceLocalAppProjectNotFoundError):
                install_workspace_local_app(store, workspace_id="other", app_id="notes", start_path=repo_root, now=now)

    def test_uninstall_preserves_data_and_removes_binding(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        source = build_app_source_record(
            app_id="crm",
            name="CRM",
            version="1.0.0",
            description="CRM app",
            publisher="maverick",
            source_kind="platform",
            source_path=str(Path("/tmp") / "unused"),
            contract=build_app_contract(),
            now=now,
        )

        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "crm"
            app_root.mkdir(parents=True, exist_ok=True)
            source = build_app_source_record(
                app_id="crm",
                name="CRM",
                version="1.0.0",
                description="CRM app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=build_app_contract(),
                now=now,
            )
            register_app_source(store, source)
            data_root = repo_root / "workspaces" / "default" / "data" / "crm"
            install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
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
        source = build_app_source_record(
            app_id="memory",
            name="Memory",
            version="1.0.0",
            description="Memory app",
            publisher="maverick",
            source_kind="platform",
            source_path=str(Path("/tmp") / "unused"),
            contract=build_app_contract(),
            now=now,
        )

        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "memory"
            app_root.mkdir(parents=True, exist_ok=True)
            source = build_app_source_record(
                app_id="memory",
                name="Memory",
                version="1.0.0",
                description="Memory app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=build_app_contract(),
                now=now,
            )
            register_app_source(store, source)
            data_root = repo_root / "workspaces" / "default" / "data" / "memory"
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "existing.json").write_text("{}", encoding="utf-8")

            result = reinstall_workspace_app(store, workspace_id="default", app_id="memory", start_path=repo_root, now=now)

            self.assertTrue(result.reused_existing_data_root)
            self.assertEqual(result.binding.status, "enabled")
            self.assertTrue((data_root / "existing.json").exists())

    def test_compatibility_checks_reject_invalid_contract_and_workspace_mode(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        bad_contract = build_app_source_record(
            app_id="unsafe",
            name="Unsafe",
            version="1.0.0",
            description="Unsafe app",
            publisher="vendor",
            source_kind="external_bundle",
            source_path=str(Path("/tmp") / "unsafe"),
            contract=build_app_contract(
                compatibility=build_app_compatibility(contract_version="2.0"),
            ),
            now=now,
        )
        full_access_only = build_app_source_record(
            app_id="operator-tools",
            name="Operator Tools",
            version="1.0.0",
            description="Operator tools",
            publisher="vendor",
            source_kind="external_bundle",
            source_path=str(Path("/tmp") / "operator-tools"),
            contract=build_app_contract(
                compatibility=build_app_compatibility(supported_workspace_modes=["full-access"]),
            ),
            now=now,
        )

        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            bad_root = repo_root / "apps" / "_bundles" / "unsafe" / "1.0.0"
            good_root = repo_root / "apps" / "_bundles" / "operator-tools" / "1.0.0"
            bad_root.mkdir(parents=True, exist_ok=True)
            good_root.mkdir(parents=True, exist_ok=True)
            bad_contract = build_app_source_record(
                app_id="unsafe",
                name="Unsafe",
                version="1.0.0",
                description="Unsafe app",
                publisher="vendor",
                source_kind="external_bundle",
                source_path=str(bad_root),
                contract=build_app_contract(
                    compatibility=build_app_compatibility(contract_version="2.0"),
                ),
                now=now,
            )
            full_access_only = build_app_source_record(
                app_id="operator-tools",
                name="Operator Tools",
                version="1.0.0",
                description="Operator tools",
                publisher="vendor",
                source_kind="external_bundle",
                source_path=str(good_root),
                contract=build_app_contract(
                    compatibility=build_app_compatibility(supported_workspace_modes=["full-access"]),
                ),
                now=now,
            )
            register_app_source(store, bad_contract)
            register_app_source(store, full_access_only)
            with self.assertRaises(AppCompatibilityError):
                install_external_app(store, source_id=bad_contract.source_id, workspace_id="default", start_path=repo_root, now=now)
            with self.assertRaises(AppCompatibilityError):
                install_external_app(store, source_id=full_access_only.source_id, workspace_id="acme", start_path=repo_root, now=now)

    def test_cannot_enable_before_install_and_can_transition_installed_to_enabled(self) -> None:
        store = self.make_store()
        with self.assertRaises(WorkspaceAppBindingNotFoundError):
            transition_workspace_app_status(store, workspace_id="default", app_id="mail", target_status="enabled")

        now = datetime.now(tz=UTC)
        source = build_app_source_record(
            app_id="mail",
            name="Mail",
            version="1.0.0",
            description="Mail app",
            publisher="maverick",
            source_kind="platform",
            source_path=str(Path("/tmp") / "unused"),
            contract=build_app_contract(),
            now=now,
        )
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "mail"
            app_root.mkdir(parents=True, exist_ok=True)
            source = build_app_source_record(
                app_id="mail",
                name="Mail",
                version="1.0.0",
                description="Mail app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=build_app_contract(),
                now=now,
            )
            register_app_source(store, source)
            install_external_app(
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
        source = build_app_source_record(
            app_id="widgets",
            name="Widgets",
            version="1.0.0",
            description="Widgets app",
            publisher="maverick",
            source_kind="platform",
            source_path=str(Path("/tmp") / "unused"),
            contract=build_app_contract(),
            now=now,
        )
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "widgets"
            app_root.mkdir(parents=True, exist_ok=True)
            source = build_app_source_record(
                app_id="widgets",
                name="Widgets",
                version="1.0.0",
                description="Widgets app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=build_app_contract(),
                now=now,
            )
            register_app_source(store, source)
            install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
            with self.assertRaises(AppLifecycleError):
                transition_workspace_app_status(
                    store,
                    workspace_id="default",
                    app_id="widgets",
                    target_status="rolled_back",
                    now=now,
                )

    def test_external_bundle_must_live_under_trusted_installation_root(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            rogue_bundle = repo_root / "workspaces" / "default" / "apps" / "rogue"
            rogue_bundle.mkdir(parents=True, exist_ok=True)
            source = build_app_source_record(
                app_id="rogue",
                name="Rogue",
                version="1.0.0",
                description="Rogue bundle",
                publisher="vendor",
                source_kind="external_bundle",
                source_path=str(rogue_bundle),
                contract=build_app_contract(),
                now=now,
            )
            register_app_source(store, source)

            with self.assertRaises(AppLifecycleError):
                install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

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
                health_contract=build_app_health_contract(mode="hook", degraded_on_failure=True),
                failure_semantics=build_app_failure_semantics(install_failure="block_activation"),
            )
            source = build_app_source_record(
                app_id="hooks-app",
                name="Hooks App",
                version="1.0.0",
                description="Hooks app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=contract,
                now=now,
            )
            register_app_source(store, source)

            binding = install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)

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
            (lifecycle_root / "install.py").write_text(
                "import time\ntime.sleep(2)\n",
                encoding="utf-8",
            )
            contract = build_app_contract(
                entrypoints=build_app_entrypoints(hooks={"install": "backend/lifecycle/install.py"}),
                hook_timeouts=build_app_hook_timeouts(install_seconds=1),
            )
            source = build_app_source_record(
                app_id="timeout-app",
                name="Timeout App",
                version="1.0.0",
                description="Timeout app",
                publisher="maverick",
                source_kind="platform",
                source_path=str(app_root),
                contract=contract,
                now=now,
            )
            register_app_source(store, source)

            with self.assertRaises(AppLifecycleError):
                install_external_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)


if __name__ == "__main__":
    unittest.main()
