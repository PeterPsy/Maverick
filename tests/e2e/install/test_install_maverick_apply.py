"""Installer live-apply failure flow tests."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
