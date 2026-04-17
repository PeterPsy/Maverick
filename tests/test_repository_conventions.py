"""Tests for repository-level discovery and conventions."""

from pathlib import Path
import unittest

from core.shared.repository import installation_paths


class RepositoryConventionsTestCase(unittest.TestCase):
    """Verify repository discovery and canonical installation roots."""

    def test_installation_paths_resolve_from_nested_module_path(self) -> None:
        current_file = Path(__file__)
        paths = installation_paths(start_path=current_file)

        self.assertEqual(paths.repository_root.name, "maverick-v3")
        self.assertEqual(paths.core_root, paths.repository_root / "core")
        self.assertEqual(paths.apps_root, paths.repository_root / "apps")
        self.assertEqual(paths.workspaces_root, paths.repository_root / "workspaces")
        self.assertEqual(paths.architecture_docs_root, paths.repository_root / "docs" / "architecture")
        self.assertEqual(paths.local_skills_root, paths.repository_root / "local-skills")


if __name__ == "__main__":
    unittest.main()

