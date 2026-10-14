"""Setup is a trusted Root document; fresh installers include the host worker."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.app_mounts import handle_root_shell, handle_root_shell_static_asset
from core.installation.host_configuration import stage_host, restore_host
from core.installation.service import InstallationService
from core.installation.host_units import render_service
from scripts.deploy.install_installation_worker import service_account_ids
from core.shared.installer import render_install_plan
from tests.unit.shared.test_installer_systemd import _make_config


class HostIntegrationTests(unittest.TestCase):
    def test_operator_installer_accepts_numeric_systemd_accounts(self):
        with patch('scripts.deploy.install_installation_worker.pwd.getpwuid', return_value=SimpleNamespace(pw_uid=1000, pw_gid=1003)):
            self.assertEqual(service_account_ids('1000', ''), (1000, 1003))
            self.assertEqual(service_account_ids('1000', '1004'), (1000, 1004))

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
        self.assertIn(config.systemd_dir / 'loopino-installation.timer', rendered)
        self.assertNotIn(config.systemd_dir / 'loopino-wildcard-tls.service', rendered)
        unit = rendered[config.systemd_dir / 'loopino-installation.service']
        self.assertIn('installation_worker.py', unit)
        self.assertNotIn('{{', unit)

    def test_migrated_host_runs_completion_outside_the_chroot(self):
        unit = render_service(Path('/projects/loopino'), root_directory='/srv/migration/root')
        self.assertIn('RootDirectoryStartOnly=yes', unit)
        self.assertIn('/usr/bin/python3 -I /srv/migration/root/projects/loopino/scripts/deploy/installation_after_tick.py', unit)

    def test_staging_a_new_hostname_preserves_the_active_virtual_host(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = InstallationService(root, environment={})
            service.store.write('configuration', {**service.configuration(), 'installation_id': 'a' * 32})
            certificates = {kind: {'fullchain': '/safe/cert.pem', 'private_key': '/safe/key.pem'} for kind in ['main', 'apps']}
            old, new = 'old.example.com', 'new.example.com'
            old_private, new_private = root / 'old-private', root / 'new-private'
            old_private.mkdir(); new_private.mkdir()
            with patch('core.installation.host_configuration.managed_nginx_path', side_effect=lambda service, host: root / (host + '.conf')), \
                 patch('core.installation.host_configuration.managed_nginx_registration', side_effect=lambda service, host: root / 'os' / (host + '.conf')), \
                 patch('core.installation.host_configuration.check_nginx'), patch('core.installation.host_configuration.reload_nginx'):
                stage_host(service, {'hostname': old}, certificates, old_private)
                before = (root / (old + '.conf')).read_bytes()
                stage_host(service, {'hostname': new}, certificates, new_private)
                self.assertEqual((root / (old + '.conf')).read_bytes(), before)
                self.assertTrue((root / (new + '.conf')).exists())
                restore_host(service, new_private)
                self.assertFalse((root / (new + '.conf')).exists())
                self.assertEqual((root / (old + '.conf')).read_bytes(), before)
