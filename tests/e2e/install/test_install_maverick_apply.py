"""Tests for applying rendered Maverick installation plans."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.shared.installer import (
    InstallerConfig,
    _ensure_symlink,
    _write_file,
    apply_install_plan,
    render_install_plan,
    request_tls_certificate,
)
from scripts.install_maverick import LIVE_APPLY_FAILED_EXIT_CODE, main as installer_main


class InstallerApplyFlowTestCase(unittest.TestCase):
    def secret_args(self, output_root: Path) -> list[str]:
        return [
            "--secret-key-file",
            str(output_root / "bootstrap-secrets" / "secret-store.key"),
            "--bootstrap-secret-store-root",
            str(output_root / "bootstrap-secrets"),
        ]

    def admin_password_args(self, output_root: Path) -> list[str]:
        output_root.mkdir(parents=True, exist_ok=True)
        password_file = output_root / "admin-password.txt"
        password_file.write_text("install-admin-password\n", encoding="utf-8")
        return ["--admin-password-file", str(password_file)]

    def test_installer_main_reports_live_apply_command_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch(
                "scripts.install_maverick.apply_install_plan",
                side_effect=subprocess.CalledProcessError(1, ["nginx", "-t"]),
            ), patch(
                "scripts.install_maverick._apply_initial_admin_password",
            ):
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--output-root",
                        str(output_root),
                        "--install-env",
                        str(output_root / "maverick.env"),
                        "--skip-bootstrap",
                        "--skip-verify",
                        "--yes",
                        "--force",
                        *self.admin_password_args(output_root),
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, LIVE_APPLY_FAILED_EXIT_CODE)


class InstallerApplyTestCase(unittest.TestCase):
    def test_apply_install_plan_copies_rendered_files_and_reloads_services(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            temp_root = Path(temp_dir)
            output_root = temp_root / "install"
            config = InstallerConfig(
                repository_root=repo_root,
                install_root=repo_root,
                output_root=output_root,
                service_user="ubuntu",
                service_group="ubuntu",
                bind_host="127.0.0.1",
                hostname="maverick.example.test",
                public_scheme="https",
                core_port=8014,
                rescue_port=8015,
                bootstrap=False,
                verify=False,
                local_only=False,
                acme_root=temp_root / "acme",
                systemd_dir=output_root / "systemd",
                nginx_conf_path=output_root / "nginx" / "maverick.example.test.conf",
                install_env_path=output_root / "maverick.env",
                live_systemd_dir=temp_root / "live-systemd",
                live_nginx_conf_path=temp_root / "sites-available" / "maverick.example.test.conf",
                live_nginx_enabled_path=temp_root / "sites-enabled" / "maverick.example.test.conf",
                build_frontends=False,
                secret_key_file=str(temp_root / "bootstrap-secrets" / "secret-store.key"),
                bootstrap_secret_store_root=str(temp_root / "bootstrap-secrets"),
            )
            rendered = render_install_plan(config)
            for path, content in rendered.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            commands: list[list[str]] = []
            apply_install_plan(config, rendered, run_command=commands.append)

            self.assertTrue((config.live_systemd_dir / "maverick-core.service").is_file())
            self.assertTrue(config.live_nginx_conf_path.is_file())
            self.assertTrue(config.live_nginx_enabled_path.is_symlink())
            self.assertIn(["systemctl", "daemon-reload"], commands)
            self.assertIn(["systemctl", "reload", "nginx"], commands)

    def test_request_tls_certificate_rewrites_nginx_with_https_after_certbot(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            temp_root = Path(temp_dir)
            output_root = temp_root / "install"
            live_nginx_conf = temp_root / "sites-available" / "maverick.example.test.conf"
            config = InstallerConfig(
                repository_root=repo_root,
                install_root=repo_root,
                output_root=output_root,
                service_user="ubuntu",
                service_group="ubuntu",
                bind_host="127.0.0.1",
                hostname="maverick.example.test",
                public_scheme="https",
                core_port=8014,
                rescue_port=8015,
                bootstrap=False,
                verify=False,
                local_only=False,
                acme_root=temp_root / "acme",
                systemd_dir=output_root / "systemd",
                nginx_conf_path=output_root / "nginx" / "maverick.example.test.conf",
                install_env_path=output_root / "maverick.env",
                live_systemd_dir=temp_root / "live-systemd",
                live_nginx_conf_path=live_nginx_conf,
                live_nginx_enabled_path=temp_root / "sites-enabled" / "maverick.example.test.conf",
                build_frontends=False,
            )
            commands: list[list[str]] = []

            request_tls_certificate(config, run_command=commands.append)

            self.assertIn(
                "ssl_certificate /etc/letsencrypt/live/maverick.example.test/fullchain.pem;",
                live_nginx_conf.read_text(encoding="utf-8"),
            )
            self.assertIn(["nginx", "-t"], commands)
            self.assertIn(["systemctl", "reload", "nginx"], commands)

    def test_write_file_uses_privileged_install_when_direct_write_is_denied(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            target = Path(temp_dir) / "systemd" / "maverick-core.service"
            commands: list[list[str]] = []

            with patch("pathlib.Path.write_text", side_effect=PermissionError):
                _write_file(target, "unit\n", run_command=commands.append)

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][:4], ["install", "-D", "-m", "0644"])
            self.assertEqual(commands[0][-1], str(target))

    def test_ensure_symlink_skips_when_link_and_target_are_same_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            target = Path(temp_dir) / "maverick.conf"
            target.write_text("nginx\n", encoding="utf-8")
            commands: list[list[str]] = []

            _ensure_symlink(target, target, run_command=commands.append)

            self.assertEqual(commands, [])
            self.assertFalse(target.is_symlink())


if __name__ == "__main__":
    unittest.main()
