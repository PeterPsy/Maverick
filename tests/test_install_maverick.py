"""Tests for the Maverick installer CLI and rendering helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.shared.installer import (
    InstallerConfig,
    default_nginx_conf_path,
    default_output_root,
    default_systemd_dir,
    render_install_plan,
)
from scripts.install_maverick import main as installer_main


class InstallerRenderingTestCase(unittest.TestCase):
    def make_config(self, repo_root: Path, *, hostname: str | None, local_only: bool) -> InstallerConfig:
        output_root = default_output_root(repo_root)
        return InstallerConfig(
            repository_root=repo_root,
            install_root=repo_root,
            output_root=output_root,
            service_user="ubuntu",
            service_group="ubuntu",
            bind_host="127.0.0.1",
            hostname=hostname,
            public_scheme="https",
            core_port=8014,
            rescue_port=8015,
            bootstrap=False,
            verify=False,
            local_only=local_only,
            acme_root=None if hostname is None else Path("/var/www") / hostname,
            systemd_dir=default_systemd_dir(output_root),
            nginx_conf_path=None if hostname is None else default_nginx_conf_path(output_root, hostname=hostname),
        )

    def test_render_install_plan_renders_custom_hostname_and_units(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = self.make_config(repo_root, hostname="maverick.example.test", local_only=False)

        rendered = render_install_plan(config)

        core_service = rendered[config.systemd_dir / "maverick3-core.service"]
        nginx_conf = rendered[config.nginx_conf_path]
        manifest = json.loads(rendered[config.output_root / "install-manifest.json"])
        self.assertIn("WorkingDirectory=" + str(repo_root), core_service)
        self.assertIn("--port 8014", core_service)
        self.assertIn("server_name maverick.example.test;", nginx_conf)
        self.assertIn("ssl_certificate /etc/letsencrypt/live/maverick.example.test/fullchain.pem;", nginx_conf)
        self.assertEqual(manifest["public_url"], "https://maverick.example.test")

    def test_render_install_plan_skips_nginx_for_local_only_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = self.make_config(repo_root, hostname=None, local_only=True)

        rendered = render_install_plan(config)

        self.assertEqual(json.loads(rendered[config.output_root / "install-manifest.json"])["public_url"], "http://127.0.0.1:8014")

    def test_installer_main_writes_rendered_files_without_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            exit_code = installer_main(
                [
                    "--hostname",
                    "maverick.example.test",
                    "--output-root",
                    str(output_root),
                    "--skip-bootstrap",
                    "--skip-verify",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_root / "systemd" / "maverick3-core.service").is_file())
            self.assertTrue((output_root / "nginx" / "maverick.example.test.conf").is_file())
            self.assertTrue((output_root / "install-manifest.json").is_file())

    def test_installer_main_requires_hostname_without_local_only(self) -> None:
        with self.assertRaises(SystemExit):
            installer_main(["--skip-bootstrap", "--skip-verify"])

    def test_installer_main_runs_bootstrap_and_verify_when_requested(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.subprocess.run") as mocked_run:
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--output-root",
                        str(output_root),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(mocked_run.call_args_list[0].args[0], [str(repo_root / "scripts" / "bootstrap_local.sh")])
        self.assertEqual(mocked_run.call_args_list[1].args[0], [str(repo_root / "scripts" / "verify_local.sh")])


if __name__ == "__main__":
    unittest.main()
