"""Tests for the Maverick installer CLI and rendering helpers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.shared.installer import (
    InstallerConfig,
    _ensure_symlink,
    _write_file,
    apply_install_plan,
    check_health,
    default_install_env_path,
    default_live_nginx_conf_path,
    default_live_nginx_enabled_path,
    default_live_systemd_dir,
    default_nginx_conf_path,
    default_output_root,
    default_systemd_dir,
    request_tls_certificate,
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


class InstallerFlowTestCase(unittest.TestCase):
    def secret_args(self, output_root: Path) -> list[str]:
        return [
            "--secret-key-file",
            str(output_root / "bootstrap-secrets" / "secret-store.key"),
            "--bootstrap-secret-store-root",
            str(output_root / "bootstrap-secrets"),
        ]

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
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, 2)
        mocked_apply.assert_not_called()

    def test_installer_main_runs_bootstrap_and_verify_when_requested(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.subprocess.run") as mocked_run:
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
            with patch("core.shared.installer.subprocess.run") as mocked_run:
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

    def test_installer_main_installs_mongo_extra_when_mongo_control_store_is_selected(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            with patch("core.shared.installer.subprocess.run") as mocked_run:
                exit_code = installer_main(
                    [
                        "--local-only",
                        "--control-store",
                        "mongo",
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
        self.assertEqual(mocked_run.call_args_list[0].args[0], [str(repo_root / "scripts" / "bootstrap_local.sh")])
        self.assertEqual(mocked_run.call_args_list[0].kwargs["env"]["MAVERICK_PYPROJECT_EXTRAS"], "dev,mongo")

    def test_installer_main_applies_live_plan_when_confirmed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maverick-install-") as temp_dir:
            output_root = Path(temp_dir) / "install"
            live_systemd_dir = Path(temp_dir) / "live-systemd"
            live_nginx_conf = Path(temp_dir) / "sites-available" / "maverick.example.test.conf"
            live_nginx_enabled = Path(temp_dir) / "sites-enabled" / "maverick.example.test.conf"
            with patch("core.shared.installer.run_privileged_command") as mocked_runner, patch(
                "scripts.install_maverick.check_health",
                return_value={"http://127.0.0.1:8014/health": True},
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
                        *self.secret_args(output_root),
                    ]
                )

        self.assertEqual(exit_code, 3)

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

            self.assertIn("ssl_certificate /etc/letsencrypt/live/maverick.example.test/fullchain.pem;", live_nginx_conf.read_text(encoding="utf-8"))
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
