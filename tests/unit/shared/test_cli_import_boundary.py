"""Installed Core imports do not depend on repository deployment-script imports."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliImportBoundaryTests(unittest.TestCase):
    def test_core_cli_and_host_primitives_import_with_only_core_source_visible(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / "core").symlink_to(root / "core", target_is_directory=True)
            probe = """import sys
sys.path.insert(0, sys.argv[1])
import core.app_sdk.cli
from core.installation import certificates, host_configuration
from core.api import persistence_admin
assert not any(name == 'scripts' or name.startswith('scripts.') for name in sys.modules)
assert callable(core.app_sdk.cli.main)
assert persistence_admin.atomic_replace.__module__ == 'core.installation.protected_material'
assert certificates.refresh_credentials.__module__ == 'core.installation.dns_credentials'
assert host_configuration.reload_nginx.__module__ == 'core.installation.nginx_control'
"""
            result = subprocess.run([sys.executable, "-I", "-c", probe, str(source)],
                                    cwd=source, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
