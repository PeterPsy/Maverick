"""Installer coverage for the HTTP-01 managed exact-origin TLS mode."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.shared.installer import (
    managed_browser_origin_probe_command,
    preflight_check,
    prepare_managed_browser_origin_tls,
    render_install_plan,
    request_tls_certificate,
)
from tests.e2e.install.installer_test_support import make_installer_config


class ManagedBrowserOriginTlsInstallerTestCase(unittest.TestCase):
    def test_rendered_nginx_loads_only_validated_exact_host_certificates(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            make_installer_config(
                repo_root,
                hostname="maverick.example.test",
                local_only=False,
            ),
            hosted_sidecars=True,
            browser_origin_tls_mode="managed_exact",
            browser_origin_tls_root="/var/lib/maverick/browser-origin-tls",
            browser_origin_acme_webroot="/var/lib/maverick/browser-origin-acme",
        )

        rendered = render_install_plan(config, force_https_nginx=True)
        nginx = rendered[config.nginx_conf_path]
        environment = rendered[config.install_env_path]
        manifest = json.loads(rendered[config.output_root / "install-manifest.json"])

        self.assertIn("location ^~ /.well-known/acme-challenge/", nginx)
        self.assertIn("root /var/lib/maverick/browser-origin-acme;", nginx)
        self.assertIn("map $ssl_server_name $maverick_browser_origin_cert_host", nginx)
        self.assertIn(
            "~^(?<reserved_browser_origin>(?:af|sc)-[a-f0-9]{24}\\.sidecars\\.maverick\\.example\\.test)$",
            nginx,
        )
        self.assertIn(
            "ssl_certificate /var/lib/maverick/browser-origin-tls/served/hosts/"
            "$maverick_browser_origin_cert_host/current/fullchain.pem;",
            nginx,
        )
        self.assertNotIn("maverick.example.test-sidecars/fullchain.pem", nginx)
        self.assertIn("MAVERICK_BROWSER_ORIGIN_TLS_MODE=managed_exact", environment)
        self.assertIn(
            "MAVERICK_BROWSER_ORIGIN_TLS_ROOT=/var/lib/maverick/browser-origin-tls",
            environment,
        )
        self.assertEqual(manifest["browser_origin_tls_mode"], "managed_exact")

    def test_managed_mode_can_bootstrap_without_an_external_wildcard(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            make_installer_config(
                repo_root,
                hostname="maverick.example.test",
                local_only=False,
            ),
            hosted_sidecars=True,
            browser_origin_tls_mode="managed_exact",
            sidecar_tls_cert_path="/missing/external-wildcard.pem",
            sidecar_tls_key_path="/missing/external-wildcard.key",
        )

        with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
            report = preflight_check(config, live_apply=True, request_tls=True)

        self.assertEqual(report.errors, [])

    def test_skip_tls_requires_both_published_probe_names(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-managed-tls-") as temp_dir:
            config = replace(
                make_installer_config(
                    repo_root,
                    hostname="maverick.example.test",
                    local_only=False,
                ),
                hosted_sidecars=True,
                browser_origin_tls_mode="managed_exact",
                browser_origin_tls_root=temp_dir,
            )
            with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
                report = preflight_check(config, live_apply=True, request_tls=False)

        self.assertTrue(
            any("managed browser-origin TLS certificate not found" in error for error in report.errors)
        )

    def test_bootstrap_runs_certbot_as_service_user_for_both_exact_probes(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            make_installer_config(
                repo_root,
                hostname="maverick.example.test",
                local_only=False,
            ),
            hosted_sidecars=True,
            browser_origin_tls_mode="managed_exact",
        )
        commands: list[list[str]] = []

        prepare_managed_browser_origin_tls(config, run_command=commands.append)
        bootstrap = managed_browser_origin_probe_command(config)

        self.assertTrue(all(command[0] == "install" for command in commands))
        self.assertIn("2750", {value for command in commands for value in command})
        self.assertEqual(bootstrap[:4], ["runuser", "--user", "ubuntu", "--"])
        self.assertIn("core.shared.browser_origin_tls", bootstrap)
        self.assertIn(
            "sc-000000000000000000000000.sidecars.maverick.example.test",
            bootstrap,
        )
        self.assertIn(
            "af-000000000000000000000000.sidecars.maverick.example.test",
            bootstrap,
        )

    def test_tls_request_bootstraps_managed_probes_before_final_nginx_reload(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-managed-tls-") as temp_dir:
            root = Path(temp_dir)
            config = replace(
                make_installer_config(
                    repo_root,
                    hostname="maverick.example.test",
                    local_only=False,
                ),
                hosted_sidecars=True,
                browser_origin_tls_mode="managed_exact",
                browser_origin_tls_root=str(root / "tls"),
                browser_origin_acme_webroot=str(root / "acme-sidecars"),
                acme_root=root / "acme-main",
                live_nginx_conf_path=root / "sites-available" / "maverick.conf",
                live_nginx_enabled_path=root / "sites-enabled" / "maverick.conf",
            )
            commands: list[list[str]] = []

            request_tls_certificate(config, run_command=commands.append)

        managed_index = next(
            index
            for index, command in enumerate(commands)
            if "core.shared.browser_origin_tls" in command
        )
        reload_index = commands.index(["systemctl", "reload", "nginx"])
        self.assertLess(managed_index, reload_index)
        self.assertIn(["nginx", "-t"], commands)


if __name__ == "__main__":
    unittest.main()
