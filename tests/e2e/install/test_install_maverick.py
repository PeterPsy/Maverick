"""Tests for the Maverick installer CLI and rendering helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from core.shared.installer import (
    InstallerConfig,
    check_health,
    default_install_env_path,
    default_live_nginx_conf_path,
    default_live_nginx_enabled_path,
    default_live_systemd_dir,
    default_nginx_conf_path,
    default_output_root,
    default_systemd_dir,
    preflight_check,
    render_install_plan,
    render_nginx_config,
    write_install_plan,
)
from scripts.install_maverick import build_config, main as installer_main, parse_args


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
            install_env_path=default_install_env_path(repo_root),
            live_systemd_dir=default_live_systemd_dir(),
            live_nginx_conf_path=None if hostname is None else default_live_nginx_conf_path(hostname=hostname),
            live_nginx_enabled_path=None if hostname is None else default_live_nginx_enabled_path(hostname=hostname),
            build_frontends=False,
        )

    def test_render_install_plan_renders_custom_hostname_and_units(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = self.make_config(repo_root, hostname="maverick.example.test", local_only=False)

        rendered = render_install_plan(config)

        core_service = rendered[config.systemd_dir / "maverick-core.service"]
        watchdog_service = rendered[config.systemd_dir / "maverick-backend-watchdog.service"]
        nginx_conf = rendered[config.nginx_conf_path]
        env_file = rendered[config.install_env_path]
        manifest = json.loads(rendered[config.output_root / "install-manifest.json"])
        self.assertIn("WorkingDirectory=" + str(repo_root), core_service)
        self.assertIn("EnvironmentFile=" + str(config.install_env_path), core_service)
        self.assertIn("EnvironmentFile=" + str(config.install_env_path), watchdog_service)
        self.assertIn("--port 8014", core_service)
        self.assertIn("MAVERICK_ADMIN_USERNAME=admin", env_file)
        self.assertNotIn("MAVERICK_ADMIN_PASSWORD=", env_file)
        self.assertNotIn("MAVERICK_ADMIN_PASSWORD_REF=", env_file)
        self.assertIn("MAVERICK_SECRET_KEY_FILE=data/bootstrap-secrets/secret-store.key", env_file)
        self.assertIn("MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT=data/bootstrap-secrets", env_file)
        self.assertIn("MAVERICK_RUNTIME_API_SECRET_REF=platform:secret-alias/runtime-api-secret", env_file)
        self.assertIn("MAVERICK_WIDGET_CONTEXT_SECRET_REF=platform:secret-alias/widget-context-secret", env_file)
        self.assertNotIn("MAVERICK_RUNTIME_API_SECRET=", env_file)
        self.assertNotIn("MAVERICK_WIDGET_CONTEXT_SECRET=", env_file)
        self.assertNotIn("MAVERICK_SECRET_STORE_KEY=", env_file)
        self.assertIn("MAVERICK_CONTROL_STORE=json", env_file)
        self.assertIn("MAVERICK_JSON_CONTROL_STORE_ROOT=data/control-plane/json", env_file)
        self.assertNotIn("MAVERICK_MONGODB_URI=", env_file)
        self.assertIn(repo_root / "data" / "bootstrap-secrets" / "secret-store.key", rendered)
        self.assertEqual(config.install_env_path, repo_root / ".env.maverick")
        self.assertNotIn(".maverick", config.install_env_path.parts)
        self.assertIn("server_name maverick.example.test;", nginx_conf)
        self.assertIn("location ^~ /.well-known/acme-challenge/", nginx_conf)
        self.assertNotIn("ssl_certificate", nginx_conf)
        self.assertEqual(manifest["public_url"], "https://maverick.example.test")
        self.assertEqual(manifest["live_systemd_dir"], "/etc/systemd/system")

    def test_write_install_plan_restricts_development_env_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            env_path = Path(temp_dir) / ".env"

            write_install_plan({env_path: "MAVERICK_ADMIN_USERNAME=admin\n"})

            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_render_install_plan_can_select_mongo_control_store(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = self.make_config(repo_root, hostname="maverick.example.test", local_only=False)
        config = replace(config, control_store="mongo")

        rendered = render_install_plan(config)
        env_file = rendered[config.install_env_path]

        self.assertIn("MAVERICK_CONTROL_STORE=mongo", env_file)
        self.assertIn("MAVERICK_MONGODB_URI=mongodb://127.0.0.1:27017/maverick", env_file)
        self.assertIn("MAVERICK_MONGODB_DATABASE=maverick", env_file)

    def test_render_nginx_config_can_force_https_after_certificate_request(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = self.make_config(repo_root, hostname="maverick.example.test", local_only=False)

        nginx_conf = render_nginx_config(config, force_https=True)

        self.assertIn("listen 443 ssl", nginx_conf)
        self.assertIn("ssl_certificate /etc/letsencrypt/live/maverick.example.test/fullchain.pem;", nginx_conf)
        self.assertIn("ssl_session_cache shared:MaverickSSL:10m;", nginx_conf)
        self.assertNotIn("shared:SSL:", nginx_conf)

    def test_render_install_plan_can_force_https_nginx_for_externally_managed_tls(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = self.make_config(repo_root, hostname="maverick.example.test", local_only=False)

        rendered = render_install_plan(config, force_https_nginx=True)
        nginx_conf = rendered[config.nginx_conf_path]

        self.assertIn("listen 443 ssl", nginx_conf)
        self.assertIn("ssl_certificate /etc/letsencrypt/live/maverick.example.test/fullchain.pem;", nginx_conf)

    def test_hosted_sidecars_render_wildcard_vhost_and_core_environment(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            self.make_config(repo_root, hostname="maverick.example.test", local_only=False),
            hosted_sidecars=True,
            sidecar_tls_cert_path="/run/tls/sidecars-fullchain.pem",
            sidecar_tls_key_path="/run/tls/sidecars-privkey.pem",
        )

        rendered = render_install_plan(config, force_https_nginx=True)
        nginx_conf = rendered[config.nginx_conf_path]
        env_file = rendered[config.install_env_path]
        manifest = json.loads(rendered[config.output_root / "install-manifest.json"])

        self.assertIn("server_name *.sidecars.maverick.example.test;", nginx_conf)
        self.assertIn("ssl_certificate /run/tls/sidecars-fullchain.pem;", nginx_conf)
        self.assertIn("proxy_buffering off;", nginx_conf)
        sidecar_server = nginx_conf.split("server_name *.sidecars.maverick.example.test;", 1)[1]
        self.assertNotIn("add_header X-Frame-Options", sidecar_server)
        self.assertIn("MAVERICK_SIDECAR_ORIGIN_MODE=hosted", env_file)
        self.assertIn("MAVERICK_SIDECAR_INSTALLATION_DOMAIN=maverick.example.test", env_file)
        self.assertIn("MAVERICK_SIDECAR_PLATFORM_ORIGIN=https://maverick.example.test", env_file)
        self.assertTrue(manifest["hosted_sidecars"])
        self.assertEqual(manifest["sidecar_origin_pattern"], "*.sidecars.maverick.example.test")

    def test_hosted_sidecars_fail_live_preflight_without_wildcard_tls_files(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            self.make_config(repo_root, hostname="maverick.example.test", local_only=False),
            hosted_sidecars=True,
            sidecar_tls_cert_path="/missing/sidecars-fullchain.pem",
            sidecar_tls_key_path="/missing/sidecars-privkey.pem",
        )

        with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
            report = preflight_check(config, live_apply=True, request_tls=False)

        self.assertIn("hosted sidecar TLS certificate not found: /missing/sidecars-fullchain.pem", report.errors)
        self.assertIn("hosted sidecar TLS private key not found: /missing/sidecars-privkey.pem", report.errors)

    def test_hosted_sidecars_fail_live_preflight_for_invalid_or_non_wildcard_tls(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-sidecar-tls-") as temp_dir:
            tls_root = Path(temp_dir)
            certificate_path = tls_root / "fullchain.pem"
            private_key_path = tls_root / "privkey.pem"
            certificate_path.write_text("not a certificate\n", encoding="utf-8")
            private_key_path.write_text("not a private key\n", encoding="utf-8")
            config = replace(
                self.make_config(repo_root, hostname="maverick.example.test", local_only=False),
                hosted_sidecars=True,
                sidecar_tls_cert_path=str(certificate_path),
                sidecar_tls_key_path=str(private_key_path),
            )

            with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
                malformed = preflight_check(config, live_apply=True, request_tls=False)

            self.assertIn(
                f"hosted sidecar TLS certificate is not valid PEM: {certificate_path}",
                malformed.errors,
            )
            self.assertIn(
                f"hosted sidecar TLS private key is not valid unencrypted PEM: {private_key_path}",
                malformed.errors,
            )

            _write_tls_pair(
                certificate_path,
                private_key_path,
                dns_names=["sc-one.sidecars.maverick.example.test"],
            )
            with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
                exact_host = preflight_check(config, live_apply=True, request_tls=False)

            self.assertIn(
                "hosted sidecar TLS certificate SAN does not include required wildcard: "
                "*.sidecars.maverick.example.test",
                exact_host.errors,
            )

    def test_hosted_sidecars_accept_only_a_valid_wildcard_certificate_and_matching_key(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-sidecar-tls-") as temp_dir:
            tls_root = Path(temp_dir)
            certificate_path = tls_root / "fullchain.pem"
            private_key_path = tls_root / "privkey.pem"
            _write_tls_pair(
                certificate_path,
                private_key_path,
                dns_names=["*.sidecars.maverick.example.test"],
            )
            config = replace(
                self.make_config(repo_root, hostname="maverick.example.test", local_only=False),
                hosted_sidecars=True,
                sidecar_tls_cert_path=str(certificate_path),
                sidecar_tls_key_path=str(private_key_path),
            )

            with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
                valid = preflight_check(config, live_apply=True, request_tls=False)

            self.assertEqual(valid.errors, [])

            unrelated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            private_key_path.write_bytes(
                unrelated_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            with patch("core.shared.installer.shutil.which", return_value="/usr/bin/tool"):
                mismatched = preflight_check(config, live_apply=True, request_tls=False)

            self.assertIn(
                "hosted sidecar TLS certificate and private key do not match",
                mismatched.errors,
            )

    def test_render_install_plan_skips_nginx_for_local_only_mode(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = self.make_config(repo_root, hostname=None, local_only=True)

        rendered = render_install_plan(config)

        self.assertEqual(json.loads(rendered[config.output_root / "install-manifest.json"])["public_url"], "http://127.0.0.1:8014")
        self.assertIn(config.install_env_path, rendered)

    def test_check_health_retries_until_public_url_is_ready(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = self.make_config(repo_root, hostname="maverick.example.test", local_only=False)
        sleeps: list[float] = []

        with patch(
            "core.shared.installer._url_is_healthy",
            side_effect=[True, False, False, True],
        ) as mocked_probe:
            result = check_health(
                config,
                attempts=3,
                delay_seconds=0.25,
                sleep_func=sleeps.append,
            )

        self.assertEqual(result["http://127.0.0.1:8014/health"], True)
        self.assertEqual(result["https://maverick.example.test/health"], True)
        self.assertEqual(mocked_probe.call_count, 4)
        self.assertEqual(sleeps, [0.25, 0.25])

    def test_check_health_probes_sidecar_and_app_frame_origin_shapes(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        config = replace(
            self.make_config(repo_root, hostname="maverick.example.test", local_only=False),
            hosted_sidecars=True,
        )

        with patch("core.shared.installer._url_is_healthy", return_value=True), patch(
            "core.shared.installer_tls.hosted_browser_origin_is_healthy",
            return_value=True,
        ) as mocked_sidecar_probe:
            result = check_health(config, attempts=1)

        sidecar_url = "https://sc-000000000000000000000000.sidecars.maverick.example.test/"
        app_frame_url = "https://af-000000000000000000000000.sidecars.maverick.example.test/"
        self.assertEqual(result[sidecar_url], True)
        self.assertEqual(result[app_frame_url], True)
        self.assertEqual(
            mocked_sidecar_probe.call_args_list,
            [
                call(sidecar_url, timeout_seconds=5.0),
                call(app_frame_url, timeout_seconds=5.0),
            ],
        )


class InstallerFlowTestCase(unittest.TestCase):
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

    def test_installer_main_writes_rendered_files_without_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            exit_code = installer_main(
                [
                    "--hostname",
                    "maverick.example.test",
                    "--output-root",
                    str(output_root),
                    "--install-env",
                    str(output_root / "maverick.env"),
                    "--skip-bootstrap",
                    "--skip-verify",
                    "--render-only",
                    "--yes",
                    *self.secret_args(output_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_root / "systemd" / "maverick-core.service").is_file())
            self.assertTrue((output_root / "nginx" / "maverick.example.test.conf").is_file())
            self.assertTrue((output_root / "install-manifest.json").is_file())
            self.assertTrue((output_root / "maverick.env").is_file())
            self.assertNotIn("MAVERICK_CODEX_COMMAND=", (output_root / "maverick.env").read_text(encoding="utf-8"))

    def test_installer_main_prompts_for_hostname_when_missing(self) -> None:
        args = parse_args(["--skip-bootstrap", "--skip-verify", "--render-only"])
        with patch("builtins.input", side_effect=["public", "maverick.example.test", "", "", "", "", "", "", "", "", ""]), patch(
            "scripts.install_maverick.getpass.getpass",
            return_value="",
        ):
            config = build_config(args, interactive=True)
        self.assertEqual(config.hostname, "maverick.example.test")
        self.assertFalse(config.local_only)

    def test_build_config_rejects_install_root_that_is_not_checkout_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-root-") as temp_dir:
            args = parse_args(
                [
                    "--local-only",
                    "--install-root",
                    str(Path(temp_dir)),
                    "--skip-bootstrap",
                    "--skip-verify",
                    "--render-only",
                    "--yes",
                ]
            )

            with self.assertRaises(SystemExit):
                build_config(args, interactive=False)

    def test_installer_main_blocks_live_apply_when_required_tools_are_missing(self) -> None:
        def fake_which(command: str) -> str | None:
            if command in {"systemctl", "nginx", "certbot", "codex", "bubblewrap", "bwrap"}:
                return None
            return f"/usr/bin/{command}"

        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.shutil.which", side_effect=fake_which), patch(
                "scripts.install_maverick.apply_install_plan"
            ) as mocked_apply:
                exit_code = installer_main(
                    [
                        "--hostname",
                        "maverick.example.test",
                        "--output-root",
                        str(output_root),
                        "--install-env",
                        str(output_root / "maverick.env"),
                        "--skip-bootstrap",
                        "--skip-verify",
                        "--skip-tls",
                        "--yes",
                        *self.admin_password_args(output_root),
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, 2)
        mocked_apply.assert_not_called()

    def test_installer_main_runs_bootstrap_and_verify_when_requested(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.node_runtime_diagnostic", return_value=None), patch(
                "core.shared.installer.subprocess.run"
            ) as mocked_run:
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--output-root",
                        str(output_root),
                        "--install-env",
                        str(output_root / "maverick.env"),
                        "--render-only",
                        "--yes",
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_count, 2)
        self.assertEqual(mocked_run.call_args_list[0].args[0], [str(repo_root / "scripts" / "bootstrap_local.sh")])
        self.assertEqual(mocked_run.call_args_list[1].args[0], [str(repo_root / "scripts" / "verify_local.sh")])
        self.assertNotIn("MAVERICK_BUILD_FRONTENDS", mocked_run.call_args_list[0].kwargs["env"])

    def test_installer_main_passes_frontend_build_flag_to_bootstrap(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.node_runtime_diagnostic", return_value=None), patch(
                "core.shared.installer.subprocess.run"
            ) as mocked_run:
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--output-root",
                        str(output_root),
                        "--install-env",
                        str(output_root / "maverick.env"),
                        "--render-only",
                        "--build-frontends",
                        "--yes",
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_args_list[0].args[0], [str(repo_root / "scripts" / "bootstrap_local.sh")])
        self.assertEqual(mocked_run.call_args_list[0].kwargs["env"]["MAVERICK_BUILD_FRONTENDS"], "1")

    def test_installer_main_applies_live_plan_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            live_systemd_dir = Path(temp_dir) / "live-systemd"
            live_nginx_conf = Path(temp_dir) / "sites-available" / "maverick.example.test.conf"
            live_nginx_enabled = Path(temp_dir) / "sites-enabled" / "maverick.example.test.conf"
            with patch("core.shared.installer.run_privileged_command") as mocked_runner, patch(
                "scripts.install_maverick.check_health",
                return_value={"http://127.0.0.1:8014/health": True},
            ), patch(
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
                        "--skip-tls",
                        "--force",
                        *self.admin_password_args(output_root),
                        *self.secret_args(output_root),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((live_systemd_dir / "maverick-core.service").is_file())
            self.assertTrue(live_nginx_conf.is_file())
            self.assertTrue(live_nginx_enabled.is_symlink())
            self.assertTrue(mocked_runner.call_args_list)

    def test_installer_main_fails_when_post_apply_health_check_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            live_systemd_dir = Path(temp_dir) / "live-systemd"
            with patch("core.shared.installer.run_privileged_command"), patch(
                "scripts.install_maverick.check_health",
                return_value={"http://127.0.0.1:8014/health": False},
            ), patch(
                "scripts.install_maverick._apply_initial_admin_password",
            ):
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--output-root",
                        str(output_root),
                        "--live-systemd-dir",
                        str(live_systemd_dir),
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

        self.assertEqual(exit_code, 3)


def _write_tls_pair(certificate_path: Path, private_key_path: Path, *, dns_names: list[str]) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0])]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0])]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name) for name in dns_names]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


if __name__ == "__main__":
    unittest.main()
