"""Tests for the minimal Phase 12 slice that unblocks Phase 13."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contracts import (
    build_app_contract,
    build_app_distribution,
    build_app_entrypoints,
    build_app_lifecycle,
    build_app_storage,
    build_parsed_app_contract,
    write_app_contract_file,
)
from core.apps.service import (
    fork_store_app_to_workspace,
    install_store_app,
    install_workspace_local_app,
    register_app_source_from_contract,
)
from core.apps.store import AppCollections, MongoAppStore
from core.workspaces.files import (
    build_file_identity,
    discover_workspace_export_files,
    discover_workspace_storage_files,
    export_workspace_bundle,
)


class FakeCollection:
    """Small in-memory collection used by export tests."""

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


class Phase12WorkspaceExportTestCase(unittest.TestCase):
    """Verify file inventory, export discovery, and minimal app participation."""

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

    def write_contract(self, app_root: Path, *, app_id: str, contract=None) -> None:
        parsed = build_parsed_app_contract(
            app_id=app_id,
            name=app_id.title(),
            version="1.0.0",
            description=f"{app_id} app",
            publisher="maverick",
            contract=contract or build_app_contract(),
        )
        write_app_contract_file(app_root, parsed)

    def test_discover_workspace_storage_files_reads_uploaded_and_generated_roots(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspaces" / "default"
            uploaded = workspace_root / "storage" / "uploaded" / "brief.txt"
            generated = workspace_root / "storage" / "generated" / "report.md"
            uploaded.parent.mkdir(parents=True, exist_ok=True)
            generated.parent.mkdir(parents=True, exist_ok=True)
            uploaded.write_text("brief", encoding="utf-8")
            generated.write_text("# report", encoding="utf-8")

            discovered = discover_workspace_storage_files(workspace_root)

            self.assertEqual(
                [path.relative_to(workspace_root).as_posix() for path in discovered],
                [
                    "storage/generated/report.md",
                    "storage/uploaded/brief.txt",
                ],
            )

    def test_stable_file_identity_does_not_collapse_duplicate_content_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspaces" / "default"
            first = workspace_root / "storage" / "generated" / "first.txt"
            second = workspace_root / "storage" / "generated" / "second.txt"
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_text("same-bytes", encoding="utf-8")
            second.write_text("same-bytes", encoding="utf-8")

            first_identity = build_file_identity(first, workspace_root)
            second_identity = build_file_identity(second, workspace_root)

            self.assertNotEqual(first_identity.file_id, second_identity.file_id)

    def test_export_bundle_excludes_runtime_logs_tmp_and_keeps_data_and_storage(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "workspaces" / "default"
            exported_paths = {
                workspace_root / "storage" / "uploaded" / "brief.txt": "brief",
                workspace_root / "storage" / "generated" / "report.md": "# report",
                workspace_root / "data" / "chat" / "thread.json": "{}",
                workspace_root / "data" / "chat" / "cache" / "index.json": "{}",
            }
            excluded_paths = {
                workspace_root / "runtime" / "state.json": "{}",
                workspace_root / "logs" / "workspace" / "events.log": "event",
                workspace_root / "tmp" / "scratch.txt": "scratch",
            }
            for path, payload in {**exported_paths, **excluded_paths}.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")

            discovered = discover_workspace_export_files(workspace_root)
            bundle = export_workspace_bundle("default", workspace_root)

            self.assertEqual(
                [path.relative_to(workspace_root).as_posix() for path in discovered],
                [
                    "data/chat/thread.json",
                    "storage/generated/report.md",
                    "storage/uploaded/brief.txt",
                ],
            )
            self.assertEqual(bundle.manifest.schema_versions["app_contract"], "1.0")
            self.assertEqual(
                [identity.relative_path for identity in bundle.manifest.files],
                [
                    "data/chat/thread.json",
                "storage/generated/report.md",
                "storage/uploaded/brief.txt",
                ],
            )

    def test_export_bundle_runs_declared_app_export_hook_before_manifest(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            workspace_root = repo_root / "workspaces" / "default"
            app_root = repo_root / "apps" / "reports"
            lifecycle_root = app_root / "backend" / "lifecycle"
            lifecycle_root.mkdir(parents=True, exist_ok=True)
            (lifecycle_root / "export.py").write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                "payload = json.loads(sys.stdin.read() or '{}')\n"
                "Path('export-ran.txt').write_text(payload['data_root'], encoding='utf-8')\n"
                "Path('export-hook-name.txt').write_text(payload['hook_name'], encoding='utf-8')\n",
                encoding="utf-8",
            )
            contract = build_app_contract(
                storage=build_app_storage(data_schema_version="7"),
                lifecycle=build_app_lifecycle(export=True),
                entrypoints=build_app_entrypoints(hooks={"export": "backend/lifecycle/export.py"}),
            )
            self.write_contract(app_root, app_id="reports", contract=contract)
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
                start_path=repo_root,
                now=now,
            )
            output_file = workspace_root / "storage" / "generated" / "report.md"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text("# report", encoding="utf-8")

            bundle = export_workspace_bundle("default", workspace_root, app_store=store, start_path=repo_root)

            self.assertEqual(len(bundle.participants), 1)
            self.assertEqual(bundle.participants[0].strategy, "export_hook")
            self.assertEqual(bundle.participants[0].data_schema_version, "7")
            self.assertEqual((app_root / "export-ran.txt").read_text(encoding="utf-8"), str(repo_root / "workspaces" / "default" / "data" / "reports"))
            self.assertEqual((app_root / "export-hook-name.txt").read_text(encoding="utf-8"), "workspace_export")
            self.assertEqual(bundle.manifest.known_apps[0].app_id, "reports")
            self.assertEqual(bundle.manifest.known_apps[0].data_schema_version, "7")

    def test_export_manifest_includes_workspace_fork_provenance(self) -> None:
        store = self.make_store()
        now = datetime.now(tz=UTC)
        with TemporaryDirectory() as temp_dir:
            repo_root = self.make_repo_root(temp_dir)
            workspace_root = repo_root / "workspaces" / "acme"
            app_root = repo_root / "apps" / "customizable"
            contract = build_app_contract(
                distribution=build_app_distribution(mode="source_available", source_access="forkable"),
            )
            self.write_contract(app_root, app_id="customizable", contract=contract)
            source = register_app_source_from_contract(
                store,
                source_kind="platform",
                source_path=str(app_root),
                now=now,
            )
            fork_store_app_to_workspace(
                store,
                source_id=source.source_id,
                workspace_id="acme",
                start_path=repo_root,
                now=now,
            )
            install_workspace_local_app(
                store,
                workspace_id="acme",
                app_id="customizable",
                start_path=repo_root,
                now=now,
            )

            bundle = export_workspace_bundle("acme", workspace_root, app_store=store, start_path=repo_root)

            app_ref = bundle.manifest.known_apps[0]
            self.assertEqual(app_ref.app_id, "customizable")
            self.assertEqual(app_ref.source_kind, "workspace_local_project")
            self.assertEqual(app_ref.forked_from_source_id, source.source_id)
            self.assertEqual(app_ref.forked_from_version, source.version)


if __name__ == "__main__":
    unittest.main()
