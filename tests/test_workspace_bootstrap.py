"""Tests for workspace path contracts and workspace bootstrap."""

from pathlib import Path
import tempfile
import unittest

from core.api.application import create_application
from core.apps.paths import external_app_bundles_root, installed_apps_root, workspace_app_data_root, workspace_apps_root
from core.apps.service import build_workspace_app_binding_record
from core.runtime.paths import workspace_runtime_root
from core.workspaces.errors import InvalidWorkspaceIdError
from core.workspaces.files import build_export_manifest, build_file_identity
from core.workspaces.service import ensure_default_workspace, ensure_workspace_layout
from core.workspaces.store import WorkspaceCollections, MongoWorkspaceStore


class FakeCollection:
    """Small in-memory collection for workspace bootstrap tests."""

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


class WorkspaceBootstrapTestCase(unittest.TestCase):
    """Verify canonical path helpers and workspace layout creation."""

    def make_temp_repo_root(self) -> Path:
        """Create a minimal Maverick v3-shaped repository root for isolated tests."""
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        repo_root = Path(temp_dir.name) / "maverick-v3"
        (repo_root / "core").mkdir(parents=True)
        (repo_root / "apps").mkdir()
        (repo_root / "workspaces").mkdir()
        (repo_root / "docs" / "architecture").mkdir(parents=True)
        (repo_root / "scripts").mkdir()
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def test_workspace_layout_is_materialized(self) -> None:
        repo_root = self.make_temp_repo_root()
        workspace = ensure_workspace_layout(workspace_id="default", start_path=repo_root)

        self.assertTrue(workspace.apps.is_dir())
        self.assertTrue(workspace.data.is_dir())
        self.assertTrue(workspace.logs.is_dir())
        self.assertTrue(workspace.runtime.is_dir())
        self.assertTrue(workspace.uploaded_storage.is_dir())
        self.assertTrue(workspace.generated_storage.is_dir())
        self.assertTrue(workspace.tests.is_dir())
        self.assertTrue(workspace.tmp.is_dir())

    def test_default_workspace_bootstrap_uses_default_id(self) -> None:
        repo_root = self.make_temp_repo_root()
        workspace = ensure_default_workspace(start_path=repo_root)
        self.assertEqual(workspace.workspace_id, "default")

    def test_invalid_workspace_ids_are_rejected(self) -> None:
        with self.assertRaises(InvalidWorkspaceIdError):
            ensure_workspace_layout(workspace_id="Bad Workspace", start_path=Path(__file__))

    def test_app_and_runtime_paths_align_with_workspace_contract(self) -> None:
        repo_root = self.make_temp_repo_root()
        workspace = ensure_workspace_layout(workspace_id="acme", start_path=repo_root)

        self.assertEqual(installed_apps_root(start_path=repo_root), repo_root / "apps")
        self.assertEqual(external_app_bundles_root(start_path=repo_root), repo_root / "apps" / "_bundles")
        self.assertEqual(workspace_apps_root(workspace_id="acme", start_path=repo_root), workspace.apps)
        self.assertEqual(workspace_app_data_root("acme", "chat", start_path=repo_root), workspace.data / "chat")
        self.assertEqual(workspace_runtime_root("acme", start_path=repo_root), workspace.runtime)

    def test_file_identity_survives_rename_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "default"
            data_root = workspace_root / "data" / "chat"
            data_root.mkdir(parents=True)
            chat_state = data_root / "state.json"
            chat_state.write_text('{"status":"ok"}', encoding="utf-8")

            identity = build_file_identity(file_path=chat_state, workspace_root=workspace_root)
            renamed_state = data_root / "state-renamed.json"
            chat_state.rename(renamed_state)
            renamed_identity = build_file_identity(file_path=renamed_state, workspace_root=workspace_root)

            self.assertEqual(identity.file_id, renamed_identity.file_id)
            self.assertEqual(renamed_identity.relative_path, "data/chat/state-renamed.json")
            self.assertEqual(renamed_identity.file_role, "app_data")
            self.assertEqual(len(identity.content_hash), 64)

    def test_export_manifest_includes_schema_versions_and_app_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "default"
            generated_root = workspace_root / "storage" / "generated"
            generated_root.mkdir(parents=True)
            report = generated_root / "report.md"
            report.write_text("# report", encoding="utf-8")
            binding = build_workspace_app_binding_record(
                workspace_id="default",
                app_id="reports",
                source_record_id="platform:reports:1.0.0",
                source_kind="platform",
                status="enabled",
                active_version="1.0.0",
                data_root=str(workspace_root / "data" / "reports"),
            )
            manifest = build_export_manifest(
                workspace_id="default",
                workspace_root=workspace_root,
                files=[report],
                app_bindings=[binding],
                schema_versions={"workspace_export": "2", "file_inventory": "1", "app_contract": "1.0"},
            )

            self.assertEqual(manifest.manifest_version, "2")
            self.assertEqual(manifest.workspace_id, "default")
            self.assertEqual(manifest.schema_versions["app_contract"], "1.0")
            self.assertEqual(len(manifest.known_apps), 1)
            self.assertEqual(manifest.known_apps[0].app_id, "reports")
            self.assertEqual(len(manifest.files), 1)
            self.assertEqual(manifest.files[0].file_role, "generated")

    def test_application_bootstrap_materializes_default_workspace_and_registry_record(self) -> None:
        repo_root = self.make_temp_repo_root()
        store = MongoWorkspaceStore(
            WorkspaceCollections(
                workspaces=FakeCollection(),
                memberships=FakeCollection(),
                governance=FakeCollection(),
                quotas=FakeCollection(),
                active_workspace_selections=FakeCollection(),
            )
        )

        application = create_application(start_path=repo_root, workspace_store=store)

        self.assertEqual(application["default_workspace_id"], "default")
        self.assertTrue((repo_root / "workspaces" / "default").is_dir())
        self.assertEqual(store.get_workspace("default").workspace_id, "default")
        self.assertTrue(store.get_governance("default").allow_full_access_runtime)


if __name__ == "__main__":
    unittest.main()
