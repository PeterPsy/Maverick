"""Split tests from app hosting helper module."""

from __future__ import annotations

from tests.support.app_hosting import *


class TestAppHooksAndUpgrades(AppHostingTestBase):
    """Focused test slice."""

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

    def test_upgrade_rejects_target_source_for_different_app(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            foo_root = repo_root / "apps" / "_bundles" / "foo" / "1.0.0"
            bar_root = repo_root / "apps" / "_bundles" / "bar" / "2.0.0"
            self.write_contract(foo_root, app_id="foo")
            self.write_contract(bar_root, app_id="bar", version="2.0.0")
            foo_source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(foo_root),
                now=now,
            )
            bar_source = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(bar_root),
                now=now,
            )
            install_store_app(store, source_id=foo_source.source_id, workspace_id="default", start_path=repo_root, now=now)

            with self.assertRaises(AppLifecycleError):
                upgrade_workspace_app(
                    store,
                    workspace_id="default",
                    app_id="foo",
                    target_source_id=bar_source.source_id,
                    start_path=repo_root,
                    now=now,
                )

    def test_workspace_fork_upgrade_to_store_source_requires_explicit_rebase(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            store_root = repo_root / "apps" / "customizable"
            upgraded_store_root = repo_root / "apps" / "_bundles" / "customizable" / "2.0.0"
            self.write_contract(
                store_root,
                app_id="customizable",
                contract=build_app_contract(
                    distribution=build_app_distribution(mode="source_available", source_access="forkable"),
                ),
            )
            self.write_contract(upgraded_store_root, app_id="customizable", version="2.0.0")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(store_root),
                now=now,
            )
            target = register_app_source_from_contract(
                store,
                source_kind="external_bundle",
                source_path=str(upgraded_store_root),
                now=now,
            )
            fork_store_app_to_workspace(store, source_id=source.source_id, workspace_id="acme", start_path=repo_root, now=now)
            install_workspace_local_app(store, workspace_id="acme", app_id="customizable", start_path=repo_root, now=now)

            with self.assertRaises(AppLifecycleError):
                upgrade_workspace_app(
                    store,
                    workspace_id="acme",
                    app_id="customizable",
                    target_source_id=target.source_id,
                    start_path=repo_root,
                    now=now,
                )

            result = upgrade_workspace_app(
                store,
                workspace_id="acme",
                app_id="customizable",
                target_source_id=target.source_id,
                rebase_workspace_fork=True,
                start_path=repo_root,
                now=now,
            )

            self.assertEqual(result.binding.source_kind, "external_bundle")
            self.assertEqual(result.binding.active_version, "2.0.0")
