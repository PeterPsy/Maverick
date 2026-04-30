"""Split tests from app hosting helper module."""

from __future__ import annotations

from tests.support.app_hosting import *


class TestAppReinstall(AppHostingTestBase):
    """Focused test slice."""

    def test_reinstall_reattaches_to_existing_data(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "sample-app"
            self.write_contract(app_root, app_id="sample-app", name="Memory")
            register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            data_root = repo_root / "workspaces" / "default" / "data" / "sample-app"
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "existing.json").write_text("{}", encoding="utf-8")

            result = reinstall_workspace_app(store, workspace_id="default", app_id="sample-app", start_path=repo_root, now=now)

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
