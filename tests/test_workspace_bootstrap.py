"""Tests for workspace path contracts and workspace bootstrap."""

from pathlib import Path
import tempfile
import unittest

from core.apps.paths import installed_apps_root, workspace_app_data_root, workspace_apps_root
from core.runtime.paths import workspace_runtime_root
from core.workspaces.errors import InvalidWorkspaceIdError
from core.workspaces.files import build_export_manifest, build_file_identity
from core.workspaces.service import ensure_default_workspace, ensure_workspace_layout


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
        (repo_root / "local-skills").mkdir()
        (repo_root / "scripts").mkdir()
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        (repo_root / "IMPLEMENTATION_TASKLIST.md").write_text("", encoding="utf-8")
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
        self.assertEqual(workspace_apps_root(workspace_id="acme", start_path=repo_root), workspace.apps)
        self.assertEqual(workspace_app_data_root("acme", "chat", start_path=repo_root), workspace.data / "chat")
        self.assertEqual(workspace_runtime_root("acme", start_path=repo_root), workspace.runtime)

    def test_file_identity_and_export_manifest_follow_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir) / "default"
            data_root = workspace_root / "data" / "chat"
            data_root.mkdir(parents=True)
            chat_state = data_root / "state.json"
            chat_state.write_text('{"status":"ok"}', encoding="utf-8")

            identity = build_file_identity(file_path=chat_state, workspace_root=workspace_root)
            manifest = build_export_manifest(workspace_id="default", workspace_root=workspace_root, files=[chat_state])

            self.assertEqual(identity.relative_path, "data/chat/state.json")
            self.assertEqual(len(identity.file_id), 64)
            self.assertEqual(len(identity.content_hash), 64)
            self.assertEqual(manifest.manifest_version, "1")
            self.assertEqual(manifest.workspace_id, "default")
            self.assertEqual(len(manifest.files), 1)


if __name__ == "__main__":
    unittest.main()
