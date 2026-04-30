"""Installer TLS failure flow tests."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.install_maverick import TLS_FAILED_EXIT_CODE, main as installer_main


class InstallerTlsFlowTestCase(unittest.TestCase):
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

    def test_installer_main_reports_tls_failure_after_health_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            live_systemd_dir = Path(temp_dir) / "live-systemd"
            live_nginx_conf = Path(temp_dir) / "sites-available" / "maverick.example.test.conf"
            live_nginx_enabled = Path(temp_dir) / "sites-enabled" / "maverick.example.test.conf"
            with patch("core.shared.installer.run_privileged_command"), patch(
                "scripts.install_maverick.check_health",
                return_value={"http://127.0.0.1:8014/health": True},
            ) as mocked_health, patch(
                "scripts.install_maverick.request_tls_certificate",
                side_effect=subprocess.CalledProcessError(1, ["certbot"]),
            ) as mocked_tls, patch(
                "scripts.install_maverick._apply_initial_admin_password",
            ):
                exit_code = installer_main(
                    [
                        "--hostname",
                        "maverick.example.test",
                        "--output-root",
                        str(output_root),
                        "--live-systemd-dir",
                        str(live_systemd_dir),
                        "--install-env",
                        str(output_root / "maverick.env"),
                        "--live-nginx-conf",
                        str(live_nginx_conf),
                        "--live-nginx-enabled",
                        str(live_nginx_enabled),
                        "--skip-bootstrap",
                        "--skip-verify",
                        "--yes",
                        "--force",
                        *self.admin_password_args(output_root),
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, TLS_FAILED_EXIT_CODE)
        mocked_health.assert_called_once()
        mocked_tls.assert_called_once()
