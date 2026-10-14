"""Installation backing files and exclusive OS symlink rollback contracts."""

from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.installation.host_configuration import managed_nginx_path, stage_host, restore_host
from core.installation.provisioning import provision_service_paths
from core.installation.registrations import register_file, unregister_file
from core.shared.installer import apply_install_plan, default_output_root
from scripts.deploy.install_installation_worker import register_worker_units
from tests.unit.shared.test_installer_systemd import _make_config


class InstallationRegistrationTests(unittest.TestCase):
    def test_registration_never_replaces_foreign_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            link, backing = root / "os/config", root / "installation/nginx/config"
            register_file(link, backing)
            register_file(link, backing)
            self.assertEqual(link.readlink(), backing)
            unregister_file(link, backing)
            for foreign in (False, True):
                if foreign:
                    link.symlink_to(root / "unrelated")
                else:
                    link.write_text("unrelated")
                with self.assertRaises(FileExistsError):
                    register_file(link, backing)
                with self.assertRaises(FileExistsError):
                    unregister_file(link, backing)
                link.unlink()

    def test_worker_units_have_only_symlink_registrations_and_preflight_conflicts(self):
        with tempfile.TemporaryDirectory() as folder:
            root, host = Path(folder) / "product", Path(folder) / "os"
            contents = {"loopino-installation.service": "service", "loopino-installation.timer": "timer"}
            register_worker_units(root, host, contents, host_backing_root=root)
            for name, content in contents.items():
                link = host / "etc/systemd/system" / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.read_text(), content)
                self.assertEqual(link.readlink(), root / "installation/systemd" / name)
            conflict = host / "etc/systemd/system/loopino-installation.timer"
            conflict.unlink(); conflict.write_text("foreign")
            with self.assertRaises(FileExistsError):
                register_worker_units(root, host, {name:"changed" for name in contents}, host_backing_root=root)
            self.assertEqual((root / "installation/systemd/loopino-installation.service").read_text(), "service")
            self.assertEqual(conflict.read_text(), "foreign")

    def test_generic_apply_failure_restores_backing_and_only_removes_new_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = replace(_make_config(root), live_systemd_dir=root / "os/systemd")
            self.assertEqual(default_output_root(root), root / "installation")
            source = config.systemd_dir / "loopino-core.service"
            backing = root / "installation/systemd/loopino-core.service"
            backing.parent.mkdir(parents=True); backing.write_text("before")
            def fail(command):
                if command == ["systemctl", "daemon-reload"]:
                    raise RuntimeError("activation failed")
            with self.assertRaisesRegex(RuntimeError, "activation failed"):
                apply_install_plan(config, {source:"after"}, run_command=fail)
            self.assertEqual(backing.read_text(), "before")
            self.assertFalse((config.live_systemd_dir / source.name).is_symlink())

    def test_worker_activation_failure_rolls_back_new_files_and_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root, host = Path(folder) / "product", Path(folder) / "os"
            def fail():
                raise RuntimeError("activation failed")
            with self.assertRaisesRegex(RuntimeError, "activation failed"):
                register_worker_units(root, host, {"loopino-installation.service":"service"},
                                      host_backing_root=root, activate=fail)
            self.assertFalse((host / "etc/systemd/system/loopino-installation.service").is_symlink())
            self.assertFalse((root / "installation/systemd/loopino-installation.service").exists())

    def test_nginx_validation_failure_restores_backing_and_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = SimpleNamespace(configuration=lambda:{"installation_id":"a"*32},
                                      store=SimpleNamespace(repository_root=root), environment={})
            backing = managed_nginx_path(service, "loopino.example.com")
            self.assertTrue(backing.is_relative_to(root / "installation/nginx"))
            link = root / "os/nginx.conf"
            private = root / "private"; private.mkdir()
            certs = {kind:{"fullchain":"/cert", "private_key":"/key"} for kind in ("main","apps")}
            with patch("core.installation.host_configuration.managed_nginx_registration", return_value=link), \
                 patch("core.installation.host_configuration.check_nginx", side_effect=RuntimeError("invalid")), \
                 patch("core.installation.host_configuration.reload_nginx"):
                with self.assertRaisesRegex(RuntimeError, "invalid"):
                    stage_host(service, {"hostname":"loopino.example.com"}, certs, private)
                self.assertFalse(link.is_symlink())
                self.assertFalse(backing.exists())
                link.parent.mkdir(exist_ok=True); link.write_text("foreign")
                with self.assertRaises(FileExistsError):
                    restore_host(service, private)
                self.assertEqual(link.read_text(), "foreign")

    def test_service_ownership_is_narrow_and_secrets_are_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = replace(_make_config(root), service_user="loopino", service_group="loopino")
            key = root / config.secret_key_file
            calls = []
            provision_service_paths(config, {key:"key", config.install_env_path:"env"}, calls.append)
            self.assertIn(["chown", "loopino:loopino", str(key)], calls)
            self.assertIn(["chmod", "0600", str(key)], calls)
            self.assertTrue(all("-R" not in command for command in calls))
            self.assertTrue(all(str(root / "data/app-artifacts") not in command for command in calls))
            for value in ("core/key", "data/app-artifacts/key", ".toolchains/key", "../key"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    provision_service_paths(replace(config, secret_key_file=value), {}, calls.append)
