"""App bootstrap dependencies must import before lifecycle hooks can run."""

from pathlib import Path
import subprocess
import sys
import unittest


class BootstrapImportTests(unittest.TestCase):
    def test_install_hook_dependencies_import(self) -> None:
        backend = Path(__file__).resolve().parents[1] / "backend"
        result = subprocess.run(
            [sys.executable, "-c", "import lifecycle"],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
