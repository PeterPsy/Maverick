"""Privileged environment/log/backup paths cannot be replaced by Core."""

from dataclasses import replace
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.installation.host_configuration import commit_environment, render_nginx
from core.installation.host_units import render_service
from core.installation.protected_material import (
    create_recovery_backup, prepare_host_logs, protect_service_environment,
    require_root_environment_update, require_service_environment,
)
from core.installation.provisioning import provision_service_paths
from core.shared.installer import render_install_plan
from tests.unit.shared.test_installer_systemd import _make_config


class ProtectedMaterialTests(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() == 0, "Synthetic unprivileged access requires root to drop uid")
    def test_group_reader_cannot_write_or_replace_root_worker_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o755)
            env = root / ".env.loopino"
            env.write_text("LOOPINO_PORT=8014\n")
            os.chown(env, 0, 65534)
            env.chmod(0o640)
            def unprivileged():
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            script = '''import pathlib, sys
path = pathlib.Path(sys.argv[1])
assert path.read_text() == "LOOPINO_PORT=8014\\n"
for operation in (lambda: path.write_text("PYTHONPATH=untrusted"), lambda: path.unlink(),
                  lambda: path.rename(path.with_name("replaced"))):
    try:
        operation()
    except PermissionError:
        continue
    raise AssertionError("Unprivileged environment modification succeeded")
'''
            result = subprocess.run(["/usr/bin/python3", "-I", "-S", "-c", script, str(env)],
                                    preexec_fn=unprivileged, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_root_environment_is_group_readable_and_never_service_owned(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env.loopino"
            env.write_text("LOOPINO_PORT=8014\n")
            env.chmod(0o600)
            calls = []
            protect_service_environment(env, "1234", calls.append)
            self.assertEqual(calls, [["chown", "root:1234", str(env)], ["chmod", "0640", str(env)]])
            if os.geteuid() == 0:
                protect_service_environment(env, "0", lambda command: subprocess.run(command, check=True))
                self.assertEqual((env.stat().st_uid, stat.S_IMODE(env.stat().st_mode)), (0, 0o640))
                require_service_environment(env)
            with patch("core.installation.protected_material.os.geteuid", return_value=1234):
                with self.assertRaises(PermissionError):
                    require_root_environment_update(env)

    def test_env_rejects_writable_or_symlink_parent_and_previously_untrusted_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env.loopino"
            env.write_text("PYTHONPATH=untrusted\n")
            env.chmod(0o666)
            with self.assertRaises(ValueError):
                protect_service_environment(env, "0", lambda _: self.fail("must reject before mutation"))
            env.chmod(0o640)
            root.chmod(0o777)
            with self.assertRaises(ValueError):
                require_service_environment(env)
            root.chmod(0o700)
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                require_service_environment(alias / env.name)
            if os.geteuid() == 0:
                os.chown(env, 1234, 1234)
                with self.assertRaises(ValueError):
                    require_service_environment(env)

    def test_only_root_typed_address_updates_preserve_other_bytes_and_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env.loopino"
            env.write_text("# trusted\nOTHER=value\nLOOPINO_PORT=8014\n")
            env.chmod(0o640)
            from types import SimpleNamespace
            service = SimpleNamespace(store=SimpleNamespace(repository_root=root))
            private = root / "private"; private.mkdir()
            plan = {"hostname": "loopino.example.com", "target_ip": "8.8.8.8"}
            with patch("core.installation.host_configuration.target_environment", return_value={"LOOPINO_SIDECAR_INSTALLATION_DOMAIN": "loopino.example.com"}):
                self.assertTrue(commit_environment(service, plan, private))
            self.assertIn("# trusted\nOTHER=value\n", env.read_text())
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o640)
            with patch("core.installation.protected_material.os.geteuid", return_value=1234):
                with self.assertRaises(PermissionError):
                    commit_environment(service, plan, private)

    def test_log_parents_are_protected_and_distinct_from_service_writable_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            prepare_host_logs(root)
            for name in ("systemd", "nginx"):
                parent = root / "installation/logs" / name
                self.assertFalse(parent.stat().st_mode & 0o022)
                self.assertEqual(parent.stat().st_uid, 0)
            (root / "installation/logs/nginx").chmod(0o777)
            with self.assertRaises(ValueError):
                prepare_host_logs(root)

    def test_host_log_parent_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "installation").mkdir()
            (root / "outside").mkdir()
            (root / "installation/logs").symlink_to(root / "outside", target_is_directory=True)
            with self.assertRaises(ValueError):
                prepare_host_logs(root)
            self.assertEqual(list((root / "outside").iterdir()), [])

    def test_all_rendered_units_and_vhosts_use_explicit_in_root_logs(self):
        root = Path(__file__).resolve().parents[3]
        config = replace(_make_config(root), hostname="loopino.example.com", nginx_conf_path=root / "plan/nginx.conf")
        rendered = render_install_plan(config, force_https_nginx=True)
        for path, content in rendered.items():
            if path.suffix == ".service":
                self.assertIn(f"StandardOutput=append:{root}/installation/logs/systemd/", content)
                self.assertIn(f"StandardError=append:{root}/installation/logs/systemd/", content)
        certs = {key: {"fullchain": "/cert", "private_key": "/key"} for key in ("main", "apps")}
        for content in (rendered[config.nginx_conf_path], render_nginx(config.hostname, certs, 8014, repository_root=root)):
            self.assertEqual(content.count("access_log "), content.count("server_name "))
            self.assertEqual(content.count("error_log "), content.count("server_name "))
            self.assertIn(f"{root}/installation/logs/nginx/main-access.log", content)
            self.assertIn("location = /catalog/api/apps", content)
            self.assertIn("/.well-known/acme-challenge/", content)
        self.assertIn("StandardOutput=append:/migration/projects/loopino/installation/logs/systemd/", render_service(Path("/projects/loopino"), root_directory="/migration"))

    def test_service_handoff_does_not_chown_host_logs_or_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = replace(_make_config(root), service_user="loopino", service_group="loopino")
            config.install_env_path.write_text("KEY=value\n")
            config.install_env_path.chmod(0o600)
            calls = []
            provision_service_paths(config, {config.install_env_path: "env"}, calls.append)
            for command in calls:
                if "loopino:loopino" in command or "-o" in command:
                    self.assertNotIn("/installation/logs", command[-1])
                    self.assertNotEqual(command[-1], str(config.install_env_path))

    def test_recovery_backups_stay_in_exclusive_protected_namespaces(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup = create_recovery_backup(root, "wildcard", "checkpoint")
            self.assertEqual(backup, root / "installation/backups/wildcard/checkpoint")
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
            with self.assertRaises(FileExistsError):
                create_recovery_backup(root, "wildcard", "checkpoint")
            with self.assertRaises(ValueError):
                create_recovery_backup(root, "wildcard", "../escape")
            backup.parent.chmod(0o777)
            with self.assertRaises(ValueError):
                create_recovery_backup(root, "wildcard", "next")
