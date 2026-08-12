from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("maverick_test_suite", ROOT / "scripts/test_suite.py")
assert SPEC is not None and SPEC.loader is not None
test_suite = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = test_suite
SPEC.loader.exec_module(test_suite)


class ChangedSuiteTests(unittest.TestCase):
    def test_explicit_paths_are_normalized_without_reading_the_working_tree(self) -> None:
        paths = test_suite.normalize_changed_paths(
            ["./apps/design-studio/backend/service.py", "core/providers/runtime.py"]
        )

        with patch.object(test_suite, "changed_paths", side_effect=AssertionError("working tree consulted")):
            with patch.object(test_suite, "run_app_test_dirs", return_value=0) as app_tests:
                with patch.object(test_suite, "run_discover_dirs", return_value=0) as root_tests:
                    status = test_suite.run_changed(level="fast", jobs=1, changed=paths)

        self.assertEqual(status, 0)
        app_tests.assert_called_once_with(["apps/design-studio/tests"], level="fast", jobs=1)
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
