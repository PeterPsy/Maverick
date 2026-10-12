"""Setup is a trusted Root document; fresh installers include the host worker."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.app_mounts import handle_root_shell, handle_root_shell_static_asset
from core.installation.host_units import render_service
from core.shared.installer import render_install_plan
from tests.unit.shared.test_installer_systemd import _make_config


class HostIntegrationTests(unittest.TestCase):
    def test_setup_runs_as_root_shell_document_while_public_html_remains_inert(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'frontend').mkdir()
            (root / 'frontend' / 'installation.html').write_text('<html><script src="/setup.js"></script></html>')
            parsed = SimpleNamespace(contract=SimpleNamespace(entrypoints=SimpleNamespace(frontend='frontend')))
            common = dict(workspace_id='default', root_shell_app_id='custom-shell', start_path=root)
            with patch('core.api.app_mounts.resolve_app_surface', return_value=(None, root, parsed)):
                headers = []
                result = handle_root_shell(None, document='installation.html', start_response=lambda status, value: headers.extend(value), **common)
                self.assertIn(b'/setup.js', b''.join(result))
                self.assertNotIn('Content-Security-Policy', dict(headers))
                headers.clear()
                handle_root_shell_static_asset(None, subpath='installation.html', start_response=lambda status, value: headers.extend(value), **common)
                self.assertIn('sandbox', dict(headers)['Content-Security-Policy'])

    def test_fresh_installer_renders_worker_without_legacy_domain_placeholders(self):
        config = _make_config(Path(__file__).resolve().parents[3])
        rendered = render_install_plan(config)
        self.assertIn(config.systemd_dir / 'maverick-installation.timer', rendered)
        self.assertNotIn(config.systemd_dir / 'maverick-wildcard-tls.service', rendered)
        unit = rendered[config.systemd_dir / 'maverick-installation.service']
        self.assertIn('installation_worker.py', unit)
        self.assertNotIn('{{', unit)

    def test_migrated_host_runs_completion_outside_the_chroot(self):
        unit = render_service(Path('/opt/maverick'), root_directory='/srv/migration/root')
        self.assertIn('RootDirectoryStartOnly=yes', unit)
        self.assertIn('ExecStartPost=/usr/bin/python3 /srv/migration/root/opt/maverick/scripts/deploy/installation_after_tick.py', unit)
