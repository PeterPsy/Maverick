"""Split tests from tests/test_phase4_app_hosting.py."""

from __future__ import annotations

from tests.phase4_app_hosting_helpers import *


class TestPhase4AppInstallation(Phase4AppHostingBase):
    """Focused test slice."""

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

    def test_fork_overwrite_preserves_existing_project_when_contract_write_fails(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            app_root = repo_root / "apps" / "customizable"
            self.write_contract(
                app_root,
                app_id="customizable",
                contract=build_app_contract(
                    distribution=build_app_distribution(mode="source_available", source_access="forkable"),
                ),
            )
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            fork_store_app_to_workspace(store, source_id=source.source_id, workspace_id="acme", start_path=repo_root, now=now)
            fork_root = repo_root / "workspaces" / "acme" / "apps" / "customizable"
            marker = fork_root / "marker.txt"
            marker.write_text("keep", encoding="utf-8")

            with patch("core.apps.forks.write_app_contract_file", side_effect=RuntimeError("write failed")):
                with self.assertRaises(RuntimeError):
                    fork_store_app_to_workspace(
                        store,
                        source_id=source.source_id,
                        workspace_id="acme",
                        start_path=repo_root,
                        now=now,
                        overwrite=True,
                    )

            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
