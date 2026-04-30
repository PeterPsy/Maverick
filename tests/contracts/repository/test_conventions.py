"""Tests for repository-level discovery and conventions."""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest

from core.shared.repository import discover_repository_root, installation_paths


class RepositoryConventionsTestCase(unittest.TestCase):
    """Verify repository discovery and canonical installation roots."""

    def test_installation_paths_resolve_from_nested_module_path(self) -> None:
        current_file = Path(__file__)
        paths = installation_paths(start_path=current_file)

        self.assertTrue((paths.repository_root / "AGENTS.md").is_file())
        self.assertEqual(paths.core_root, paths.repository_root / "core")
        self.assertEqual(paths.apps_root, paths.repository_root / "apps")
        self.assertEqual(paths.workspaces_root, paths.repository_root / "workspaces")
        self.assertEqual(paths.architecture_docs_root, paths.repository_root / "docs" / "architecture")

    def test_repository_root_discovery_does_not_require_generated_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "AGENTS.md").write_text("test", encoding="utf-8")
            (repo_root / "core").mkdir()
            (repo_root / "apps").mkdir()
            nested_path = repo_root / "core" / "shared" / "repository.py"
            nested_path.parent.mkdir(parents=True, exist_ok=True)
            nested_path.write_text("", encoding="utf-8")

            self.assertEqual(discover_repository_root(start_path=nested_path), repo_root)
            self.assertFalse((repo_root / "workspaces").exists())

    def test_open_source_setup_scripts_are_present_and_shell_valid(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        for relative_path in ("scripts/bootstrap_local.sh", "scripts/run_local.sh", "scripts/verify_local.sh"):
            script_path = repo_root / relative_path
            self.assertTrue(script_path.is_file(), relative_path)
            result = subprocess.run(["bash", "-n", str(script_path)], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=f"{relative_path}: {result.stderr}")

    def test_installer_script_is_executable_and_uses_supported_python(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        script_path = repo_root / "scripts" / "install_maverick.py"
        content = script_path.read_text(encoding="utf-8")

        self.assertTrue(script_path.stat().st_mode & 0o111)
        self.assertIn("sys.version_info < (3, 12)", content)
        result = subprocess.run([sys.executable, str(script_path), "--help"], check=False, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_local_bootstrap_and_run_scripts_share_generated_env_contract(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        bootstrap_script = (repo_root / "scripts" / "bootstrap_local.sh").read_text(encoding="utf-8")
        run_script = (repo_root / "scripts" / "run_local.sh").read_text(encoding="utf-8")

        self.assertIn('--install-env "${ROOT_DIR}/.env"', bootstrap_script)
        self.assertIn('--install-env "${ROOT_DIR}/.env"', run_script)
        self.assertIn('PYTHON_BIN="${MAVERICK_PYTHON:-}"', run_script)
        self.assertIn('elif [[ -f "${ROOT_DIR}/.env.maverick" ]]', run_script)
        self.assertIn("MAVERICK_ADMIN_USERNAME is required.", run_script)

    def test_workspace_hygiene_reporter_is_documented_and_machine_readable(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        script_path = repo_root / "scripts" / "check_workspace_hygiene.py"
        docs_path = repo_root / "docs" / "development" / "generated_artifacts.md"

        self.assertTrue(script_path.is_file())
        self.assertIn("check_workspace_hygiene.py", docs_path.read_text(encoding="utf-8"))
        result = subprocess.run(
            ["python3", str(script_path), "--repository-root", str(repo_root), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("summary", payload)
        self.assertIn("tracked_frontend_dist_changes", payload["findings"])

    def test_dependency_inventory_is_generated_and_has_root_and_app_metadata(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        inventory_path = repo_root / "docs" / "legal" / "third_party_inventory.json"
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "1")
        self.assertEqual(payload["root"]["python"]["name"], "maverick")
        self.assertIn("uvicorn[standard]>=0.30", payload["root"]["python"]["runtime_dependencies"])
        self.assertTrue(payload["apps"])
        self.assertTrue(all("package_name" in item for item in payload["apps"]))

    def test_public_release_docs_exist(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        required_paths = [
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

        self.assertEqual(pyproject["project"]["license"], {"text": "MIT"})
        self.assertEqual(pyproject["tool"]["setuptools"]["packages"]["find"]["include"], ["core*"])
        self.assertTrue(pyproject["tool"]["setuptools"]["packages"]["find"]["namespaces"])

    def test_root_tests_are_layered_not_flat(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        flat_tests = sorted(path.name for path in (repo_root / "tests").glob("test_*.py"))

        self.assertEqual(flat_tests, [])

    def test_root_test_files_stay_small_and_named_for_domains(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        oversized = []
        historical_names = []
        historical_content = []
        historical_pattern = re.compile("|".join(["phase" + r"[0-9]", "test_" + "phase", "Phase " + r"[0-9]"]))

        for test_file in sorted((repo_root / "tests").glob("**/test_*.py")):
            relative = test_file.relative_to(repo_root).as_posix()
            line_count = len(test_file.read_text(encoding="utf-8").splitlines())
            if line_count > 500:
                oversized.append(f"{relative}:{line_count}")
            if historical_pattern.search(relative):
                historical_names.append(relative)
            content = test_file.read_text(encoding="utf-8")
            if historical_pattern.search(content):
                historical_content.append(relative)

        self.assertEqual(oversized, [])
        self.assertEqual(historical_names, [])
        self.assertEqual(historical_content, [])

    def test_p2_refactor_sibling_modules_stay_small(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        groups = [
            ("core", "providers", "provider_codex*.py"),
            ("core", "api", "app_store*.py"),
            ("core", "providers", "codex_app_server_runtime*.py"),
            ("core", "runtime", "turn_submission_service*.py"),
            ("core", "apps", "contract_parser*.py"),
            ("core", "app_sdk", "cli_*.py"),
            ("core", "runtime", "lifecycle_service*.py"),
        ]

        oversized = []
        for group in groups:
            base = repo_root.joinpath(*group[:-1])
            for module_path in sorted(base.glob(group[-1])):
                if module_path.suffix != ".py":
                    continue
                line_count = len(module_path.read_text(encoding="utf-8").splitlines())
                if line_count > 300:
                    relative = module_path.relative_to(repo_root).as_posix()
                    oversized.append(f"{relative}:{line_count}")

        self.assertEqual(oversized, [])

    def test_root_tests_do_not_reference_first_party_app_directories(self) -> None:
        repo_root = installation_paths(start_path=Path(__file__)).repository_root
        app_ids = {
            path.name
            for path in (repo_root / "apps").iterdir()
            if path.is_dir() and (path / "app_contract.json").is_file()
        }
        forbidden = []
        for test_file in sorted((repo_root / "tests").glob("**/test_*.py")):
            content = test_file.read_text(encoding="utf-8")
            for app_id in app_ids:
                tuple_fragment = f'"apps", "{app_id}"'
                if (
                    f"apps/{app_id}" in content
                    or f'"apps" / "{app_id}"' in content
                    or f"'apps' / '{app_id}'" in content
                    or tuple_fragment in content
                ):
                    forbidden.append(f"{test_file.relative_to(repo_root).as_posix()} -> {app_id}")

        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
