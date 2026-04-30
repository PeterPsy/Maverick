"""Split tests from app hosting helper module."""

from __future__ import annotations

from tests.support.app_hosting import *


class TestAppStatus(AppHostingTestBase):
    """Focused test slice."""

    def test_uninstall_preserves_data_and_removes_binding(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "sample-app"
            self.write_contract(app_root, app_id="sample-app", name="record-centric")
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            data_root = repo_root / "workspaces" / "default" / "data" / "sample-app"
            install_store_app(store, source_id=source.source_id, workspace_id="default", start_path=repo_root, now=now)
            (data_root / "records.json").write_text("{}", encoding="utf-8")

            uninstall_workspace_app(store, workspace_id="default", app_id="sample-app")

            self.assertTrue(data_root.is_dir())
            with self.assertRaises(WorkspaceAppBindingNotFoundError):
                store.get_workspace_app_binding(workspace_id="default", app_id="sample-app")

    def test_purge_data_is_separate_from_uninstall(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            data_root = repo_root / "workspaces" / "default" / "data" / "reports"
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "snapshot.json").write_text("{}", encoding="utf-8")

            removed_root = purge_workspace_app_data(workspace_id="default", app_id="reports", start_path=repo_root)

            self.assertEqual(removed_root, data_root)
            self.assertFalse(data_root.exists())

    def test_purge_data_rejects_app_id_path_traversal(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)

            with self.assertRaises(ValueError):
                purge_workspace_app_data(workspace_id="default", app_id="../secrets", start_path=repo_root)

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
