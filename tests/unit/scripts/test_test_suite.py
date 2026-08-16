from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("maverick_test_suite", ROOT / "scripts/test_suite.py")
assert SPEC is not None and SPEC.loader is not None
test_suite = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = test_suite
SPEC.loader.exec_module(test_suite)


class ChangedSuiteTests(unittest.TestCase):
    def test_discovery_roots_include_tests_below_non_package_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-suite-discovery-") as temporary:
            synthetic_root = Path(temporary)
            unit_root = synthetic_root / "tests/unit"
            package_root = unit_root / "packaged"
            api_root = unit_root / "api"
            nested_root = api_root / "nested"
            for directory in (unit_root, package_root, api_root, nested_root):
                directory.mkdir(parents=True, exist_ok=True)
            (unit_root / "test_root.py").touch()
            (package_root / "__init__.py").touch()
            (package_root / "test_packaged.py").touch()
            (api_root / "test_api.py").touch()
            (nested_root / "test_nested.py").touch()

            with patch.object(test_suite, "REPO_ROOT", synthetic_root):
                roots = test_suite.unittest_discovery_roots("tests/unit")

        self.assertEqual(
            roots,
            ["tests/unit", "tests/unit/api", "tests/unit/api/nested"],
        )

    def test_explicit_paths_are_normalized_without_reading_the_working_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="test-suite-app-") as temporary:
            synthetic_root = Path(temporary)
            (synthetic_root / "apps/sample-app/tests").mkdir(parents=True)
            paths = test_suite.normalize_changed_paths(
                ["./apps/sample-app/backend/service.py", "core/providers/runtime.py"]
            )

            with patch.object(test_suite, "REPO_ROOT", synthetic_root):
                with patch.object(
                    test_suite,
                    "changed_paths",
                    side_effect=AssertionError("working tree consulted"),
                ):
                    with patch.object(test_suite, "run_app_test_dirs", return_value=0) as app_tests:
                        with patch.object(test_suite, "run_discover_dirs", return_value=0) as root_tests:
                            status = test_suite.run_changed(level="fast", jobs=1, changed=paths)

        self.assertEqual(status, 0)
        app_tests.assert_called_once_with(["apps/sample-app/tests"], level="fast", jobs=1)
        root_tests.assert_called_once_with(
            ["tests/e2e/provider_process", "tests/unit/providers"],
            level="fast",
        )

    def test_explicit_paths_reject_absolute_and_parent_traversal(self) -> None:
        for value in ("/repo/core/service.py", "../core/service.py", "core/../service.py"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                test_suite.normalize_changed_paths([value])


if __name__ == "__main__":
    unittest.main()
