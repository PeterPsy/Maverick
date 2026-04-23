"""Tests for repository-level discovery and conventions."""

import json
from pathlib import Path
import subprocess
import tomllib
import unittest

from core.shared.repository import installation_paths


class RepositoryConventionsTestCase(unittest.TestCase):
    """Verify repository discovery and canonical installation roots."""

    def test_installation_paths_resolve_from_nested_module_path(self) -> None:
        current_file = Path(__file__)
        paths = installation_paths(start_path=current_file)

        self.assertTrue((paths.repository_root / "AGENTS.md").is_file())
        self.assertTrue((paths.repository_root / "IMPLEMENTATION_TASKLIST.md").is_file())
        self.assertEqual(paths.core_root, paths.repository_root / "core")
        self.assertEqual(paths.apps_root, paths.repository_root / "apps")
        self.assertEqual(paths.workspaces_root, paths.repository_root / "workspaces")
        self.assertEqual(paths.architecture_docs_root, paths.repository_root / "docs" / "architecture")

    def test_open_source_setup_scripts_are_present_and_shell_valid(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        for relative_path in ("scripts/bootstrap_local.sh", "scripts/run_local.sh", "scripts/verify_local.sh"):
            script_path = repo_root / relative_path
            self.assertTrue(script_path.is_file(), relative_path)
            result = subprocess.run(["bash", "-n", str(script_path)], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=f"{relative_path}: {result.stderr}")

    def test_dependency_inventory_is_generated_and_has_root_and_app_metadata(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        inventory_path = repo_root / "docs" / "legal" / "third_party_inventory.json"
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["root"]["python"]["name"], "maverick-v3")
        self.assertIn("uvicorn[standard]>=0.30", payload["root"]["python"]["runtime_dependencies"])
        self.assertIn("chat", [item["app_id"] for item in payload["apps"]])
        self.assertTrue(all("package_name" in item for item in payload["apps"]))

    def test_public_release_docs_exist(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        required_paths = [
            "OPEN_SOURCE_CHECKLIST.md",
            "docs/security/threat_model.md",
            "docs/adr/README.md",
            "docs/reference/core_surfaces.md",
            "docs/reference/runtime_provider_model.md",
            "docs/reference/persistence_model.md",
            "docs/development/supply_chain.md",
            "docs/legal/third_party_inventory.md",
            "docs/legal/third_party_inventory.json",
            "docs/product/setup_onboarding_plan.md",
        ]
        for relative_path in required_paths:
            self.assertTrue((repo_root / relative_path).is_file(), relative_path)

    def test_core_top_level_packages_are_explicit(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        core_root = repo_root / "core"

        self.assertTrue((core_root / "__init__.py").is_file(), "core/__init__.py")
        for package_dir in sorted(path for path in core_root.iterdir() if path.is_dir() and not path.name.startswith("__")):
            self.assertTrue((package_dir / "__init__.py").is_file(), f"{package_dir.relative_to(repo_root)}/__init__.py")

    def test_pyproject_limits_package_discovery_to_core(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["license"], "MIT")
        self.assertEqual(pyproject["tool"]["setuptools"]["packages"]["find"]["include"], ["core*"])
        self.assertTrue(pyproject["tool"]["setuptools"]["packages"]["find"]["namespaces"])


if __name__ == "__main__":
    unittest.main()
